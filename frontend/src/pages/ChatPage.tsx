import { useQuery } from "@tanstack/react-query";
import { type FormEvent, Fragment, type ReactNode, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { kbTree } from "../api/kb";

const ROOT = "esg";

interface Source {
  n: number;
  doc_id: string;
  title: string;
  year: number | null;
  pages: number[];
  headings: string[];
  text: string;
}

interface Turn {
  question: string;
  answer: string;
  status: string;
  sources: Source[];
  used: number[];
  general: boolean; // в базе не нашлось — ответ без неё
  removed: number; // фраз без подтверждающей ссылки убрано
  seconds: number | null;
  error: string;
  pending: boolean;
}

interface ChatEvent {
  type: string;
  text?: string;
  error?: string;
  sources?: Source[];
  used?: number[];
  removed?: number;
  unsupported?: number;
  seconds?: number;
  off_topic?: boolean;
  not_found?: boolean;
}

/** Ответ модели: абзацы, **жирный**, ссылки [1] и [1, 3] — на источники ниже. */
function Answer({ text, turn }: { text: string; turn: number }) {
  const inline = (line: string): ReactNode[] =>
    line.split(/(\*\*[^*]+\*\*|\[\d+(?:\s*[,–-]\s*\d+)*\])/g).map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
      const refs = /^\[(.+)\]$/.exec(part);
      if (refs) {
        const nums = (refs[1] ?? "").split(/\s*[,–-]\s*/).filter(Boolean);
        return (
          <sup key={i} className="cite">
            [
            {nums.map((n, j) => (
              <Fragment key={n}>
                {j > 0 && ", "}
                <a href={`#src-${turn}-${n}`}>{n}</a>
              </Fragment>
            ))}
            ]
          </sup>
        );
      }
      return <Fragment key={i}>{part}</Fragment>;
    });
  return (
    <div className="answer">
      {text
        .split(/\n{2,}/)
        .filter((p) => p.trim())
        .map((p, i) => (
          <p key={i}>
            {p.split("\n").map((line, j) => (
              <Fragment key={j}>
                {j > 0 && <br />}
                {inline(line.replace(/^\s*[-*]\s+/, "• "))}
              </Fragment>
            ))}
          </p>
        ))}
    </div>
  );
}

function Sources({ turn, index }: { turn: Turn; index: number }) {
  const shown = turn.used.length > 0 ? turn.sources.filter((s) => turn.used.includes(s.n)) : turn.sources;
  if (shown.length === 0) return null;
  return (
    <details className="chat-sources" open={turn.used.length > 0}>
      <summary>
        Источники: {shown.length} {turn.used.length > 0 ? "фрагментов, на которые есть ссылки" : "найденных фрагментов"}
      </summary>
      <ol>
        {shown.map((s) => (
          <li key={s.n} id={`src-${index}-${s.n}`} value={s.n}>
            <Link to={`/knowledge/article/${encodeURIComponent(s.doc_id)}`}>{s.title || s.doc_id}</Link>
            <span className="muted">
              {s.year ? `, ${s.year}` : ""}
              {s.pages.length > 0 ? ` · с. ${s.pages.join("–")}` : ""}
              {s.headings.length > 0 ? ` · ${s.headings[s.headings.length - 1]}` : ""}
            </span>
            <blockquote>{s.text.length > 420 ? `${s.text.slice(0, 420)}…` : s.text}</blockquote>
          </li>
        ))}
      </ol>
    </details>
  );
}

