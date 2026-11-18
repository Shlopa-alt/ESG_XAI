import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { EN } from "./i18n/en";
import { getLang, startTranslator, translate } from "./i18n";

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("Английская версия: словарь", () => {
  it("подписи, шаблоны с числами и формы «3 статьи»", () => {
    expect(translate("Выйти")).toBe("Sign out");
    expect(translate("  Найти связи ")).toBe("  Find links ");
    expect(translate("НЕЙРОСЕТИ")).toBe("NEURAL NETWORKS");
    expect(translate("держится у 3 из 5")).toBe("holds in 3 of 5");
    expect(translate("≈ 12 мин")).toBe("≈ 12 min");
    expect(translate("5 статей")).toBe("5 articles");
    expect(translate("1 статья")).toBe("1 article");
    expect(translate("2 сети")).toBe("2 networks");
    // данные не переводятся: их нет в словаре
    expect(translate("[стенд] Статья-заглушка")).toBe("[стенд] Статья-заглушка");
    expect(translate("ROA 2021")).toBe("ROA 2021");
    // шаблон почти без постоянного текста не «переводит» данные по одному слову
    expect(translate("[стенд] такой сети в библиотеке нет")).toBe("[стенд] такой сети в библиотеке нет");
    expect(translate("5 строк в 2 сети")).toBe("5 rows in 2 networks");
    // подписи через «·» — по частям
    expect(translate("1 вариант · 2 задания")).toBe("1 variant · 2 tasks");
    expect(translate("EXP-901 · задание методики не указано")).toBe("EXP-901 · no methodology task specified");
    // каталоги сервера: сети и методы библиотеки
    expect(translate("Случайный лес")).toBe("Random forest");
    // строки интерфейса не перепутаны со строками сервера
    expect(translate("2–4 главных числа результата: что получили, с чем сравнивали, насколько надёжно.")).toMatch(/^2–4 key numbers/);
    expect(translate("Параметры Z (размер, отрасль, регион)")).toBe("Parameters Z (size, industry, region)");
  });

  it("в каждом шаблоне — те же места для чисел", () => {
    for (const [ru, en] of Object.entries(EN.templates)) {
      expect((en.match(/\{\d+\}/g) ?? []).sort()).toEqual((ru.match(/\{\d+\}/g) ?? []).sort());
    }
    expect(Object.keys(EN.exact).length).toBeGreaterThan(1000);
  });
});

describe("Английская версия: страница", () => {
  it("переводит текст и подсказки, снова переводит после обновления React; не трогает ввод и translate=no", async () => {
    const root = document.createElement("div");
    root.innerHTML =
      '<p>Выйти</p><input placeholder="Поиск по статьям…"><textarea>Выйти</textarea><span translate="no">Выйти</span>';
    document.body.append(root);
    const obs = startTranslator(root);
    const p = root.querySelector("p");
    expect(p?.textContent).toBe("Sign out");
    expect(root.querySelector("input")?.getAttribute("placeholder")).toBe("Search articles…");
    expect(root.querySelector("textarea")?.value).toBe("Выйти");
    expect(root.querySelector("span")?.textContent).toBe("Выйти");
    if (p?.firstChild) p.firstChild.nodeValue = "Найти связи"; // так React обновляет текст
    await waitFor(() => expect(p?.textContent).toBe("Find links"));
    const added = document.createElement("button");
    added.textContent = "Сохранить";
    root.append(added);
    await waitFor(() => expect(added.textContent).toBe("Save"));
    obs.disconnect();
    root.remove();
    document.documentElement.lang = "ru";
  });

  it("переключатель в шапке запоминает язык", async () => {
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(json(url.includes("/auth/me") ? { id: 1, login: "[логин]", full_name: "", email: "", role: "reader", nda_access: false } : [])),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(getLang()).toBe("ru");
    await userEvent.click(await screen.findByRole("button", { name: "Switch to English" }));
    expect(getLang()).toBe("en");
    expect(reload).toHaveBeenCalled();
  });
});
