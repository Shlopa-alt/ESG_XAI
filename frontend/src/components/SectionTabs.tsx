import { NavLink } from "react-router-dom";

import { useMe } from "../auth/useAuth";
import { canRun } from "./Ux";

interface TabLink {
  to: string;
  label: string;
  end?: boolean;
}

/** Вкладки раздела: один пункт меню, внутри — связанные страницы. Каждая вкладка — свой адрес. */
function SectionTabs({ label, items }: { label: string; items: TabLink[] }) {
  return (
    <nav className="tabs" aria-label={label}>
      {items.map((i) => (
        <NavLink key={i.to} to={i.to} end={i.end} className={({ isActive }) => (isActive ? "tab active" : "tab")}>
          {i.label}
        </NavLink>
      ))}
    </nav>
  );
}

export function BankTabs() {
  return (
    <SectionTabs
      label="Разделы банка статей"
      items={[
        { to: "/knowledge", label: "Статьи", end: true },
        { to: "/knowledge/graph", label: "Карта связей" },
        { to: "/knowledge/import", label: "Добавить статью" },
      ]}
    />
  );
}

export function DataTabs() {
  return (
    <SectionTabs
      label="Разделы данных"
      items={[
        { to: "/data", label: "Наборы данных", end: true },
        { to: "/data-drafts", label: "Данные из статей" },
      ]}
    />
  );
}

export function ChecksTabs() {
  const launch = canRun(useMe().data?.role);
  return (
    <SectionTabs
      label="Разделы проверок"
      items={[
        { to: "/experiments", label: "Все проверки", end: true },
        ...(launch ? [{ to: "/run", label: "Новая проверка", end: true }] : []),
        { to: "/runs", label: "Расчёты", end: true },
      ]}
    />
  );
}
