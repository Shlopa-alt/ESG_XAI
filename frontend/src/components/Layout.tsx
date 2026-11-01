import { type FormEvent, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import type { User } from "../api/auth";
import { useLogout } from "../auth/useAuth";

const NAV = [
  { to: "/", label: "Обзор", end: true },
  { to: "/knowledge", label: "База знаний", end: false },
  { to: "/knowledge/graph", label: "Граф связей", end: false },
  { to: "/knowledge/import", label: "Импорт статей", end: false },
  { to: "/qwen", label: "Задачи Qwen", end: false },
  { to: "/hypotheses", label: "Гипотезы", end: false },
  { to: "/experiments", label: "Эксперименты", end: false },
  { to: "/run", label: "Запуск экспериментов", end: false },
  { to: "/methodology", label: "Методология", end: false },
];

function initials(user: User): string {
  const source = user.full_name.trim() || user.login;
  return source
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w.charAt(0).toUpperCase())
    .join("");
}

export function Layout({ user }: { user: User }) {
  const logout = useLogout();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [query, setQuery] = useState("");
  const nav = user.role === "owner" ? [...NAV, { to: "/users", label: "Пользователи", end: false }] : NAV;

  // На узком экране меню закрывается после перехода и по Escape
  useEffect(() => setMenuOpen(false), [location.pathname]);
  useEffect(() => {
    if (!menuOpen) return undefined;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  const search = (e: FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (q) navigate(`/knowledge?q=${encodeURIComponent(q)}`);
  };

  return (
    <div className={menuOpen ? "shell menu-open" : "shell"}>
      <nav className="sidebar" id="main-menu" aria-label="Разделы платформы">
        <div className="brand">
          <svg
            width="32"
            height="32"
            viewBox="0 0 32 32"
            fill="none"
            stroke="#7FC8A0"
            strokeWidth="2"
            aria-hidden="true"
          >
            <circle cx="8" cy="22" r="4" />
            <circle cx="24" cy="10" r="4" />
            <circle cx="24" cy="24" r="3" />
            <path d="M11 19l9-7M12 22h9" />
          </svg>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span className="brand-name">ESG Open Research</span>
            <span className="brand-sub">НИЦ ИИ · Университет «Дубна»</span>
          </div>
        </div>
        <div className="nav">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end || item.to === "/knowledge"}
              className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
            >
              {item.label}
            </NavLink>
          ))}
        </div>
        <div className="sidebar-foot">
          <span>Внутренняя сеть</span>
          <small>Доступ только из сети центра, вход по учётной записи</small>
        </div>
      </nav>
      <button type="button" className="scrim" aria-label="Закрыть меню" onClick={() => setMenuOpen(false)} />

      <div className="main">
        <header className="topbar">
          <button
            type="button"
            className="btn-ghost menu-toggle"
            aria-controls="main-menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
          >
            Меню
          </button>
          <form role="search" onSubmit={search}>
            <label htmlFor="q-main" className="sr-only">
              Поиск по базе знаний
            </label>
            <input
              id="q-main"
              type="search"
              className="search"
              placeholder="Поиск по статьям базы знаний…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </form>
          <div className="topbar-actions">
            <NavLink to="/password" className="btn-ghost">
              Пароль
            </NavLink>
            <button type="button" className="btn-ghost" onClick={() => logout.mutate()} disabled={logout.isPending}>
              Выйти
            </button>
            <span className="avatar" role="img" aria-label={`Профиль: ${user.full_name || user.login}`}>
              {initials(user)}
            </span>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
