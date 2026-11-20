import "@xyflow/react/dist/style.css";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  type Connection,
  Controls,
  type Edge,
  type EdgeChange,
  Handle,
  type Node,
  type NodeChange,
  type NodeProps,
  Position,
  ReactFlow,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  type ComponentSchema,
  copyScenario,
  fileUrl,
  getComponents,
  getRun,
  getScenario,
  approvePython,
  type Graph,
  type NodeSummary,
  type NodeView,
  runScenario,
  listScenarios,
  saveScenario,
  type Scenario,
  stopRun,
  StudioError,
  type StudioRun,
} from "../api/studio";
import { useMe } from "../auth/useAuth";
import { StudioChart, StudioCube, StudioQuality, StudioReport } from "../components/StudioCharts";
import { type ParamContext, StudioParams } from "../components/StudioParams";

interface StepData extends Record<string, unknown> {
  comp: ComponentSchema;
  title: string;
  params: Record<string, unknown>;
  summary?: NodeSummary;
  busy: boolean;
  problem?: string;
}

type StepNode = Node<StepData, "step">;

const ACTIVE = new Set(["queued", "running"]);
const fmt = (v: unknown) => {
  if (v == null) return "";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toLocaleString("ru-RU", { maximumFractionDigits: 4 });
  return String(v);
};

/** Узел на холсте: входы слева (по портам компонента), выход справа, итог последнего расчёта. */
function Step({ data, selected }: NodeProps<StepNode>) {
  const { comp, summary, busy, problem } = data;
  const n = comp.inputs.length;
  return (
    <div className={`studio-node${selected ? " selected" : ""}${summary && !summary.ok ? " failed" : ""}`}>
      {comp.inputs.map((inp, i) => (
        <Handle key={inp.name} type="target" position={Position.Left} id={inp.name} style={{ top: `${((i + 1) / (n + 1)) * 100}%` }} title={inp.label} />
      ))}
      <div className="studio-node-kind">{comp.title}</div>
      <div className="studio-node-title">{data.title || comp.title}</div>
      <div className="studio-node-state">
        {busy
          ? "считается…"
          : problem
            ? problem
            : summary
              ? summary.ok
                ? `${summary.rows ?? 0} строк · ${summary.cols ?? 0} столбцов`
                : summary.error
              : "ещё не считали"}
      </div>
      <Handle type="source" position={Position.Right} id="out" />
    </div>
  );
}

const NODE_TYPES = { step: Step };

/** Узлы без своих мест (сценарий собран через API) — по слоям слева направо: слой — длина пути от начала. */
function layout(graph: Graph): Map<string, { x: number; y: number }> {
  const spots = new Set(graph.nodes.map((n) => `${n.x ?? 0}:${n.y ?? 0}`));
  if (graph.nodes.length < 2 || spots.size === graph.nodes.length) return new Map();
  const ups = new Map<string, string[]>();
  graph.edges.forEach((e) => ups.set(e.to, [...(ups.get(e.to) ?? []), e.from]));
  const depth = new Map<string, number>();
  const level = (id: string, seen: Set<string>): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    if (seen.has(id)) return 0;
    seen.add(id);
    const d = Math.max(-1, ...(ups.get(id) ?? []).map((u) => level(u, seen))) + 1;
    depth.set(id, d);
    return d;
  };
  const rows = new Map<number, number>();
  const out = new Map<string, { x: number; y: number }>();
  graph.nodes.forEach((n) => {
    const d = level(n.id, new Set());
    const row = rows.get(d) ?? 0;
    rows.set(d, row + 1);
    out.set(n.id, { x: d * 240, y: row * 120 });
  });
  return out;
}

function toFlow(graph: Graph, comps: Map<string, ComponentSchema>): { nodes: StepNode[]; edges: Edge[] } {
  const auto = layout(graph);
  const nodes = graph.nodes
    .filter((n) => comps.has(n.type))
    .map<StepNode>((n) => ({
      id: n.id,
      type: "step",
      position: auto.get(n.id) ?? { x: n.x ?? 0, y: n.y ?? 0 },
      data: { comp: comps.get(n.type) as ComponentSchema, title: n.title ?? "", params: n.params ?? {}, busy: false },
    }));
  const edges = graph.edges.map<Edge>((e) => ({ id: `${e.from}->${e.to}:${e.port}`, source: e.from, target: e.to, targetHandle: e.port }));
  return { nodes, edges };
}

