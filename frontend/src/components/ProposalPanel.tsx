import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { listTemplates } from "../pages/RunPage";
import { defaults, ParamsEditor, type ParamValue } from "./ParamsEditor";

export interface Proposal {
  id: number;
  hypothesis: string;
  status: "proposed" | "approved" | "rejected";
  title: string;
  method: string;
  method_title: string;
  snapshot_id: number | null;
  snapshot: string;
  params: Record<string, unknown>;
  setup: string[];
  expected: string;
  rationale: string;
  problems: string;
  note: string;
  decided_by: string;
  experiment: string;
  run_id: number | null;
  created_at: string;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/experiment-proposals${path}`, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const body = (await res.json().catch(() => null)) as (T & { detail?: unknown }) | null;
  if (!res.ok || body === null) throw new Error(typeof body?.detail === "string" ? body.detail : `Ошибка ${res.status}`);
  return body;
}

export const proposalsFor = (code: string) => call<Proposal[]>(`?hypothesis=${encodeURIComponent(code)}`);

function Editable({ p, canDecide }: { p: Proposal; canDecide: boolean }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const templates = useQuery({ queryKey: ["run-templates"], queryFn: listTemplates });
  const [title, setTitle] = useState(p.title);
  const [method, setMethod] = useState(p.method);
  const [snapshot, setSnapshot] = useState<number | null>(p.snapshot_id);
  const [params, setParams] = useState<Record<string, ParamValue>>({});
  const [setup, setSetup] = useState(p.setup.join("\n"));
  const [expected, setExpected] = useState(p.expected);
  const [note, setNote] = useState("");
  const t = templates.data?.find((x) => x.key === method);
  useEffect(() => {
    // метод сменился — его параметры; тот же, что предложила Qwen, — её значения
    setParams(defaults(t?.params ?? [], method === p.method ? p.params : {}));
  }, [t, method, p.method, p.params]);
  const body = () => ({
    title,
    method,
    snapshot_id: snapshot,
    params,
    setup: setup.split("\n").map((x) => x.trim()).filter(Boolean),
    expected,
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["proposals", p.hypothesis] });
    void qc.invalidateQueries({ queryKey: ["hypotheses"] });
    void qc.invalidateQueries({ queryKey: ["experiments"] });
  };
  const approve = useMutation({
    mutationFn: () => call<Proposal>(`/${p.id}/approve`, { method: "POST", body: JSON.stringify(body()) }),
    onSuccess: (r) => {
      refresh();
      if (r.run_id) navigate(`/run/${r.run_id}`);
    },
  });
  const save = useMutation({
    mutationFn: () => call<Proposal>(`/${p.id}`, { method: "PATCH", body: JSON.stringify(body()) }),
    onSuccess: refresh,
  });
  const reject = useMutation({
    mutationFn: () => call<Proposal>(`/${p.id}/reject`, { method: "POST", body: JSON.stringify({ note }) }),
    onSuccess: refresh,
  });
  const error = approve.error ?? save.error ?? reject.error;
  const snaps = t?.snapshots ?? [];
  return (
    <div className="proposal">
      <div className="kb-meta">
        <span className="badge st-running">Qwen предлагает эксперимент</span>
        <span className="muted">{new Date(p.created_at).toLocaleDateString("ru-RU")}</span>
      </div>
      {p.rationale && <p className="muted pre-line">{p.rationale}</p>}
      {p.problems && (
        <p className="blockers" role="status">
          Перед запуском поправьте: {p.problems}
        </p>
      )}
      {canDecide ? (
        <>
          <label className="field">
            Название эксперимента
            <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={512} />
          </label>
          <div className="form-grid">
            <label className="field">
              Метод
              <select value={method} onChange={(e) => setMethod(e.target.value)}>
                <option value="">— выберите метод —</option>
                {(templates.data ?? []).map((x) => (
                  <option key={x.key} value={x.key}>
                    {x.scope === "replication" ? "Повтор · " : ""}
                    {x.title}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Срез данных
              <select value={snapshot ?? ""} onChange={(e) => setSnapshot(e.target.value ? Number(e.target.value) : null)}>
                <option value="">— выберите срез —</option>
                {snaps.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.dataset} · {s.version}
                    {s.row_count ? ` · ${s.row_count} строк` : ""}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {t && <p className="muted">{t.description}</p>}
          {t && <ParamsEditor params={t.params} snapshotId={snapshot} value={params} onChange={setParams} idPrefix={`prop-${p.id}`} />}
          <label className="field">
            Протокол — шаг на строку
            <textarea rows={4} value={setup} onChange={(e) => setSetup(e.target.value)} />
          </label>
          <label className="field">
            Что подтвердит или опровергнет гипотезу
            <textarea rows={2} value={expected} onChange={(e) => setExpected(e.target.value)} />
          </label>
          {error && (
            <p className="error" role="alert">
              {error.message}
            </p>
          )}
          <div className="review-form">
            <button type="button" className="btn-primary" disabled={approve.isPending || !method || snapshot === null} onClick={() => approve.mutate()}>
              {approve.isPending ? "Создаю и запускаю…" : "Одобрить и запустить"}
            </button>
            <button type="button" className="btn-ghost" disabled={save.isPending} onClick={() => save.mutate()}>
              Сохранить правки
            </button>
          </div>
          <div className="review-form">
            <label className="field inline grow">
              Почему отклоняете (увидит лаборатория)
              <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
            </label>
            <button type="button" className="btn-ghost" disabled={reject.isPending || note.trim().length < 3} onClick={() => reject.mutate()}>
              Отклонить
            </button>
          </div>
        </>
      ) : (
        <>
          <p>
            <strong>{p.title}</strong> — {p.method_title || "метод не выбран"}
            {p.snapshot && <> на {p.snapshot}</>}
          </p>
          {p.setup.length > 0 && (
            <ul className="list muted">
              {p.setup.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          )}
          {p.expected && <p className="muted">Что подтвердит или опровергнет: {p.expected}</p>}
        </>
      )}
    </div>
  );
}

/** Предложение эксперимента от Qwen на карточке гипотезы. */
export function ProposalPanel({ code, status, canDecide }: { code: string; status: string; canDecide: boolean }) {
  const q = useQuery({
    queryKey: ["proposals", code],
    queryFn: () => proposalsFor(code),
    enabled: status === "accepted" || status === "testing" || status === "tested",
    refetchInterval: (query) => (status === "accepted" && (query.state.data ?? []).length === 0 ? 30_000 : false),
  });
  const list = q.data ?? [];
  const open = list.find((p) => p.status === "proposed");
  const approved = list.find((p) => p.status === "approved");
  if (status === "accepted" && q.isSuccess && list.length === 0) {
    return <p className="muted">Qwen готовит предложение эксперимента — появится здесь через несколько минут.</p>;
  }
  return (
    <>
      {open && <Editable key={open.id} p={open} canDecide={canDecide && status === "accepted"} />}
      {approved && (
        <p className="muted">
          Эксперимент по предложению Qwen:{" "}
          <Link to={`/experiments/${approved.experiment}`} className="mono">
            {approved.experiment}
          </Link>
          {approved.run_id && (
            <>
              , запуск <Link to={`/run/${approved.run_id}`}>№{approved.run_id}</Link>
            </>
          )}{" "}
          (одобрил {approved.decided_by})
        </p>
      )}
      {list
        .filter((p) => p.status === "rejected")
        .map((p) => (
          <p key={p.id} className="muted">
            Предложение Qwen «{p.title}» отклонено ({p.decided_by}): {p.note}
          </p>
        ))}
    </>
  );
}
