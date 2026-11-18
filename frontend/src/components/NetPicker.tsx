import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { checkLink, linkNets, type NetOption } from "../api/analysis";
import { plural } from "./Ux";

/** Что за сеть — простыми словами (п. 11 фидбека: понятно, чем проверяем). */
export function netAbout(n: Pick<NetOption, "id" | "net">): string {
  if (n.id.startsWith("method:")) return "Метод из статьи банка: модель авторов, тот же протокол проверки.";
  switch (n.net) {
    case "mlp":
      return "Нейросеть лаборатории: учится на всех показателях сразу и может уловить нелинейные эффекты.";
    case "transformer":
      return "Более сложная нейросеть: ищет, какие показатели важны вместе. Считается в разы дольше перцептрона.";
    case "gbm":
      return "Без нейросети: бустинг деревьев и линейная модель, за минуты. Если они не хуже — сложная сеть не нужна.";
    default:
      return "";
  }
}

const minutes = (m: number | null) => (m === null ? "" : m < 1 ? "< 1 мин" : `≈ ${Math.round(m).toLocaleString("ru-RU")} мин`);

/** Выбор перед проверкой связи: что предсказываем и какими сетями. Ничего не запускается, пока
 *  человек не нажмёт кнопку; уже считавшиеся сети видны и не выбираются второй раз. */
export function NetPicker({
  scanRun,
  a,
  b,
  fixedTarget,
  onDone,
}: {
  scanRun: number;
  a: string;
  b: string;
  fixedTarget?: string; // проверка уже есть — что предсказываем, решено
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const [target, setTarget] = useState(fixedTarget ?? b);
  const [picked, setPicked] = useState<Set<string> | null>(null); // null — выбор по умолчанию
  const body = { scan_run: scanRun, a, b, target, node: "" };
  const menu = useQuery({ queryKey: ["link-nets", scanRun, a, b, target], queryFn: () => linkNets(body), retry: false });
  const options = menu.data?.nets ?? [];
  const free = (n: NetOption) => n.runnable && !n.done;
  const chosen = picked ?? new Set(options.filter((n) => free(n) && n.recommended).map((n) => n.id));
  const selected = options.filter((n) => free(n) && chosen.has(n.id));
  const total = selected.reduce((s, n) => s + (n.minutes ?? 0), 0);
  const existing = menu.data?.existing ?? null;
  const go = useMutation({
    mutationFn: () => checkLink({ ...body, nets: selected.map((n) => n.id) }),
    onSuccess: () => {
      for (const key of ["links", "experiments", "runs", "link-nets"]) void qc.invalidateQueries({ queryKey: [key] });
      onDone();
    },
  });
  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setPicked(next);
  };
  const other = target === a ? b : a;
  const groupId = `nets-${a}-${b}`;
  return (
    <div className="net-picker">
      {!fixedTarget && (
        <fieldset>
          <legend>Что предсказываем</legend>
          {[b, a].map((t) => (
            <label key={t} className="net-target">
              <input
                type="radio"
                name={`target-${a}-${b}`}
                checked={target === t}
                onChange={() => {
                  setTarget(t);
                  setPicked(null);
                }}
              />{" "}
              «{t}» по «{t === a ? b : a}» и остальным показателям
            </label>
          ))}
        </fieldset>
      )}
      <fieldset aria-describedby={`${groupId}-hint`}>
        <legend>Какими сетями проверить</legend>
        <p className="muted net-sub" id={`${groupId}-hint`}>
          Каждая выбранная сеть предсказывает «{target}» по «{other}» и остальным показателям — на данных, которых не
          было в обучении. Если хотя бы у нескольких сетей связь держится, это уже не случайность одной модели.
        </p>
        {menu.isPending && <p className="muted">Смотрю, какие сети подходят…</p>}
        {menu.isError && (
          <p className="error" role="alert">
            {menu.error.message}
          </p>
        )}
        {options.map((n) => {
          const id = `${groupId}-${n.id}`;
          return (
            <label key={n.id} htmlFor={id} className={free(n) ? "net-option" : "net-option disabled"}>
              <input
                id={id}
                type="checkbox"
                disabled={!free(n)}
                checked={n.done || (free(n) && chosen.has(n.id))}
                onChange={() => toggle(n.id)}
              />
              <span className="method-option-body">
                <strong>{n.title}</strong>
                {n.recommended && free(n) && <span className="badge st-done">рекомендуем</span>}
                {n.done && <span className="badge st-review">уже в проверке</span>}
                {n.minutes !== null && !n.done && <span className="muted"> · {minutes(n.minutes)}</span>}
                <span className="method-line">{netAbout(n)}</span>
                {n.note && <span className="method-line muted">{n.note}</span>}
                {!n.runnable && n.warnings.map((w) => <span key={w} className="method-line blockers">{w}</span>)}
              </span>
            </label>
          );
        })}
      </fieldset>
      {options.length > 0 && (
        <div className="net-picker-go">
          <button type="button" className="btn-primary" disabled={selected.length === 0 || go.isPending} onClick={() => go.mutate()}>
            {go.isPending
              ? "Ставлю расчёты…"
              : selected.length === 0
                ? "Отметьте хотя бы одну сеть"
                : existing
                ? `Добавить к ${existing}: ${plural(selected.length, "сеть", "сети", "сетей")}`
                : `Проверить: ${plural(selected.length, "сеть", "сети", "сетей")}`}
          </button>
          {selected.length > 0 && <span className="muted"> в сумме {minutes(total)} расчёта</span>}
          {existing && (
            <span className="muted">
              {" "}
              · проверка <Link to={`/experiments/${existing}`}>{existing}</Link>
            </span>
          )}
        </div>
      )}
      {go.isError && (
        <p className="error" role="alert">
          {go.error.message}
        </p>
      )}
    </div>
  );
}
