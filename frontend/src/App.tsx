import { lazy, Suspense } from "react";
import { Route, Routes, useLocation } from "react-router-dom";

import { useMe } from "./auth/useAuth";
import { Layout } from "./components/Layout";
import { Analysis } from "./pages/AnalysisPage";
import { ApiAccess } from "./pages/ApiAccessPage";
import { MethodLibrary } from "./pages/MethodLibraryPage";
import { Nets } from "./pages/NetsPage";
import { Article } from "./pages/ArticlePage";
import { DataDraftPage, DataDrafts } from "./pages/DataDraftsPage";
import { DatasetPage } from "./pages/DatasetPage";
import { Experiment, Experiments } from "./pages/ExperimentPages";
import { Hypotheses } from "./pages/HypothesesPage";
import { Import } from "./pages/ImportPage";
import { Login } from "./pages/Login";
import { Methodology } from "./pages/MethodologyPage";
import { Qwen } from "./pages/QwenPage";
import { ResetPassword } from "./pages/ResetPassword";
import { Run, RunDetail } from "./pages/RunPage";
import { Studio } from "./pages/StudioPage";
import { ChangePassword, Users } from "./pages/UsersPage";
import {
  Knowledge,
  Overview,
  Data,
} from "./pages/sections";

// Cytoscape (~400 КБ) нужен только графу — грузится, когда граф открыли
const Graph = lazy(() => import("./pages/GraphPage").then((m) => ({ default: m.Graph })));
// Редактор Студии (холст React Flow) — только когда его открыли
const StudioEditor = lazy(() => import("./pages/StudioEditor").then((m) => ({ default: m.StudioEditor })));

export function App() {
  const { data: user, isPending, isError } = useMe();
  const { pathname } = useLocation();

  if (isPending) return <p className="empty" style={{ padding: 24 }}>Загрузка…</p>;
  if (isError) return <p className="error" role="alert" style={{ padding: 24 }}>Сервер недоступен</p>;
  // ссылка из письма «Забыли пароль?» открывается и без входа
  if (pathname === "/reset-password") return <ResetPassword />;
  if (!user) return <Login />;
  if (user.must_change_password) return <ChangePassword forced />;

  return (
    <Routes>
      <Route element={<Layout user={user} />}>
        <Route index element={<Overview />} />
        <Route path="knowledge" element={<Knowledge />} />
        <Route path="knowledge/graph" element={<Suspense fallback={<p className="muted">Загрузка карты…</p>}><Graph /></Suspense>} />
        <Route path="knowledge/import" element={<Import />} />
        <Route path="data" element={<Data />} />
        <Route path="datasets/:code" element={<DatasetPage />} />
        <Route path="data-drafts" element={<DataDrafts />} />
        <Route path="data-drafts/:id" element={<DataDraftPage />} />
        <Route path="knowledge/article/:docId" element={<Article />} />
        <Route path="hypotheses" element={<Hypotheses />} />
        <Route path="experiments" element={<Experiments />} />
        <Route path="experiments/:code" element={<Experiment />} />
        <Route path="run" element={<Run view="new" />} />
        <Route path="runs" element={<Run view="list" />} />
        <Route path="run/:id" element={<RunDetail />} />
        <Route path="nets" element={<Nets />} />
        <Route path="nets/library" element={<MethodLibrary />} />
        <Route path="analysis" element={<Analysis />} />
        <Route path="methodology" element={<Methodology />} />
        <Route path="password" element={<ChangePassword />} />
        <Route path="api-access" element={<ApiAccess />} />
        <Route path="studio" element={<Studio />} />
        <Route path="studio/:code" element={<Suspense fallback={<p className="muted">Загрузка Студии…</p>}><StudioEditor /></Suspense>} />
        {user.role === "owner" && <Route path="users" element={<Users />} />}
        {user.role === "owner" && <Route path="qwen" element={<Qwen />} />}
        <Route path="*" element={<Overview />} />
      </Route>
    </Routes>
  );
}
