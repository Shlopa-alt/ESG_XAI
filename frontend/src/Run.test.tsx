import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { experimentNext } from "./components/Ux";
import type { RunRow, RunStatus } from "./pages/RunPage";

// Заглушки — не реальные данные: проверяется только поведение мастера
const USER = { id: 1, login: "[researcher]", full_name: "", email: "", role: "researcher", nda_access: false };
const HYP = {
  code: "H-001",
  title: "[идея]",
  statement: "[утверждение]",
  rationale: "",
  direction: "",
  status: "accepted",
  decision_note: "",
  author: "",
  decided_by: "",
  experiment: "",
  methodology_node: "",
  source: "qwen",
  suggested: {},
  created_at: "2026-11-01T00:00:00Z",
  refs: [],
};
const PROPOSAL = {
  id: 7,
  hypothesis: "H-001",
  status: "proposed",
  from_qwen: true,
  title: "[проверка]",
  method: "rank-agreement",
  method_title: "[метод]",
  snapshot_id: 1,
  snapshot: "DS-01 · [версия данных]",
  params: {},
  setup: [],
  expected: "",
  rationale: "",
  problems: "",
  note: "",
  decided_by: "",
  experiment: "",
  run_id: null,
  created_at: "2026-11-01T00:00:00Z",
};
const SNAPSHOTS = [{ id: 1, dataset: "DS-01", version: "[версия данных]", sha256: "", row_count: 10 }];
const GENERIC = {
  key: "predictive-check",
  title: "[общий метод]",
  description: "[описание]",
  scope: "generic",
  experiment: "",
  dataset: "",
  resource: "cpu",
  limit_min: 60,
  params: [{ name: "target", label: "Целевой столбец", default: "", min: 0, max: 0, kind: "column", numeric: true, required: true, hint: "" }],
  snapshots: SNAPSHOTS,
};
const REPEAT = { ...GENERIC, key: "exp007-hsu", title: "[повтор]", scope: "replication", dataset: "DS-01", limit_min: 240, params: [] };

const RUN = {
  id: 5,
  experiment: "EXP-009",
  status: "queued",
  resource: "cpu",
  template: "rank-agreement",
  config: { params: {} },
  runner_commit: "",
  dataset: "",
  dataset_sha256: "",
  env_lock_sha256: "",
  python: "",
  seeds: {},
  parts: {},
  summary: {},
  results_path: "",
  mlflow_run_id: "",
  message: "",
  author: "",
  started_at: null,
  finished_at: null,
  created_at: null,
  reproducible: false,
  note: "",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

type Sent = { url: string; body: Record<string, unknown> };

/** Сервер-заглушка: на POST отвечает по первому подходящему правилу из `posts`, остальное — обычные списки. */
function api({
  proposals = [] as unknown[] | Response,
  wait = { job: "queued", worker: true },
  templates = [GENERIC, REPEAT] as unknown[],
  hypotheses = [HYP] as unknown[] | Response,
  posts = {} as Record<string, () => Response>,
  me = USER,
} = {}) {
  const sent: Sent[] = [];
  const answer = (v: unknown[] | Response) => (v instanceof Response ? v.clone() : json(v));
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        sent.push({ url, body: JSON.parse(String(init.body ?? "{}")) as Record<string, unknown> });
        const rule = Object.entries(posts).find(([k]) => url.includes(k));
        return Promise.resolve(rule ? rule[1]() : json({ detail: "нет правила" }, 500));
      }
      if (url.includes("/auth/me")) return Promise.resolve(json(me));
      if (url.includes("/run-templates")) return Promise.resolve(json(templates));
      if (url.includes("/columns")) return Promise.resolve(json({ columns: ["roa"], numeric: ["roa"], sheets: [], sheet: "" }));
      if (url.includes("/experiment-proposals/wait")) return Promise.resolve(json(wait));
      if (url.includes("/experiment-proposals")) return Promise.resolve(answer(proposals));
      if (url.includes("/hypotheses")) return Promise.resolve(answer(hypotheses));
      if (/\/runs\/\d+$/.test(url)) return Promise.resolve(json(RUN));
      if (/\/experiments\/EXP-\d+$/.test(url)) return Promise.resolve(json({ detail: "[нет на заглушке]" }, 404));
      return Promise.resolve(json([]));
    }),
  );
  // после одобрения открывается страница запуска с живым потоком — в jsdom его нет
  vi.stubGlobal("EventSource", class { close() {} });
  return sent;
}

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const APPROVE = "Одобрить предложение и запустить";
const MANUAL = "Создать проверку и запустить";

afterEach(() => vi.unstubAllGlobals());

