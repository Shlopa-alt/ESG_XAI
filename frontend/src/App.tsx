import { Route, Routes } from "react-router-dom";

import { useMe } from "./auth/useAuth";
import { Layout } from "./components/Layout";
import { Login } from "./pages/Login";
import {
  Experiment,
  Experiments,
  Graph,
  Knowledge,
  Methodology,
  Overview,
  Run,
} from "./pages/sections";

export function App() {
  const { data: user, isPending, isError } = useMe();

  if (isPending) return <p className="empty" style={{ padding: 24 }}>Загрузка…</p>;
  if (isError) return <p className="error" role="alert" style={{ padding: 24 }}>Сервер недоступен</p>;
  if (!user) return <Login />;

  return (
    <Routes>
      <Route element={<Layout user={user} />}>
        <Route index element={<Overview />} />
        <Route path="knowledge" element={<Knowledge />} />
        <Route path="knowledge/graph" element={<Graph />} />
        <Route path="experiments" element={<Experiments />} />
        <Route path="experiments/:code" element={<Experiment />} />
        <Route path="run" element={<Run />} />
        <Route path="methodology" element={<Methodology />} />
        <Route path="*" element={<Overview />} />
      </Route>
    </Routes>
  );
}
