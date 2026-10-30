import { Route, Routes } from "react-router-dom";

import { useMe } from "./auth/useAuth";
import { Layout } from "./components/Layout";
import { Article } from "./pages/ArticlePage";
import { Experiment, Experiments } from "./pages/ExperimentPages";
import { Graph } from "./pages/GraphPage";
import { Hypotheses } from "./pages/HypothesesPage";
import { Login } from "./pages/Login";
import { Methodology } from "./pages/MethodologyPage";
import { Run } from "./pages/RunPage";
import { ChangePassword, Users } from "./pages/UsersPage";
import {
  Knowledge,
  Overview,
} from "./pages/sections";

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
        <Route path="knowledge/graph" element={<Graph />} />
        <Route path="knowledge/article/:docId" element={<Article />} />
        <Route path="hypotheses" element={<Hypotheses />} />
        <Route path="experiments" element={<Experiments />} />
        <Route path="experiments/:code" element={<Experiment />} />
        <Route path="run" element={<Run />} />
        <Route path="methodology" element={<Methodology />} />
        <Route path="password" element={<ChangePassword />} />
        {user.role === "owner" && <Route path="users" element={<Users />} />}
        <Route path="*" element={<Overview />} />
      </Route>
    </Routes>
  );
}