describe("Мастер расчёта: предложение ИИ-помощника", () => {
  it("показывает предложение, одобряет его и ведёт на страницу расчёта", async () => {
    const sent = api({
      proposals: [PROPOSAL],
      posts: { "/approve": () => json({ ...PROPOSAL, status: "approved", experiment: "EXP-009", run_id: 5 }) },
    });
    renderAt("/run?h=H-001");
    expect(await screen.findByText("[метод]")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: APPROVE }));
    expect(sent.map((s) => s.url)).toEqual(["/api/experiment-proposals/7/approve"]);
    // сразу переходим на страницу запуска с понятным «что дальше»
    expect(await screen.findByText(/стоит в очереди сервера/)).toBeInTheDocument();
  });

  it("повтор расчёта запускается только после явного подтверждения", async () => {
    const sent = api({
      proposals: [{ ...PROPOSAL, method: "exp007-hsu", method_title: "[повтор]" }],
      posts: { "/approve": () => json({ ...PROPOSAL, status: "approved", experiment: "EXP-009", run_id: 5 }) },
    });
    renderAt("/run?h=H-001");
    const box = await screen.findByRole("checkbox", { name: /этот повтор действительно проверяет/ });
    const go = screen.getByRole("button", { name: APPROVE });
    expect(go).toBeDisabled();
    await userEvent.click(box);
    expect(go).toBeEnabled();
    await userEvent.click(go);
    expect(sent[0]?.body).toEqual({ confirm_replication: true });
  });

  it("предложение можно отклонить, и только с причиной", async () => {
    const sent = api({ proposals: [PROPOSAL], posts: { "/reject": () => json({ ...PROPOSAL, status: "rejected" }) } });
    renderAt("/run?h=H-001");
    await screen.findByText("[метод]");
    await userEvent.click(screen.getByText("Отклонить предложение"));
    const reject = screen.getByRole("button", { name: "Отклонить" });
    expect(reject).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox", { name: /Почему отклоняете/ }), "нет данных");
    await userEvent.click(reject);
    await waitFor(() => expect(sent[0]).toEqual({ url: "/api/experiment-proposals/7/reject", body: { note: "нет данных" } }));
  });
});

describe("Мастер расчёта: предложения нет", () => {
  it("в очереди — объясняет ожидание и предлагает задать вручную", async () => {
    api();
    renderAt("/run");
    expect(await screen.findByText(/стоит в очереди ИИ-помощника/)).toBeInTheDocument();
    expect(screen.queryByText(/не на связи/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: APPROVE })).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: "Задам сам" }));
    expect(screen.getByRole("combobox", { name: "Метод" })).toBeInTheDocument();
  });

  it("обработчик не на связи — так и говорит", async () => {
    api({ wait: { job: "queued", worker: false } });
    renderAt("/run");
    expect(await screen.findByText(/не на связи/)).toBeInTheDocument();
  });

  it("задача сорвалась — не ждёт, а предлагает попросить ещё раз", async () => {
    const sent = api({
      wait: { job: "failed", worker: true },
      posts: { "/request": () => json({ job: "queued", worker: true }) },
    });
    renderAt("/run");
    expect(await screen.findByText(/не смогла подготовить предложение/)).toBeInTheDocument();
    expect(screen.queryByText(/ИИ-помощник готовит/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Попросить ИИ-помощника ещё раз" }));
    await waitFor(() => expect(sent[0]).toEqual({ url: "/api/experiment-proposals/request", body: { hypothesis: "H-001" } }));
  });

  it("предложение отклонено — показывает кем и почему", async () => {
    api({
      wait: { job: "done", worker: true },
      proposals: [{ ...PROPOSAL, status: "rejected", decided_by: "[логин]", note: "[причина]" }],
    });
    renderAt("/run");
    expect(await screen.findByText(/отклонено \(\[логин\]\): \[причина\]/)).toBeInTheDocument();
  });

  it("ошибка сервера — ошибка, а не ожидание", async () => {
    api({ proposals: json({ detail: "[сбой предложений]" }, 500) });
    renderAt("/run");
    expect((await screen.findByRole("alert")).textContent).toContain("[сбой предложений]");
    expect(screen.queryByText(/очереди ИИ-помощника/)).not.toBeInTheDocument();
  });

  it("ошибка списка идей — не «нет идей»", async () => {
    api({ hypotheses: json({ detail: "[сбой идей]" }, 500) });
    renderAt("/run");
    expect((await screen.findByRole("alert")).textContent).toContain("Не удалось загрузить идеи");
    expect(screen.queryByText(/Нет идей, принятых к проверке/)).not.toBeInTheDocument();
  });
});

