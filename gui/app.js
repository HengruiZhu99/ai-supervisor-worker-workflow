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

async function postJson(path, payload = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.message || `Request failed: ${response.status}`);
  }
  return data;
}

function formValues(form) {
  const data = {};
  for (const element of form.elements) {
    if (!element.name) continue;
    if (element.type === "checkbox") data[element.name] = element.checked;
    else data[element.name] = element.value;
  }
  return data;
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
    box.innerHTML = '<div class="milestone">No milestones parsed.</div>';
    return;
  }
  box.innerHTML = milestones.map((m) => {
    const pct = m.total ? Math.round((m.done / m.total) * 100) : 0;
    return `
      <details class="milestone">
        <summary>
          <span class="milestone-title">${escapeHtml(m.title)}</span>
          <span class="muted">${m.done}/${m.total} fulfilled · ${pct}%</span>
        </summary>
        <div class="mini-track"><div class="mini-bar" style="width:${pct}%"></div></div>
        <div class="criteria-list">
          ${m.items.map((item) => `
            <div class="criterion ${item.done ? "done" : item.active ? "active" : "open"}">
              <span>${item.done ? "✓" : item.active ? "●" : "○"}</span>
              <p>${escapeHtml(item.text)}</p>
            </div>
          `).join("")}
        </div>
      </details>
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

function formatSize(bytes) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function renderTreeNode(node, depth = 0) {
  if (!node) return "";
  if (node.type === "file") {
    return `
      <div class="tree-file" style="padding-left:${Math.min(depth, 12) * 12}px">
        <button type="button" class="file-link" data-path="${escapeHtml(node.path)}" title="Open ${escapeHtml(node.path)}">
          <span>•</span>
          <code>${escapeHtml(node.name || node.path)}</code>
        </button>
        <span class="muted">${escapeHtml(formatSize(node.size))}</span>
      </div>
    `;
  }
  const children = (node.children || []).map((child) => renderTreeNode(child, depth + 1)).join("");
  const open = "";
  const truncated = node.truncated ? '<span class="muted">truncated</span>' : "";
  return `
    <details class="tree-dir" ${open} style="padding-left:${Math.min(depth, 12) * 12}px">
      <summary>
        <span>${depth === 0 ? "Project" : "Folder"}</span>
        <code>${escapeHtml(node.name || node.path || ".")}</code>
        ${truncated}
      </summary>
      <div class="tree-children">${children}</div>
    </details>
  `;
}

function renderTree(tree) {
  const box = $("tree");
  if (!tree || !tree.children) {
    box.innerHTML = '<div class="tree-empty">No project tree available.</div>';
    return;
  }
  box.innerHTML = renderTreeNode(tree, 0);
  box.querySelectorAll(".file-link").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await postJson("/api/open-file", { path: button.dataset.path });
      } catch (error) {
        alert(error.message);
      }
    });
  });
}

function renderHumanReview(supervisor) {
  const section = $("humanReviewSection");
  const gate = $("humanGate");
  const form = $("humanReviewForm");
  if (!supervisor.human_gate_exists) {
    section.classList.add("hidden");
    form.innerHTML = "";
    gate.textContent = "";
    return;
  }

  section.classList.remove("hidden");
  gate.textContent = supervisor.human_gate || "Human review required.";
  const items = supervisor.human_gate_checklist.length
    ? supervisor.human_gate_checklist
    : [
        "Milestone summary is accurate.",
        "Accepted jobs and commits are reviewable.",
        "Tests and validation are acceptable.",
        "Scientific assumptions, risks, and limitations are acceptable.",
        "Recommended next milestone is acceptable.",
      ];
  form.innerHTML = items.map((item, index) => `
    <div class="review-item" data-index="${index}">
      <div class="review-question">${escapeHtml(item)}</div>
      <div class="review-choice">
        <label><input type="radio" name="review-${index}" value="yes" checked /> Yes</label>
        <label><input type="radio" name="review-${index}" value="no" /> No</label>
      </div>
      <textarea name="comment-${index}" placeholder="Comment if no"></textarea>
    </div>
  `).join("") + '<div class="button-row"><button type="submit">Submit Human Review</button></div>';
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
  $("workerActivity").textContent = data.activity?.worker || "Worker status unavailable.";
  $("supervisorActivity").textContent = data.activity?.supervisor || "Supervisor status unavailable.";
  $("ledger").textContent = data.supervisor.ledger || "No ledger found.";
  $("latestLog").textContent = data.supervisor.latest_supervisor_log || "";
  $("supervisorLog").textContent = data.supervisor.latest_supervisor_tail || "No supervisor log found.";
  $("workerLoopLog").textContent = data.controls?.worker?.log_tail || "No worker loop log found.";
  $("supervisorLoopLog").textContent = data.controls?.supervisor?.log_tail || "No supervisor loop log found.";
  $("workerLogTitle").textContent = data.controls?.worker?.log_label || "Cursor Worker Output";
  $("workerLoopLogMeta").textContent = data.controls?.worker?.log_file
    ? `${data.controls.worker.log_file} · last ${data.controls.worker.log_display_lines} lines`
    : "";
  $("supervisorLoopLogMeta").textContent = data.controls?.supervisor?.log_file
    ? `${data.controls.supervisor.log_file} · last ${data.controls.supervisor.log_display_lines} lines`
    : "";

  renderProcesses("workerProcesses", [...data.processes.worker, ...data.processes.cursor]);
  renderProcesses("supervisorProcesses", [...data.processes.supervisor, ...data.processes.codex]);
  renderJobs(data.jobs);
  renderMilestones(data.supervisor.milestones);
  renderWorktrees(data.worktrees);
  renderTree(data.tree);
  renderHumanReview(data.supervisor);
}

async function refresh() {
  const response = await fetch("/api/state", { cache: "no-store" });
  if (!response.ok) throw new Error(`State request failed: ${response.status}`);
  render(await response.json());
}

$("refreshButton").addEventListener("click", () => refresh().catch(console.error));
$("workerForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await postJson("/api/worker/start", formValues(event.currentTarget));
    await refresh();
  } catch (error) {
    alert(error.message);
  }
});
$("supervisorForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await postJson("/api/supervisor/start", formValues(event.currentTarget));
    await refresh();
  } catch (error) {
    alert(error.message);
  }
});
$("stopWorkerButton").addEventListener("click", async () => {
  try {
    await postJson("/api/worker/stop");
    await refresh();
  } catch (error) {
    alert(error.message);
  }
});
$("stopSupervisorButton").addEventListener("click", async () => {
  try {
    await postJson("/api/supervisor/stop");
    await refresh();
  } catch (error) {
    alert(error.message);
  }
});
$("humanReviewForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const items = [...event.currentTarget.querySelectorAll(".review-item")];
  const decisions = items.map((item) => {
    const index = item.dataset.index;
    const label = item.querySelector(".review-question").textContent;
    const choice = item.querySelector(`input[name="review-${index}"]:checked`).value;
    const comment = item.querySelector(`textarea[name="comment-${index}"]`).value;
    return { item: label, passed: choice === "yes", comment };
  });
  try {
    const result = await postJson("/api/human-review", { decisions });
    alert(result.message || "Human review submitted.");
    await refresh();
  } catch (error) {
    alert(error.message);
    await refresh();
  }
});
refresh().catch((error) => {
  $("healthPill").textContent = "Error";
  $("healthPill").className = "health gate";
  $("supervisorLoopLog").textContent = error.stack || String(error);
});
state.timer = setInterval(() => refresh().catch(console.error), 5000);
