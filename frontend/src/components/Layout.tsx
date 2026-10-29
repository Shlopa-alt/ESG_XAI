import { NavLink, Outlet } from "react-router-dom";

import type { User } from "../api/auth";
import { useLogout } from "../auth/useAuth";

const NAV = [
  { to: "/", label: "Обзор", end: true },
  { to: "/knowledge", label: "База знаний", end: false },
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
  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Разделы платформы">
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
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
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

      <div className="main">
        <header className="topbar">
          <label htmlFor="q-main" className="sr-only">
            Поиск по платформе
          </label>
          <input
            id="q-main"
            type="search"
            className="search"
            placeholder="Поиск: методы, датасеты, эксперименты, ID…"
          />
          <button
            type="button"
            className="btn-ghost"
            onClick={() => logout.mutate()}
            disabled={logout.isPending}
          >
            Выйти
          </button>
          <span className="avatar" role="img" aria-label={`Профиль: ${user.full_name || user.login}`}
            style={{ display: "grid", placeItems: "center" }}>
            {initials(user)}
          </span>
        </header>
        <div className="content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