export function Chat() {
  const [kb, setKb] = useState(ROOT);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const tree = useQuery({ queryKey: ["kb", "kbs"], queryFn: () => kbTree(ROOT) });
  const branches = (tree.data?.nodes ?? []).filter((n) => n.path === ROOT || n.path.startsWith(`${ROOT}.`));
  const busy = turns.some((t) => t.pending);

  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => bottom.current?.scrollIntoView({ block: "end" }), [turns.length]);

  const update = (i: number, change: (t: Turn) => Partial<Turn>) =>
    setTurns((all) => all.map((t, j) => (j === i ? { ...t, ...change(t) } : t)));

  const ask = async (e: FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (q.length < 2 || busy) return;
    const history = turns
      .filter((t) => t.answer && !t.error)
      .slice(-5)
      .flatMap((t) => [
        { role: "user", content: t.question },
        { role: "assistant", content: t.answer },
      ]);
    const index = turns.length;
    setTurns((all) => [
      ...all,
      { question: q, answer: "", status: "отправляю вопрос…", sources: [], used: [], general: false, removed: 0, seconds: null, error: "", pending: true },
    ]);
    setQuestion("");
    const ctrl = new AbortController();
    abort.current = ctrl;
    try {
      const res = await fetch("/api/kb/chat", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, kb, history }),
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) {
        const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
        throw new Error(typeof body?.detail === "string" ? body.detail : `Ошибка ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const ev = JSON.parse(line) as ChatEvent;
          if (ev.type === "status") update(index, () => ({ status: ev.text ?? "" }));
          else if (ev.type === "sources") update(index, () => ({ sources: ev.sources ?? [] }));
          else if (ev.type === "token") update(index, (t) => ({ answer: t.answer + (ev.text ?? ""), status: "" }));
          else if (ev.type === "revised") update(index, () => ({ answer: ev.text ?? "" }));
          else if (ev.type === "general") update(index, () => ({ general: true, answer: ev.text ?? "", status: "" }));
          else if (ev.type === "done")
            update(index, () => ({
              used: ev.used ?? [],
              removed: (ev.removed ?? 0) + (ev.unsupported ?? 0),
              seconds: ev.seconds ?? null,
            }));
          else if (ev.type === "error") update(index, () => ({ error: ev.error ?? "ошибка" }));
        }
      }
    } catch (err) {
      const stopped = err instanceof DOMException && err.name === "AbortError";
      update(index, () => ({ error: stopped ? "Остановлено." : err instanceof Error ? err.message : String(err) }));
    } finally {
      update(index, () => ({ pending: false, status: "" }));
      abort.current = null;
    }
  };

  return (
    <>
      <section className="page-head">
        <span className="eyebrow">БАЗА ЗНАНИЙ · ЧАТ</span>
        <h1 className="page-title">Вопрос к базе знаний</h1>
        <p className="lead">
          Модель Qwen3 отвечает только по найденным фрагментам статей выбранной ветки. После каждого утверждения
          стоит номер фрагмента, фразы без подтверждения убираются. Если в базе ответа нет, бот так и скажет. Ответ
          занимает от 20 секунд до пары минут; если модель занята, вопрос встаёт в очередь.
        </p>
      </section>
      <div className="chat">
        {turns.map((t, i) => (
          <article key={i} className="card chat-turn">
            <p className="chat-q">
              <strong>Вопрос:</strong> {t.question}
            </p>
            {t.general && (
              <p className="notice" role="note">
                В базе знаний об этом не нашлось — ниже ответ не по статьям, а из общих знаний модели.
              </p>
            )}
            {t.answer && <Answer text={t.answer} turn={i} />}
            {t.pending && (
              <p className="muted" role="status">
                {t.status || "пишу ответ…"}
              </p>
            )}
            {t.error && (
              <p className="error" role="alert">
                {t.error}
              </p>
            )}
            {!t.pending && !t.error && (
              <p className="muted chat-meta">
                {t.seconds !== null && `${t.seconds.toLocaleString("ru-RU")} с`}
                {t.removed > 0 && ` · убрано фраз без подтверждения в статьях: ${t.removed}`}
              </p>
            )}
            <Sources turn={t} index={i} />
          </article>
        ))}
        <div ref={bottom} />
      </div>
      <form className="card chat-form" onSubmit={ask}>
        <label className="field inline" htmlFor="chat-kb">
          Ветка
          <select id="chat-kb" value={kb} onChange={(e) => setKb(e.target.value)} disabled={busy}>
            {branches.length === 0 && <option value={ROOT}>ESG</option>}
            {branches.map((b) => (
              <option key={b.path} value={b.path}>
                {"  ".repeat(b.depth)}
                {b.title}
              </option>
            ))}
          </select>
        </label>
        <label className="field grow" htmlFor="chat-q">
          Вопрос
          <textarea
            id="chat-q"
            rows={2}
            maxLength={2000}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="Например: как раскрытие ESG-информации влияет на стоимость капитала?"
          />
        </label>
        <div className="chat-actions">
          {busy ? (
            <button type="button" className="btn-ghost" onClick={() => abort.current?.abort()}>
              Стоп
            </button>
          ) : (
            <button type="submit" className="btn-primary" disabled={question.trim().length < 2}>
              Спросить
            </button>
          )}
          {turns.length > 0 && !busy && (
            <button type="button" className="btn-ghost" onClick={() => setTurns([])}>
              Новый разговор
            </button>
          )}
        </div>
      </form>
    </>
  );
}
