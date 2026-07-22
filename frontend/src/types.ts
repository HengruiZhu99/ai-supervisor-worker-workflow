export type Project = {
  name: string;
  root: string;
  branch: string;
  project_id: string;
  checkout_id: string;
  worktree_id: string;
};

export type Run = {
  run_id: string;
  objective?: string;
  mode: "solo" | "orchestrated";
  status: string;
  state_revision: number;
};

export type Snapshot = {
  project: Project;
  default_mode: "solo";
  parent_sandbox: "" | "read-only" | "workspace-write";
  runs: Run[];
  event_cursor: number;
};
