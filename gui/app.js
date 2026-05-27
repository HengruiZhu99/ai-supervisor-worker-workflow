const state = {
  data: null,
  timer: null,
};

const $ = (id) => document.getElementById(id);

function badgeClass(status) {
  const value = String(status || "unknown").toLowerCase();
  if (value.includes("ready")) return "ready";
  if (value.includes("running") || value.includes("queued")) return "running";
  if (value.includes("accepted")) return "accepted";
  if (value.includes("rejected")) return "rejected";
  if (value.includes("blocked")) return "blocked";
  return "";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderProcesses(id, processes) {
  const box = $(id);
  if (!processes.length) {
    box.innerHTML = '<div class="process">No active process detected.</div>';
    return;
  }
  box.innerHTML = processes.map((proc) => `
    <div class="process">
      <strong>PID ${proc.pid}</strong> <span class="muted">state ${escapeHtml(proc.state)}</span>
      <code title="${escapeHtml(proc.cmd)}">${escapeHtml(proc.cmd)}</code>
    </div>
  `).join("");
}

function renderJobs(jobs) {
  const box = $("jobs");
  if (!jobs.length) {
    box.innerHTML = '<div class="job">No jobs found.</div>';
    return;
  }
  box.innerHTML = jobs.map((job) => {
    const status = job.state || "unknown";
    const title = job.title || job.id || "Untitled job";
    return `
      <article class="job">
        <div class="job-head">
          <h3>${escapeHtml(job.id)} · ${escapeHtml(title)}</h3>
          <span class="badge ${badgeClass(status)}">${escapeHtml(status)}</span>
        </div>
        <div class="job-meta">
          <span>Attempt ${escapeHtml(job.attempt ?? 0)}</span>
          <span>Branch ${escapeHtml(job.branch || "-")}</span>
          <span>Tests ${job.tests_passed === true ? "passed" : job.tests_passed === false ? "failed" : "unknown"}</span>
          <span>${escapeHtml(job.updated_at || "")}</span>
        </div>
        <code>${escapeHtml(job._path || "")}</code>
      </article>
    `;
  }).join("");
}

function renderMilestones(milestones) {
  const box = $("milestones");
  if (!milestones.length) {
    box.innerHTML = '<div class="milestone">No roadmap milestones parsed.</div>';
    return;
  }
  box.innerHTML = milestones.map((m) => {
    const pct = m.total ? Math.round((m.done / m.total) * 100) : 0;
    return `
      <div class="milestone">
        <div class="milestone-title">${escapeHtml(m.title)}</div>
        <div class="progress-label"><span>${m.done}/${m.total} criteria</span><strong>${pct}%</strong></div>
        <div class="mini-track"><div class="mini-bar" style="width:${pct}%"></div></div>
      </div>
    `;
  }).join("");
}

function renderWorktrees(worktrees) {
  const box = $("worktrees");
  if (!worktrees.length) {
    box.innerHTML = '<div class="worktree">No Git worktrees detected.</div>';
    return;
  }
  box.innerHTML = worktrees.map((wt) => `
    <div class="worktree">
      <div class="worktree-title">${escapeHtml(wt.branch || wt.HEAD || "worktree")}</div>
      <code>${escapeHtml(wt.display_path || wt.worktree || "")}</code>
      <div class="job-meta">
        <span>${escapeHtml(wt.HEAD || "")}</span>
        <span>${wt.dirty_count || 0} dirty files</span>
      </div>
    </div>
  `).join("");
}

function renderTree(tree) {
  const box = $("tree");
  box.innerHTML = tree.map((item) => {
    const icon = item.type === "dir" ? "▸" : item.type === "file" ? "•" : "…";
    const size = item.size ? `${Math.round(item.size / 1024)} KB` : "";
    return `
      <div class="tree-row" style="padding-left:${Math.min(item.depth || 0, 8) * 12}px">
        <span>${icon}</span>
        <code>${escapeHtml(item.path)}</code>
        <span class="muted">${size}</span>
      </div>
    `;
  }).join("");
}

function render(data) {
  state.data = data;
  $("projectName").textContent = data.project.name;
  $("projectRoot").textContent = data.project.root;
  $("updatedAt").textContent = `Updated ${data.generated_at}`;
  $("gitBranch").textContent = data.git.branch || "-";
  $("gitHead").textContent = data.git.head || "-";
  $("dirtyCount").textContent = data.git.dirty_count || 0;

  const workerActive = data.processes.worker.length || data.processes.cursor.length;
  const supervisorActive = data.processes.supervisor.length || data.processes.codex.length;
  $("workerState").textContent = workerActive ? "Live" : "Idle";
  $("workerState").className = `state-dot ${workerActive ? "live" : ""}`;
  $("supervisorState").textContent = supervisorActive ? "Live" : "Idle";
  $("supervisorState").className = `state-dot ${supervisorActive ? "live" : ""}`;
  $("healthPill").textContent = data.supervisor.human_gate_exists ? "Human Review" : "Operational";
  $("healthPill").className = `health ${data.supervisor.human_gate_exists ? "gate" : "live"}`;

  $("jobProgressText").textContent = `${data.job_progress}%`;
  $("jobProgressBar").style.width = `${data.job_progress}%`;
  $("jobCounts").textContent = Object.entries(data.job_counts).map(([key, value]) => `${key}: ${value}`).join(" · ");
  $("ledger").textContent = data.supervisor.ledger || "No ledger found.";
  $("latestLog").textContent = data.supervisor.latest_supervisor_log || "";
  $("supervisorLog").textContent = data.supervisor.latest_supervisor_tail || "No supervisor log found.";

  renderProcesses("workerProcesses", [...data.processes.worker, ...data.processes.cursor]);
  renderProcesses("supervisorProcesses", [...data.processes.supervisor, ...data.processes.codex]);
  renderJobs(data.jobs);
  renderMilestones(data.supervisor.milestones);
  renderWorktrees(data.worktrees);
  renderTree(data.tree);
}

async function refresh() {
  const response = await fetch("/api/state", { cache: "no-store" });
  if (!response.ok) throw new Error(`State request failed: ${response.status}`);
  render(await response.json());
}

$("refreshButton").addEventListener("click", () => refresh().catch(console.error));
refresh().catch((error) => {
  $("healthPill").textContent = "Error";
  $("healthPill").className = "health gate";
  $("supervisorLog").textContent = error.stack || String(error);
});
state.timer = setInterval(() => refresh().catch(console.error), 5000);

