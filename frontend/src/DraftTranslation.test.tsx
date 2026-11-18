import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

// Заглушки — не реальные данные: проверяется только переключатель перевода черновика
const user = (role: string) => ({ id: 1, login: "[логин]", full_name: "", email: "", role, nda_access: false });
const ITEM = {
  id: 9, status: "proposed", title: "[Sample of firms]", article_title: "[статья]", doi: "", doc_id: "[doc]", table_number: 2,
  page: 4, n_rows: 2, n_cols: 2, dataset: "", created_at: "2026-11-01T00:00:00Z", source_kind: "table", source_url: "",
  lang: "en", title_ru: "[Выборка компаний]",
};
const TRANSLATION = {
  lang: "en", lang_title: "английский", supported: true, can_translate: true, has_texts: true, source: "en", engine: "Argos Translate 1.9", done_at: null,
  pending: "", failed: "", translator_online: null,
  pairs: { "[Sample of firms]": "[Выборка компаний]", "[Size]": "[Размер]", "[Large]": "[Крупная]" },
};
const DRAFT = {
  ...ITEM, kb_path: "esg", caption: "", description: "", columns: ["[Size]", "[Assets]"], rows: [["[Large]", 12], ["[Small]", 3]],
  numeric: ["[Assets]"], note: "", decided_by: "", decided_at: null, jobs: [], link_context: "", file_url: "", file_name: "",
  file_sha256: "", history: [], translation: TRANSLATION,
};
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function stub(role: string, draft: unknown = DRAFT, onTranslate = vi.fn()) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (url.includes("/auth/me")) return Promise.resolve(json(user(role)));
      if (url.includes("/data-drafts/9/translate")) {
        onTranslate(JSON.parse(String(init?.body)));
        return Promise.resolve(json({ ...DRAFT, translation: { ...TRANSLATION, pending: "queued", translator_online: false } }, 202));
      }
      if (url.includes("/data-drafts/9")) return Promise.resolve(json(draft));
      if (url.includes("/data-drafts")) return Promise.resolve(json([ITEM]));
      return Promise.resolve(json([]));
    }),
  );
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

afterEach(() => vi.unstubAllGlobals());

describe("Перевод черновиков данных", () => {
  it("таблица иностранной статьи — по-русски, одним нажатием — оригинал", async () => {
    stub("reader");
    renderAt("/data-drafts/9");
    expect(await screen.findByRole("heading", { name: "[Выборка компаний]", level: 1 })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: /\[Размер\]/ })).toBeInTheDocument();
    expect(within(table).getByText("[Крупная]")).toBeInTheDocument();
    expect(within(table).getByText("[Small]")).toBeInTheDocument(); // без перевода — как в оригинале
    expect(screen.getByText(/Переведено машинно с языка: английский \(Argos Translate 1\.9\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Оригинал (английский)" }));
    expect(screen.getByRole("heading", { name: "[Sample of firms]", level: 1 })).toBeInTheDocument();
    expect(within(table).getByText("[Large]")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Оригинал (английский)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: /Перевести/ })).not.toBeInTheDocument(); // читатель не ставит перевод
  });

  it("исследователь ставит перевод с другим языком; видно, что переводчик не запущен", async () => {
    const onTranslate = vi.fn();
    stub("researcher", { ...DRAFT, translation: { ...TRANSLATION, pairs: {}, source: "", engine: "" } }, onTranslate);
    renderAt("/data-drafts/9");
    expect(await screen.findByText(/Таблица на языке: английский\. Перевода пока нет/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Язык оригинала"), "немецкий");
    await userEvent.click(screen.getByRole("button", { name: "Перевести на русский" }));
    expect(onTranslate).toHaveBeenCalledWith({ lang: "de" });
    expect(await screen.findByText(/Перевод в очереди/)).toBeInTheDocument();
    expect(screen.getByText(/Переводчик на лабораторном ПК сейчас не запущен/)).toBeInTheDocument();
  });

  it("язык не определился — блок перевода есть, язык выбирают вручную", async () => {
    const onTranslate = vi.fn();
    const unknown = { ...TRANSLATION, lang: "", lang_title: "", supported: false, can_translate: false, pairs: {}, source: "", engine: "" };
    stub("researcher", { ...DRAFT, translation: unknown }, onTranslate);
    renderAt("/data-drafts/9");
    expect(await screen.findByText(/Язык таблицы не определился сам/)).toBeInTheDocument();
    const go = screen.getByRole("button", { name: "Перевести на русский" });
    expect(go).toBeDisabled(); // пока язык не выбран
    await userEvent.selectOptions(screen.getByLabelText("Язык оригинала"), "арабский");
    await userEvent.click(go);
    expect(onTranslate).toHaveBeenCalledWith({ lang: "ar" });
  });

  it("язык, которого переводчик не знает, назван, но сам не переводится", async () => {
    const es = { ...TRANSLATION, lang: "es", lang_title: "испанский", supported: false, can_translate: false, pairs: {}, source: "", engine: "" };
    stub("researcher", { ...DRAFT, translation: es });
    renderAt("/data-drafts/9");
    expect(await screen.findByText(/Таблица на языке: испанский\. Этот язык переводчик пока не знает/)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "определён: испанский (не переводится)" })).toBeInTheDocument();
  });

  it("в списке — название по-русски, оригинал и язык таблицы", async () => {
    stub("reader");
    renderAt("/data-drafts");
    expect(await screen.findByRole("link", { name: "[Выборка компаний]" })).toHaveAttribute("href", "/data-drafts/9");
    expect(screen.getByText("[Sample of firms]")).toBeInTheDocument();
    expect(screen.getByText(/язык таблицы: английский/)).toBeInTheDocument();
  });
});
