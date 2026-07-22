import React, { FormEvent, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

type Project = {
  name: string;
  root: string;
  branch: string;
  project_id: string;
  checkout_id: string;
  worktree_id: string;
};
type Run = {
  run_id: string;
  objective?: string;
  mode: "solo" | "orchestrated";
  status: string;
  state_revision: number;
};
type Snapshot = { project: Project; default_mode: "solo"; runs: Run[]; event_cursor: number };

const token = document.querySelector<HTMLMetaElement>('meta[name="aiflow-token"]')?.content ?? "";

async function readSnapshot(): Promise<Snapshot> {
  const response = await fetch("/api/v1/snapshot", { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`Snapshot failed (${response.status})`);
  return response.json() as Promise<Snapshot>;
}

async function post<T>(path: string, payload: object): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-AIFLOW-Token": token },
    body: JSON.stringify(payload),
  });
  const result = (await response.json()) as T & { error?: string };
  if (!response.ok) throw new Error(result.error ?? `Request failed (${response.status})`);
  return result;
}

function Header({ snapshot, theme, setTheme }: {
  snapshot: Snapshot | null;
  theme: string;
  setTheme: (value: string) => void;
}) {
  const project = snapshot?.project;
  const state = snapshot?.runs.at(-1)?.status ?? "Ready";
  function cycleTheme() {
    const next = theme === "system" ? "light" : theme === "light" ? "dark" : "system";
    document.documentElement.dataset.theme = next;
    setTheme(next);
  }
  return <header className="identity-bar" id="project-identity" aria-label="Project identity">
    <div className="brand"><span className="mark">AI</span><span>AIFLOW</span></div>
    <div className="identity-copy">
      <strong>{project ? `${project.name} · ${project.branch}` : "Loading project…"}</strong>
      <span>{project ? `${project.root} · checkout ${project.checkout_id.slice(-8)}` : "Resolving checkout identity"}</span>
    </div>
    <div className="status-pill"><span aria-hidden="true"/><span>{state}</span></div>
    <button className="icon-button" type="button" onClick={cycleTheme} aria-label={`Color theme: ${theme}`}>◐</button>
  </header>;
}

function TaskForm({ snapshot, refresh }: { snapshot: Snapshot; refresh: () => Promise<void> }) {
  const [mode, setMode] = useState<"solo" | "orchestrated">("solo");
  const [message, setMessage] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const acceptance = String(data.get("acceptance") ?? "").split(",").map((x) => x.trim()).filter(Boolean);
    setMessage("Creating a project-scoped run…");
    try {
      await post("/api/v1/runs", {
        objective: String(data.get("objective") ?? ""), mode, acceptance_ids: acceptance,
        checkout_id: snapshot.project.checkout_id,
      });
      form.reset();
      setMode("solo");
      setMessage("Run created and paused. Resume it from the CLI when ready.");
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Request failed"); }
  }
  return <form className="task-card" onSubmit={submit}>
    <label htmlFor="objective">Describe the outcome</label>
    <textarea id="objective" name="objective" rows={4} required maxLength={4000} placeholder="Fix the vector norm and add a regression test…"/>
    <fieldset>
      <legend>Choose a working mode</legend>
      <label className={`mode-card ${mode === "solo" ? "selected" : ""}`}>
        <input type="radio" name="mode" value="solo" checked={mode === "solo"} onChange={() => setMode("solo")}/>
        <span><strong>Solo TDD</strong><small>Inspect → RED → GREEN → Refactor → Verify → Review</small></span>
        <span className="recommended">DEFAULT</span>
      </label>
      <label className={`mode-card ${mode === "orchestrated" ? "selected" : ""}`}>
        <input type="radio" name="mode" value="orchestrated" checked={mode === "orchestrated"} onChange={() => setMode("orchestrated")}/>
        <span><strong>Autonomous Program</strong><small>Milestones, bounded agents, review, and integration</small></span>
      </label>
    </fieldset>
    <details open={mode === "orchestrated"}>
      <summary>Advanced contract settings</summary>
      <label htmlFor="acceptance">Acceptance IDs <span>(comma separated)</span></label>
      <input id="acceptance" name="acceptance" placeholder="AC-SOLO-001"/>
      <p>Models, agent permissions, and budgets remain project-configured.</p>
    </details>
    <div className="contract" aria-live="polite"><span>Compact contract</span><strong>{mode === "solo" ? "Solo · test-first · current checkout only" : "Autonomous · bounded agents · reviewed integration"}</strong></div>
    <button className="primary" type="submit">Create paused run <span aria-hidden="true">→</span></button>
    <p className="form-message" role="status">{message}</p>
  </form>;
}