describe("Мастер расчёта: задам сам", () => {
  async function fillManual() {
    await userEvent.click(await screen.findByRole("radio", { name: "Задам сам" }));
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Метод" }), "predictive-check");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /Данные/ }), "1");
  }

  it("пока не заполнено обязательное — кнопка неактивна и видно, чего не хватает", async () => {
    api();
    renderAt("/run");
    await fillManual();
    const go = screen.getByRole("button", { name: MANUAL });
    expect(go).toBeDisabled();
    expect(screen.getByText(/Чтобы запустить, укажите: целевой столбец, что подтвердит/)).toBeInTheDocument();
    await screen.findByRole("option", { name: "roa" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Целевой столбец" }), "roa");
    await userEvent.type(screen.getByRole("textbox", { name: /Что подтвердит/ }), "критерий");
    expect(go).toBeEnabled();
  });

  it("расчёт и проверка — один запрос; отказ сервера оставляет форму, можно повторить", async () => {
    let answers = 0;
    const sent = api({
      posts: {
        "/manual": () =>
          ++answers === 1 ? json({ detail: "[отказ сервера]" }, 422) : json({ ...PROPOSAL, status: "approved", experiment: "EXP-009", run_id: 5 }, 201),
      },
    });
    renderAt("/run");
    await fillManual();
    await screen.findByRole("option", { name: "roa" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Целевой столбец" }), "roa");
    await userEvent.type(screen.getByRole("textbox", { name: /Что подтвердит/ }), "критерий");
    await userEvent.click(screen.getByRole("button", { name: MANUAL }));
    expect((await screen.findByRole("alert")).textContent).toContain("[отказ сервера]");
    // отдельного создания эксперимента нет: сервер делает всё вместе
    expect(sent.map((s) => s.url)).toEqual(["/api/experiment-proposals/manual"]);
    expect(sent[0]?.body).toMatchObject({ hypothesis: "H-001", template: "predictive-check", snapshot_id: 1, expected: "критерий", params: { target: "roa" } });
    await userEvent.click(screen.getByRole("button", { name: MANUAL }));
    expect(await screen.findByText(/стоит в очереди сервера/)).toBeInTheDocument();
  });

  it("можно создать только карточку, если метода или данных пока нет", async () => {
    const sent = api({ posts: { "/hypotheses/H-001/experiment": () => json({ ...HYP, status: "testing", experiment: "EXP-009" }) } });
    renderAt("/run");
    await userEvent.click(await screen.findByRole("radio", { name: "Задам сам" }));
    await userEvent.click(screen.getByRole("button", { name: "Создать только карточку, без расчёта" }));
    await waitFor(() => expect(sent.map((s) => s.url)).toEqual(["/api/hypotheses/H-001/experiment"]));
  });
});

describe("Раздел «Проверки»", () => {
  it("вкладка «Расчёты» открывается своим адресом", async () => {
    api();
    renderAt("/runs");
    expect(await screen.findByRole("heading", { name: "Расчёты" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Новая проверка" })).toHaveAttribute("href", "/run");
    expect(screen.getByText("Расчётов пока нет.")).toBeInTheDocument();
  });

  it("читателя с новой проверки ведёт к списку расчётов", async () => {
    api({ me: { ...USER, role: "reader" } });
    renderAt("/run");
    expect(await screen.findByRole("heading", { name: "Расчёты" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Новая проверка" })).not.toBeInTheDocument();
  });
});

describe("Подсказка на карточке проверки", () => {
  const run = (status: RunStatus) => ({ ...RUN, status }) as RunRow;

  it("смотрит на последний расчёт, а не только на статус проверки", () => {
    expect(experimentNext("planned", [])).toMatch(/Расчёта ещё нет/);
    expect(experimentNext("planned", [run("running")])).toMatch(/Идёт расчёт/);
    expect(experimentNext("running", [run("done")])).toMatch(/Расчёт завершён/);
    expect(experimentNext("running", [run("failed"), run("done")])).toMatch(/не удался/);
    expect(experimentNext("done", [run("done")])).toMatch(/Проверка завершена/);
  });
});

describe("Карточка идеи", () => {
  it("у предложенной идеи источники раскрыты: они нужны для решения", async () => {
    const refs = [{ kind: "article", kbrag_id: "d", title: "[статья]", doi: "", quote: "[цитата]" }];
    api({ hypotheses: [{ ...HYP, status: "proposed", refs }, { ...HYP, code: "H-002", title: "[вторая]", status: "testing", refs }] });
    renderAt("/hypotheses");
    await screen.findByText("[идея]");
    const [first] = screen.getAllByText(/Источники в банке статей/).map((el) => el.closest("details"));
    expect(first).toHaveAttribute("open");
  });
});
