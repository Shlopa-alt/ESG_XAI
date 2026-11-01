import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";

import { useMe } from "./auth/useAuth";
import { Layout } from "./components/Layout";
import { Article } from "./pages/ArticlePage";
import { DatasetPage } from "./pages/DatasetPage";
import { Experiment, Experiments } from "./pages/ExperimentPages";
import { Hypotheses } from "./pages/HypothesesPage";
import { Import } from "./pages/ImportPage";
import { Login } from "./pages/Login";
import { Methodology } from "./pages/MethodologyPage";
import { Run, RunDetail } from "./pages/RunPage";
import { ChangePassword, Users } from "./pages/UsersPage";
import {
  Knowledge,
  Overview,
} from "./pages/sections";

// Cytoscape (~400 КБ) нужен только графу — грузится, когда граф открыли
const Graph = lazy(() => import("./pages/GraphPage").then((m) => ({ default: m.Graph })));

export function App() {
  const { data: user, isPending, isError } = useMe();

  if (isPending) return <p className="empty" style={{ padding: 24 }}>Загрузка…</p>;
  if (isError) return <p className="error" role="alert" style={{ padding: 24 }}>Сервер недоступен</p>;
  if (!user) return <Login />;
  if (user.must_change_password) return <ChangePassword forced />;

  return (
    <Routes>
      <Route element={<Layout user={user} />}>
        <Route index element={<Overview />} />
        <Route path="knowledge" element={<Knowledge />} />
        <Route path="knowledge/graph" element={<Suspense fallback={<p className="muted">Загрузка графа…</p>}><Graph /></Suspense>} />
        <Route path="knowledge/import" element={<Import />} />
        <Route path="datasets/:code" element={<DatasetPage />} />
        <Route path="knowledge/article/:docId" element={<Article />} />
        <Route path="hypotheses" element={<Hypotheses />} />
        <Route path="experiments" element={<Experiments />} />
        <Route path="experiments/:code" element={<Experiment />} />
        <Route path="run" element={<Run />} />
        <Route path="run/:id" element={<RunDetail />} />
        <Route path="methodology" element={<Methodology />} />
        <Route path="password" element={<ChangePassword />} />
        {user.role === "owner" && <Route path="users" element={<Users />} />}
        <Route path="*" element={<Overview />} />
      </Route>
    </Routes>
  );
}