function Runs({ snapshot, refresh, report }: {
  snapshot: Snapshot;
  refresh: () => Promise<void>;
  report: (message: string) => void;
}) {
  const runs = [...snapshot.runs].reverse().slice(0, 40);
  async function action(run: Run, name: "pause" | "resume" | "stop" | "handoff") {
    try {
      const result = await post<{ handoff_path?: string }>(`/api/v1/runs/${encodeURIComponent(run.run_id)}/${name}`, {
        expected_revision: run.state_revision,
        checkout_id: snapshot.project.checkout_id,
      });
      if (result.handoff_path) report(`Portable handoff written to ${result.handoff_path}`);
      await refresh();
    } catch (error) { report(error instanceof Error ? error.message : "Mutation failed"); await refresh(); }
  }
  return <section className="runs" aria-labelledby="runs-title">
    <div className="section-heading"><div><p className="eyebrow">RUNS</p><h2 id="runs-title">Recent evidence</h2></div><button onClick={refresh} type="button">Refresh</button></div>
    <div className="run-list">{runs.length ? runs.map((run) => <article className="run-card" key={run.run_id}>
      <h3>{run.objective || run.run_id}</h3><p>{run.mode} · {run.status} · rev {run.state_revision}</p>
      {!(["STOPPED", "SUCCEEDED"].includes(run.status)) && <div className="run-actions">
        {run.status === "RUNNING" && <button type="button" onClick={() => action(run, "pause")}>Pause</button>}
        {run.status === "PAUSED" && <button type="button" onClick={() => action(run, "resume")}>Resume</button>}
        {run.status === "PAUSED" && <button type="button" onClick={() => action(run, "handoff")}>Export handoff</button>}
        <button type="button" onClick={() => action(run, "stop")}>Stop</button>
      </div>}
    </article>) : <p className="empty">No runs yet. Your first run starts paused and resumable.</p>}</div>
  </section>;
}

function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [theme, setTheme] = useState("system");
  const refresh = useCallback(async () => { try { setSnapshot(await readSnapshot()); } catch (reason) { setError(reason instanceof Error ? reason.message : "Snapshot failed"); } }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    let reconnects = 0;
    let timer = 0;
    let source: EventSource | null = null;
    function connect() {
      if (!("EventSource" in window) || reconnects >= 5) { timer = window.setTimeout(() => void refresh(), Math.min(30000, 2000 * (reconnects + 1))); return; }
      source = new EventSource("/api/v1/events");
      source.addEventListener("run", () => { reconnects = 0; void refresh(); });
      source.addEventListener("reset", (event) => { reconnects = 0; setSnapshot(JSON.parse((event as MessageEvent).data) as Snapshot); });
      source.onerror = () => { source?.close(); reconnects += 1; timer = window.setTimeout(connect, Math.min(30000, 1000 * 2 ** reconnects)); };
    }
    connect();
    return () => { source?.close(); window.clearTimeout(timer); };
  }, [refresh]);
  return <><a className="skip-link" href="#workspace">Skip to task workspace</a><Header snapshot={snapshot} theme={theme} setTheme={setTheme}/><main id="workspace">
    <section className="hero" aria-labelledby="task-title"><p className="eyebrow">NEW TASK</p><h1 id="task-title">What should we move forward?</h1><p>Start with a tight, testable change. AIFLOW keeps the evidence and project boundary visible.</p></section>
    {snapshot ? <><TaskForm snapshot={snapshot} refresh={refresh}/><Runs snapshot={snapshot} refresh={refresh} report={setError}/></> : <p role="status">Loading project contract…</p>}
    {error && <p className="form-message" role="alert">{error}</p>}
  </main><footer>Local project server · no arbitrary file or shell access</footer></>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App/></React.StrictMode>);
