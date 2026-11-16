/** Ручной режим (п. 9–10 фидбека): в любой момент взять работу в свои руки — Jupyter или командная строка.
 *  Архив собирает сервер (backend/app/services/manual.py); команды — cli/README.md. */
export function ManualMode({ run, snapshot, compact = false }: { run?: number; snapshot?: number; compact?: boolean }) {
  const href = run !== undefined ? `/api/runs/${run}/manual.zip` : `/api/snapshots/${snapshot ?? 0}/manual.zip`;
  const cli = run !== undefined ? `esg notebook --run ${run}` : `esg notebook --snapshot ${snapshot ?? 0}`;
  const what = run !== undefined ? "расчёт" : "эти данные";
  if (compact) {
    return (
      <a className="link-btn" href={href} download title={`Ноутбук Jupyter: ${what} — в свои руки`}>
        ноутбук Jupyter
      </a>
    );
  }
  return (
    <details className="card details-card manual-mode">
      <summary>Ручной режим: взять {what} в свои руки</summary>
      <p className="muted">
        {run !== undefined
          ? "Архив с ноутбуком Jupyter: данные (если они вам доступны), код метода, параметры и итоги платформы. Ноутбук проверит данные, повторит расчёт той же командой и сверит итоги — дальше ваш код."
          : "Архив с ноутбуком Jupyter и файлом этой версии данных (если он вам доступен): загрузить таблицу и обрабатывать её как угодно."}{" "}
        Платформа не узнает, что вы делаете в ноутбуке; в реестр результат попадает только из клона репозитория.
      </p>
      <p>
        <a className="btn-ghost" href={href} download>
          Скачать ноутбук Jupyter
        </a>
      </p>
      <p className="muted">
        Или в командной строке: <code className="mono">{cli}</code> — установка и все команды: <code className="mono">cli/README.md</code>{" "}
        в репозитории.
      </p>
    </details>
  );
}
