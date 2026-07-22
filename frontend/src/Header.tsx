import type { Snapshot } from "./types";

export function Header({
  snapshot,
  theme,
  setTheme,
}: {
  snapshot: Snapshot | null;
  theme: string;
  setTheme: (value: string) => void;
}) {
  const project = snapshot?.project;
  const run = snapshot?.runs.at(-1);
  function cycleTheme() {
    const next =
      theme === "system" ? "light" : theme === "light" ? "dark" : "system";
    document.documentElement.dataset.theme = next;
    setTheme(next);
  }
  return (
    <header
      className="identity-bar"
      id="project-identity"
      aria-label="Project identity"
    >
      <div className="brand">
        <span className="mark">AI</span>
        <span>AIFLOW</span>
      </div>
      <div className="identity-copy">
        <strong>
          {project ? `${project.name} · ${project.branch}` : "Loading project…"}
        </strong>
        <span title={project?.root}>
          {project
            ? `${project.root} · checkout ${project.checkout_id.slice(-8)} · worktree ${project.worktree_id.slice(-8)}`
            : "Resolving checkout identity"}
        </span>
      </div>
      <div className="status-pill" aria-label="Current run">
        <span aria-hidden="true" />
        <span>
          {run ? `${run.mode} · ${run.status}` : "Ready"}
          <small>{run ? `run ${run.run_id.slice(-8)}` : "no active run"}</small>
        </span>
      </div>
      <button
        className="icon-button"
        type="button"
        onClick={cycleTheme}
        aria-label={`Color theme: ${theme}`}
      >
        ◐
      </button>
    </header>
  );
}
