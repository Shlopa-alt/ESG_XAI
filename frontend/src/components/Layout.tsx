import { type FormEvent, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import type { User } from "../api/auth";
import { useLogout } from "../auth/useAuth";
import { ORG } from "../org";
import { ROLE_LABEL } from "./Ux";

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
  also?: string[]; // другие адреса того же раздела
}

// Шесть пунктов: человек за один взгляд видит всё, связанное живёт вкладками внутри раздела
const NAV: NavItem[] = [
  { to: "/", label: "Обзор", end: true },
  { to: "/methodology", label: "Методика" },
  { to: "/knowledge", label: "Банк статей" },
  { to: "/hypotheses", label: "Идеи для проверки" },
  { to: "/experiments", label: "Проверки", also: ["/run", "/runs"] },
  { to: "/data", label: "Данные", also: ["/datasets", "/data-drafts"] },
];
const OWNER_NAV: NavItem[] = [
  { to: "/qwen", label: "Задачи Qwen" },
  { to: "/users", label: "Пользователи" },
];

function isActive(item: NavItem, path: string): boolean {
  const under = (to: string) => path === to || path.startsWith(`${to}/`);
  return item.end ? path === item.to : under(item.to) || (item.also ?? []).some(under);
}

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
  const role = ROLE_LABEL[user.role];
  const links = (items: NavItem[]) =>
    items.map((item) => {
      const active = isActive(item, location.pathname);
      return (
        <Link key={item.to} to={item.to} aria-current={active ? "page" : undefined} className={active ? "nav-link active" : "nav-link"}>
          {item.label}
        </Link>
      );
    });

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
            <span className="brand-sub">{ORG}</span>
          </div>
        </div>
        <div className="nav">
          {links(NAV)}
          {user.role === "owner" && (
            <>
              <span className="nav-low">Служебное</span>
              {links(OWNER_NAV)}
            </>
          )}
        </div>
        <div className="sidebar-foot">
          <span>
            {user.full_name || user.login} · {role?.name ?? user.role}
          </span>
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
              Поиск в банке статей
            </label>
            <input
              id="q-main"
              type="search"
              className="search"
              placeholder="Поиск по статьям…"
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