type Variable = { name: string; value: string };

function toGraph(nodes: StepNode[], edges: Edge[], variables: Variable[]): Graph {
  return {
    format: 1,
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.data.comp.type,
      ...(n.data.title ? { title: n.data.title } : {}),
      params: n.data.params,
      x: Math.round(n.position.x),
      y: Math.round(n.position.y),
    })),
    edges: edges.map((e) => ({ from: e.source, to: e.target, port: e.targetHandle ?? "in" })),
    variables: variables.filter((v) => v.name.trim() !== ""),
  };
}

const newId = () => `n${Math.random().toString(36).slice(2, 8)}`;

/** «Таблица» и «Статистика» результата узла. */
function Preview({ view }: { view: NodeView }) {
  const [tab, setTab] = useState<"report" | "table" | "stats" | "quality" | "chart" | "cube">(view.report ? "report" : "table");
  const t = view.table;
  const st = view.statistics;
  return (
    <div className="studio-preview">
      <div className="tabs" role="tablist" aria-label="Вид результата">
        {view.report && (
          <button type="button" role="tab" aria-selected={tab === "report"} className={tab === "report" ? "chip active" : "chip"} onClick={() => setTab("report")}>
            Отчёт
          </button>
        )}
        <button type="button" role="tab" aria-selected={tab === "table"} className={tab === "table" ? "chip active" : "chip"} onClick={() => setTab("table")}>
          Таблица
        </button>
        <button type="button" role="tab" aria-selected={tab === "stats"} className={tab === "stats" ? "chip active" : "chip"} onClick={() => setTab("stats")}>
          Статистика
        </button>
        <button type="button" role="tab" aria-selected={tab === "quality"} className={tab === "quality" ? "chip active" : "chip"} onClick={() => setTab("quality")}>
          Качество данных{view.quality?.issues ? ` (${view.quality.issues})` : ""}
        </button>
        <button type="button" role="tab" aria-selected={tab === "chart"} className={tab === "chart" ? "chip active" : "chip"} onClick={() => setTab("chart")}>
          Диаграмма
        </button>
        {view.cube && (
          <button type="button" role="tab" aria-selected={tab === "cube"} className={tab === "cube" ? "chip active" : "chip"} onClick={() => setTab("cube")}>
            Куб
          </button>
        )}
      </div>
      {tab === "cube" && view.cube && <StudioCube cube={view.cube} />}
      {tab === "report" && view.report && <StudioReport report={view.report} />}
      {tab === "quality" && <StudioQuality view={view} />}
      {tab === "chart" && <StudioChart view={view} />}
      {tab === "table" && t && (
        <div className="table-wrap">
          <p className="muted small">
            Строк: {t.total}
            {t.total > t.rows.length ? `, показаны первые ${t.rows.length}` : ""}
          </p>
          <table className="table studio-table">
            <thead>
              <tr>
                {t.columns.map((c) => (
                  <th key={c.name} scope="col" title={c.kind} className={c.kind === "number" || c.kind === "integer" ? "num" : ""}>
                    {c.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {t.rows.map((r, i) => (
                <tr key={i}>
                  {r.map((v, j) => (
                        <td key={j} className={typeof v === "number" ? "num" : ""}>
                      {fmt(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === "stats" && st && (
        <div className="table-wrap">
          <table className="table studio-table">
            <thead>
              <tr>
                <th scope="col">Столбец</th>
                <th scope="col">Тип</th>
                <th scope="col" className="num">Заполнено</th>
                <th scope="col" className="num">Пусто</th>
                <th scope="col" className="num">Различных</th>
                <th scope="col" className="num">Мин.</th>
                <th scope="col" className="num">Медиана</th>
                <th scope="col" className="num">Среднее</th>
                <th scope="col" className="num">Макс.</th>
                <th scope="col">Частые значения</th>
              </tr>
            </thead>
            <tbody>
              {st.columns.map((c) => (
                <tr key={c.name}>
                  <th scope="row">{c.name}</th>
                  <td>{c.kind}</td>
                  <td className="num">{c.count}</td>
                  <td className="num">{c.missing}</td>
                  <td className="num">{c.unique}</td>
                  <td className="num">{fmt(c.min)}</td>
                  <td className="num">{fmt(c.median)}</td>
                  <td className="num">{fmt(c.mean)}</td>
                  <td className="num">{fmt(c.max)}</td>
                  <td>{(c.top ?? []).map((x) => `${x.value} (${x.count})`).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function StudioEditor() {
  const { code = "" } = useParams();
  const qc = useQueryClient();
  const comps = useQuery({ queryKey: ["studio", "components"], queryFn: getComponents, staleTime: Infinity });
  const scenario = useQuery({ queryKey: ["studio", code], queryFn: () => getScenario(code) });
  const catalog = useMemo(() => new Map((comps.data?.components ?? []).map((c) => [c.type, c])), [comps.data]);
  const [nodes, setNodes] = useState<StepNode[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [version, setVersion] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [views, setViews] = useState<Record<string, NodeView>>({});
  const [summaries, setSummaries] = useState<Record<string, NodeSummary>>({});
  const [runId, setRunId] = useState<number | null>(null);
  const [problem, setProblem] = useState<{ node: string; message: string } | null>(null);
  const [variables, setVariables] = useState<Variable[]>([]);
  const scenarios = useQuery({ queryKey: ["studio", "list"], queryFn: listScenarios });
  const me = useMe();
  const editable = scenario.data?.editable ?? false;

  // сценарий и каталог пришли — на холст (только при первой загрузке или после чужого сохранения)
  useEffect(() => {
    const s = scenario.data;
    if (!s || catalog.size === 0 || s.version === version) return;
    const flow = toFlow(s.graph, catalog);
    setNodes(flow.nodes);
    setEdges(flow.edges);
    setVariables(s.graph.variables ?? []);
    setVersion(s.version);
    setDirty(false);
    const last = s.runs[0];
    if (last?.summary?.nodes) setSummaries(last.summary.nodes);
    // последний расчёт: его результаты узлов сразу видны (идёт — следим за ним)
    if (last) setRunId((id) => id ?? last.id);
  }, [scenario.data, catalog, version]);

  const run = useQuery({
    queryKey: ["studio", "run", runId],
    queryFn: () => getRun(runId as number),
    enabled: runId !== null,
    refetchInterval: (q) => (q.state.data && !ACTIVE.has(q.state.data.status) ? false : 1500),
  });
  const current: StudioRun | undefined = run.data;
  const running = current !== undefined && ACTIVE.has(current.status);

  useEffect(() => {
    if (!current || ACTIVE.has(current.status)) return;
    setViews((v) => ({ ...v, ...(current.views ?? {}) }));
    setSummaries((s) => ({ ...s, ...(current.summary.nodes ?? {}) }));
    if (current.summary.error) setProblem(current.summary.error);
    if (!current.until) void qc.invalidateQueries({ queryKey: ["studio", code] });
  }, [current, code, qc]);

  const busyNodes = useMemo(() => {
    if (!running || !current) return new Set<string>();
    if (!current.until) return new Set(nodes.map((n) => n.id));
    const ups = new Map<string, string[]>();
    edges.forEach((e) => ups.set(e.target, [...(ups.get(e.target) ?? []), e.source]));
    const need = new Set<string>();
    const stack = [current.until];
    while (stack.length) {
      const id = stack.pop() as string;
      if (!need.has(id)) {
        need.add(id);
        stack.push(...(ups.get(id) ?? []));
      }
    }
    return need;
  }, [running, current, nodes, edges]);

  const shown = useMemo(
    () =>
      nodes.map((n) => ({
        ...n,
        data: { ...n.data, summary: summaries[n.id], busy: busyNodes.has(n.id), problem: problem?.node === n.id ? problem.message : undefined },
      })),
    [nodes, summaries, busyNodes, problem],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange<StepNode>[]) => {
      setNodes((ns) => applyNodeChanges(changes, ns));
      if (changes.some((c) => c.type === "position" || c.type === "remove")) setDirty(true);
      const sel = changes.find((c) => c.type === "select" && c.selected);
      if (sel && sel.type === "select") setSelected(sel.id);
      if (changes.some((c) => c.type === "remove")) {
        const gone = new Set(changes.filter((c) => c.type === "remove").map((c) => (c.type === "remove" ? c.id : "")));
        setEdges((es) => es.filter((e) => !gone.has(e.source) && !gone.has(e.target)));
      }
    },
    [],
  );
  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    setEdges((es) => applyEdgeChanges(changes, es));
    if (changes.some((c) => c.type === "remove")) setDirty(true);
  }, []);
  const connect = useCallback((from: string, to: string, port: string) => {
    setEdges((es) => [
      ...es.filter((e) => !(e.target === to && (e.targetHandle ?? "in") === port)),
      ...(from ? [{ id: `${from}->${to}:${port}`, source: from, target: to, targetHandle: port }] : []),
    ]);
    setDirty(true);
  }, []);
  const onConnect = useCallback(
    (c: Connection) => {
      if (c.source && c.target && c.source !== c.target) connect(c.source, c.target, c.targetHandle ?? "in");
    },
    [connect],
  );

  const addNode = (comp: ComponentSchema) => {
    const id = newId();
    const params = Object.fromEntries(comp.params.filter((p) => p.default !== undefined).map((p) => [p.name, p.default]));
    const sel = nodes.find((n) => n.id === selected);
    const position = sel ? { x: sel.position.x + 240, y: sel.position.y } : { x: 40 + (nodes.length % 4) * 240, y: 40 + Math.floor(nodes.length / 4) * 140 };
    setNodes((ns) => [...ns, { id, type: "step", position, data: { comp, title: "", params, busy: false } }]);
    // новый узел сразу подключаем к выбранному — так цепочка собирается кликами
    const firstInput = comp.inputs[0];
    if (sel && firstInput) connect(sel.id, id, firstInput.name);
    setSelected(id);
    setDirty(true);
  };

  const updateNode = (id: string, patch: Partial<StepData>) => {
    setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)));
    setDirty(true);
  };
  const removeNode = (id: string) => {
    setNodes((ns) => ns.filter((n) => n.id !== id));
    setEdges((es) => es.filter((e) => e.source !== id && e.target !== id));
    setSelected(null);
    setDirty(true);
  };

  const save = useMutation({
    mutationFn: async () => {
      const s = await saveScenario(code, version, toGraph(nodes, edges, variables));
      qc.setQueryData<Scenario>(["studio", code], (old) => (old ? { ...old, ...s, runs: old.runs } : old));
      setVersion(s.version);
      setDirty(false);
      return s;
    },
    onError: (e) => {
      if (e instanceof StudioError && e.node) setProblem({ node: e.node, message: e.message });
    },
  });
  const start = useMutation({
    mutationFn: async (until: string) => {
      setProblem(null);
      if (dirty) await save.mutateAsync();
      return runScenario(code, until);
    },
    onSuccess: (r) => setRunId(r.id),
    onError: (e) => {
      if (e instanceof StudioError && e.node) setProblem({ node: e.node, message: e.message });
    },
  });
  const approve = useMutation({
    mutationFn: (node: string) => approvePython(code, node),
    onSuccess: (r) => qc.setQueryData<Scenario>(["studio", code], (old) => (old ? { ...old, python: r.python } : old)),
  });
  const stop = useMutation({ mutationFn: () => stopRun(runId as number), onSuccess: () => void run.refetch() });
  const copy = useMutation({ mutationFn: () => copyScenario(code) });

  const columnsOf = useCallback(
    (nodeId: string) => (port: string) => {
      const e = edges.find((x) => x.target === nodeId && (x.targetHandle ?? "in") === port);
      const v = e ? views[e.source] : undefined;
      return v?.table?.columns.map((c) => c.name) ?? [];
    },
    [edges, views],
  );

  if (scenario.isError) return <p className="error" role="alert">{scenario.error.message}</p>;
  if (!scenario.data || !comps.data) return <p className="empty">Загрузка…</p>;
  const s = scenario.data;
  const sel = nodes.find((n) => n.id === selected);
  const selSummary = sel ? summaries[sel.id] : undefined;
  const selView = sel ? views[sel.id] : undefined;
  const groups = [...new Set(comps.data.components.map((c) => c.group))];
  const error = save.error ?? start.error ?? stop.error ?? copy.error ?? approve.error;
  const context: ParamContext = {
    nodes: nodes.filter((n) => n.id !== selected).map((n) => ({ id: n.id, label: `${n.data.title || n.data.comp.title} (${n.id})` })),
    scenarios: (Array.isArray(scenarios.data) ? scenarios.data : []).filter((x) => x.code !== code).map((x) => ({ code: x.code, title: x.title })),
  };
  const pyState = sel && sel.data.comp.type === "code.python" ? s.python?.[sel.id] : undefined;
  const setVar = (i: number, patch: Partial<Variable>) => {
    setVariables((vs) => vs.map((v, j) => (j === i ? { ...v, ...patch } : v)));
    setDirty(true);
  };
  const lastFull = s.runs[0];

  return (
    <>
      <section className="page-head">
        <span className="eyebrow">
          <Link to="/studio">СТУДИЯ</Link> · {s.code} · ВЕРСИЯ {version}
          {dirty ? " · ЕСТЬ НЕСОХРАНЁННЫЕ ИЗМЕНЕНИЯ" : ""}
        </span>
        <h1 className="page-title">{s.title}</h1>
        <div className="actions">
          {editable && (
            <button type="button" className="btn-ghost" onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
              Сохранить
            </button>
          )}
          {editable && (
            <button type="button" className="btn-primary" onClick={() => start.mutate("")} disabled={running || start.isPending || nodes.length === 0}>
              Посчитать сценарий
            </button>
          )}
          {running && (
            <button type="button" className="btn-ghost" onClick={() => stop.mutate()} disabled={stop.isPending}>
              Остановить
            </button>
          )}
          {!editable && (
            <button type="button" className="btn-ghost" onClick={() => copy.mutate()} disabled={copy.isPending}>
              Сделать копию
            </button>
          )}
          {copy.data && <Link to={`/studio/${copy.data.code}`}>Открыть копию {copy.data.code}</Link>}
        </div>
      </section>
      {error && (
        <p className="error" role="alert">
          {error.message}
        </p>
      )}
      {current && (
        <p className={current.status === "failed" ? "error" : "muted"} role="status">
          {current.until ? `Предпросмотр узла` : `Расчёт сценария`} № {current.id}:{" "}
          {{ queued: "в очереди", running: "считается", done: "готово", failed: "с ошибкой", stopped: "остановлен" }[current.status]}
          {current.message ? ` — ${current.message}` : ""}
        </p>
      )}
      <div className="studio">
        <aside className="studio-palette card" aria-label="Компоненты">
          <h2 className="h2">Компоненты</h2>
          {!editable && <p className="muted small">Сценарий другого автора — только просмотр.</p>}
          {groups.map((g) => (
            <div key={g}>
              <h3 className="studio-group">{g}</h3>
              {comps.data.components
                .filter((c) => c.group === g)
                .map((c) => (
                  <button key={c.type} type="button" className="studio-add" title={c.description} disabled={!editable} onClick={() => addNode(c)}>
                    {c.title}
                  </button>
                ))}
            </div>
          ))}
        </aside>
        <div className="studio-canvas card">
          <ReactFlow<StepNode>
            nodes={shown}
            edges={edges}
            nodeTypes={NODE_TYPES}
            onNodesChange={editable ? onNodesChange : undefined}
            onEdgesChange={editable ? onEdgesChange : undefined}
            onConnect={editable ? onConnect : undefined}
            onNodeClick={(_, n) => setSelected(n.id)}
            onPaneClick={() => setSelected(null)}
            nodesDraggable={editable}
            nodesConnectable={editable}
            deleteKeyCode={editable ? ["Delete", "Backspace"] : null}
            fitView
            // мельче — надписи узлов не прочитать: лучше прокрутить холст
            fitViewOptions={{ padding: 0.15, minZoom: 0.6, maxZoom: 1.2 }}
            minZoom={0.2}
            proOptions={{ hideAttribution: true }}
          >
            <Background />
            <Controls showInteractive={false} />
          </ReactFlow>
          {nodes.length === 0 && <p className="studio-hint">Добавьте узел слева — например, «Набор данных».</p>}
        </div>
        <aside className="studio-side card" aria-label="Настройки узла">
          {!sel ? (
            <>
              <h2 className="h2">Узел не выбран</h2>
              <p className="muted">
                Выберите узел на схеме — здесь появятся его настройки и результат. Новый узел подключается к выбранному;
                связи можно тянуть мышью от правого края узла к левому.
              </p>
              <fieldset className="field rows" disabled={!editable}>
                <legend>Переменные сценария</legend>
                <p className="muted small">В формулах — $имя, например: год = $год. Подмодель и цикл могут их переопределить.</p>
                {variables.map((v, i) => (
                  <div className="param-row" key={i}>
                    <label className="field">
                      Имя
                      <input value={v.name} onChange={(e) => setVar(i, { name: e.target.value })} />
                    </label>
                    <label className="field">
                      Значение
                      <input value={v.value} onChange={(e) => setVar(i, { value: e.target.value })} />
                    </label>
                    <button
                      type="button"
                      className="btn-ghost"
                      onClick={() => {
                        setVariables((vs) => vs.filter((_, j) => j !== i));
                        setDirty(true);
                      }}
                    >
                      Убрать
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={() => {
                    setVariables((vs) => [...vs, { name: "", value: "" }]);
                    setDirty(true);
                  }}
                >
                  Добавить переменную
                </button>
              </fieldset>
              {lastFull && lastFull.files.length > 0 && (
                <>
                  <h3 className="studio-group">Файлы последнего расчёта № {lastFull.id}</h3>
                  <ul>
                    {lastFull.files.map((f) => (
                      <li key={f}>
                        <a href={fileUrl(lastFull.id, f)} download>
                          {f}
                        </a>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          ) : (
            <>
              <h2 className="h2">{sel.data.comp.title}</h2>
              <p className="muted small">{sel.data.comp.description}</p>
              <label className="field">
                Подпись узла
                <input value={sel.data.title} disabled={!editable} onChange={(e) => updateNode(sel.id, { title: e.target.value })} placeholder={sel.data.comp.title} />
              </label>
              {sel.data.comp.inputs.map((inp) => {
                const e = edges.find((x) => x.target === sel.id && (x.targetHandle ?? "in") === inp.name);
                return (
                  <label key={inp.name} className="field">
                    Вход: {inp.label}
                    {inp.optional ? " (необязательно)" : ""}
                    <select value={e?.source ?? ""} disabled={!editable} onChange={(ev) => connect(ev.target.value, sel.id, inp.name)}>
                      <option value="">— не подключён —</option>
                      {nodes
                        .filter((n) => n.id !== sel.id)
                        .map((n) => (
                          <option key={n.id} value={n.id}>
                            {n.data.title || n.data.comp.title} ({n.id})
                          </option>
                        ))}
                    </select>
                  </label>
                );
              })}
              <StudioParams
                comp={sel.data.comp}
                values={sel.data.params}
                columns={columnsOf(sel.id)}
                disabled={!editable}
                context={context}
                onChange={(params) => updateNode(sel.id, { params })}
              />
              {sel.data.comp.type === "code.python" && (
                <div className="py-state" role="status">
                  {dirty ? (
                    <p className="muted small">Сохраните сценарий — код проверится и покажется, одобрен ли он.</p>
                  ) : pyState && pyState.problems.length > 0 ? (
                    <p className="error">Код не проходит проверку: {pyState.problems.join("; ")}</p>
                  ) : pyState?.approved ? (
                    <p className="muted">Код проверен и одобрен владельцем платформы.</p>
                  ) : (
                    <p className="muted">Код проверен, но не одобрен: считать его может только владелец платформы, остальным — после одобрения.</p>
                  )}
                  {me.data?.role === "owner" && !dirty && pyState && !pyState.approved && pyState.problems.length === 0 && (
                    <button type="button" className="btn-ghost" onClick={() => approve.mutate(sel.id)} disabled={approve.isPending}>
                      Одобрить код (я его прочитал)
                    </button>
                  )}
                </div>
              )}
              <div className="actions">
                {editable && (
                  <button type="button" className="btn-primary" onClick={() => start.mutate(sel.id)} disabled={running || start.isPending}>
                    Посчитать узел
                  </button>
                )}
                {editable && (
                  <button type="button" className="btn-ghost" onClick={() => removeNode(sel.id)}>
                    Удалить узел
                  </button>
                )}
              </div>
              {selSummary && !selSummary.ok && (
                <p className="error" role="alert">
                  {selSummary.error}
                </p>
              )}
              {current?.hidden && <p className="muted">Результат по набору под NDA — только для допущенных.</p>}
            </>
          )}
        </aside>
      </div>
      {sel && selView && (
        <section className="card">
          <h2 className="h2">Результат: {sel.data.title || sel.data.comp.title}</h2>
          <Preview key={sel.id} view={selView} />
        </section>
      )}
    </>
  );
}
