const state = {
  data: null,
  timer: null,
  wrapperControlsInitialized: false,
  humanReviewSignature: "",
  supervisorChatSignature: "",
  supervisorChatHistory: [],
  supervisorChatBusy: false,
  modulatorTerminalHistory: [],
  modulatorTerminalBusy: false,
  modulatorTerminalRenderSignature: "",
  modulatorTerminalAtBottom: true,
  modulatorTerminalHistoryLoaded: false,
  architectHistory: [],
  architectBusy: false,
};

const $ = (id) => document.getElementById(id);

function isNearBottom(element, threshold = 24) {
  if (!element) return true;
  return element.scrollHeight - element.scrollTop - element.clientHeight <= threshold;
}

function badgeClass(status) {
  const value = String(status || "unknown").toLowerCase();
  if (value.includes("reviewing")) return "reviewing";
  if (value.includes("ready")) return "ready";
  if (value.includes("running") || value.includes("queued")) return "running";
  if (value.includes("accepted")) return "accepted";
  if (value.includes("superseded") || value.includes("cancelled")) return "terminal";
  if (value.includes("failed") || value.includes("timeout")) return "blocked";
  if (value.includes("rejected")) return "rejected";
  if (value.includes("blocked")) return "blocked";
  return "";
}

function jobDisplayStatus(job, data) {
  const status = job.state || "unknown";
  const supervisorAgentActive = Boolean(data?.processes?.supervisor_agent?.length);
  if (status === "ready_for_review" && supervisorAgentActive) return "reviewing";
  if (status === "ready_for_review") return "ready for review";
  if (status === "review_failed") return "review failed";
  if (status === "review_timeout") return "review timeout";
  return status.replaceAll("_", " ");
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
  return parseJsonResponse(response, path);
}

async function getJson(path) {
  const response = await fetch(path, { method: "GET" });
  return parseJsonResponse(response, path);
}

async function parseJsonResponse(response, path) {
  const text = await response.text();
  const contentType = response.headers.get("content-type") || "";
  let data = {};
  if (contentType.includes("application/json")) {
    try {
      data = text ? JSON.parse(text) : {};
    } catch (error) {
      throw new Error(`Invalid JSON response from ${path}: ${error.message}`);
    }
  } else {
    const snippet = text.trim().replace(/\s+/g, " ").slice(0, 220);
    throw new Error(`Expected JSON from ${path}, got ${response.status}${snippet ? `: ${snippet}` : ""}`);
  }
  if (!response.ok || data.ok === false) {
    throw new Error(data.message || `Request failed: ${response.status}`);
  }
  return data;
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function pollModulatorTerminal(chatId) {
  for (let attempt = 0; attempt < 720; attempt += 1) {
    const result = await getJson(`/api/modulator-terminal-result?id=${encodeURIComponent(chatId)}`);
    if (result.state === "done") return result;
    await delay(2000);
  }
  throw new Error("Modulator terminal is still running after 24 minutes; check the terminal log.");
}

async function loadModulatorTerminalHistory() {
  if (state.modulatorTerminalHistoryLoaded) return;
  try {
    const result = await getJson("/api/modulator-terminal-history");
    state.modulatorTerminalHistory = (result.history || []).map((entry) => ({
      role: entry.role === "user" ? "user" : "modulator",
      content: entry.content || "",
    }));
    state.modulatorTerminalHistoryLoaded = true;
    renderModulatorTerminal({ force: true });
  } catch (error) {
    console.error("modulator terminal history load failed", error);
  }
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

function wrappersForRole(role) {
  const wrappers = state.data?.agent_wrappers?.wrappers || [];
  return wrappers.filter((wrapper) => {
    const roles = wrapper.roles || [];
    return roles.length === 0 || roles.includes(role);
  });
}

function defaultModelFor(wrapper, role) {
  return wrapper?.default_models?.[role] || wrapper?.models?.[0] || "";
}

function roleDefaultWrapper(role) {
  return "cursor-agent";
}

function activeLaunchEnvForRole(role) {
  const loopByRole = {
    worker: "worker",
    supervisor: "supervisor",
    modulator: "modulator",
  };
  return state.data?.controls?.[loopByRole[role]]?.launch_env || {};
}

function envValue(env, ...keys) {
  for (const key of keys) {
    const value = env?.[key];
    if (value !== undefined && value !== null && String(value) !== "") return String(value);
  }
  return "";
}

function activeWrapperForControl(role, select) {
  const env = activeLaunchEnvForRole(role === "reviewer" ? "worker" : role);
  if (select?.name === "reviewer_a_wrapper") {
    return envValue(env, "reviewer_a_agent_wrapper", "REVIEWER_A_AGENT_WRAPPER");
  }
  if (select?.name === "reviewer_b_wrapper") {
    return envValue(env, "reviewer_b_agent_wrapper", "REVIEWER_B_AGENT_WRAPPER");
  }
  if (role === "worker") {
    return envValue(env, "worker_agent_wrapper", "WORKER_AGENT_WRAPPER");
  }
  if (role === "supervisor") {
    return envValue(env, "supervisor_agent_wrapper", "SUPERVISOR_AGENT_WRAPPER");
  }
  if (role === "modulator") {
    return envValue(env, "modulator_agent_wrapper", "MODULATOR_AGENT_WRAPPER");
  }
  return "";
}

function activeModelForControl(role, select) {
  const env = activeLaunchEnvForRole(role === "reviewer" ? "worker" : role);
  if (select?.name === "reviewer_a_wrapper") {
    return envValue(env, "reviewer_a_model", "REVIEWER_A_MODEL", "cursor_reviewer_a_model", "CURSOR_REVIEWER_A_MODEL");
  }
  if (select?.name === "reviewer_b_wrapper") {
    return envValue(env, "reviewer_b_model", "REVIEWER_B_MODEL", "cursor_reviewer_b_model", "CURSOR_REVIEWER_B_MODEL");
  }
  if (role === "worker") {
    return envValue(env, "worker_model", "WORKER_MODEL", "cursor_model", "CURSOR_MODEL");
  }
  if (role === "supervisor") {
    return envValue(env, "supervisor_model", "SUPERVISOR_MODEL", "codex_model", "CODEX_MODEL");
  }
  if (role === "modulator") {
    return envValue(env, "modulator_model", "MODULATOR_MODEL");
  }
  return "";
}

function wrapperOptionLabel(wrapper, role) {
  const recommended = (wrapper.recommended_roles || []).includes(role) ? " recommended" : "";
  const unavailable = wrapper.available === false ? " not in PATH" : "";
  const suffix = [recommended, unavailable].filter(Boolean).join(",");
  return `${wrapper.label || wrapper.id}${suffix ? ` (${suffix.trim()})` : ""}`;
}

function modelChoices(wrapper) {
  const models = wrapper?.models || [];
  return models.length ? models : [""];
}

function populateModelOptions(input, wrapper, role, preferredModel = "") {
  if (!input || !wrapper) return;
  const models = modelChoices(wrapper);
  const priorValue = input.value;
  input.innerHTML = models.map((model) => `
    <option value="${escapeHtml(model)}">${escapeHtml(model || "(wrapper default)")}</option>
  `).join("");

  const desired =
    preferredModel ||
    (priorValue && models.includes(priorValue) ? priorValue : "") ||
    defaultModelFor(wrapper, role) ||
    models[0] ||
    "";
  if (models.includes(desired) || desired === "") {
    input.value = desired;
  } else {
    input.insertAdjacentHTML(
      "beforeend",
      `<option value="${escapeHtml(desired)}">${escapeHtml(desired)} (custom)</option>`,
    );
    input.value = desired;
  }
}

function populateAgentControls() {
  if (!state.data?.agent_wrappers || state.wrapperControlsInitialized) return;
  document.querySelectorAll("[data-agent-wrapper]").forEach((select) => {
    const role = select.dataset.role;
    const modelInput = $(select.dataset.modelInput);
    const wrappers = wrappersForRole(role);
    const activeWrapper = activeWrapperForControl(role, select);
    const activeModel = activeModelForControl(role, select);
    const preferred = activeWrapper || select.value || roleDefaultWrapper(role);
    select.innerHTML = wrappers.map((wrapper) => `
      <option value="${escapeHtml(wrapper.id)}" ${wrapper.id === preferred ? "selected" : ""}>
        ${escapeHtml(wrapperOptionLabel(wrapper, role))}
      </option>
    `).join("");
    if (!select.value && wrappers.length) select.value = wrappers[0].id;
    const selected = wrappers.find((wrapper) => wrapper.id === select.value) || wrappers[0];
    populateModelOptions(modelInput, selected, role, activeModel || modelInput?.dataset.preferredModel || "");
    select.addEventListener("change", () => {
      const next = wrappersForRole(role).find((wrapper) => wrapper.id === select.value);
      populateModelOptions(modelInput, next, role);
    });
  });
  state.wrapperControlsInitialized = true;
}

function refreshModulatorTerminalModel() {
  const input = $("modulatorTerminalModel");
  if (!input || document.activeElement === input || state.modulatorTerminalBusy) return;
  const model = envValue(activeLaunchEnvForRole("modulator"), "modulator_model", "MODULATOR_MODEL");
  if (model && input.value !== model) input.value = model;
}

function collectHumanReviewDraft() {
  const form = $("humanReviewForm");
  if (!form || !form.children.length) return {};
  const items = [...form.querySelectorAll(".review-item")];
  const structuralRequested = $("structuralChangeRequested")?.checked || false;
  const structuralComment = $("structuralChangeComment")?.value || "";
  const approvalComment = $("approvalComment")?.value || "";
  const decisions = items.filter((item) => item.dataset.index !== undefined).map((item) => {
    const index = item.dataset.index;
    const checked = item.querySelector(`input[name="review-${index}"]:checked`);
    const label = item.querySelector(".review-question")?.textContent || "";
    const comment = item.querySelector(`textarea[name="comment-${index}"]`)?.value || "";
    return { item: label, passed: checked?.value !== "no", comment };
  });
  return {
    decisions,
    structural_change: {
      requested: structuralRequested,
      comment: structuralComment,
    },
    approval_comment: approvalComment,
  };
}

function renderSupervisorChat() {
  const log = $("supervisorChatLog");
  const meta = $("supervisorChatMeta");
  if (!log) return;
  if (!state.supervisorChatHistory.length) {
    log.innerHTML = '<div class="chat-empty">Ask a question about the milestone review before submitting it.</div>';
  } else {
    log.innerHTML = state.supervisorChatHistory.map((message) => `
      <div class="chat-message ${message.role === "user" ? "user" : "assistant"}">
        <span class="role">${message.role === "user" ? "You" : "Supervisor"}</span>
        ${escapeHtml(message.content || "")}
      </div>
    `).join("");
    log.scrollTop = log.scrollHeight;
  }
  if (meta) {
    meta.textContent = state.supervisorChatBusy ? "Asking..." : (meta.dataset.last || "Read-only guidance");
  }
}

function renderModulatorTerminal(options = {}) {
  const log = $("modulatorTerminalLog");
  const meta = $("modulatorTerminalMeta");
  if (!log) return;
  const metaText = state.modulatorTerminalBusy
    ? "Working..."
    : (meta?.dataset.last || "Steering channel");
  const signature = JSON.stringify({
    history: state.modulatorTerminalHistory,
    busy: state.modulatorTerminalBusy,
    meta: metaText,
  });
  if (!options.force && signature === state.modulatorTerminalRenderSignature) {
    if (meta) meta.textContent = metaText;
    return;
  }

  const shouldStickToBottom = state.modulatorTerminalAtBottom || isNearBottom(log);
  const previousScrollTop = log.scrollTop;
  const previousScrollHeight = log.scrollHeight;
  if (!state.modulatorTerminalHistory.length) {
    log.innerHTML = '<div class="chat-empty">Ask the modulator about the run, or issue a steering directive. Directives are recorded under .ai/modulator/steering/ and honored by the always-on loop.</div>';
  } else {
    log.innerHTML = state.modulatorTerminalHistory.map((message) => `
      <div class="chat-message ${message.role === "user" ? "user" : "assistant"}">
        <span class="role">${message.role === "user" ? "You" : "Modulator"}</span>
        ${escapeHtml(message.content || "")}
      </div>
    `).join("");
    if (shouldStickToBottom) {
      log.scrollTop = log.scrollHeight;
    } else {
      log.scrollTop = previousScrollTop + (log.scrollHeight - previousScrollHeight);
    }
  }
  if (meta) {
    meta.textContent = metaText;
  }
  state.modulatorTerminalAtBottom = isNearBottom(log);
  state.modulatorTerminalRenderSignature = signature;
}

function renderJobs(jobs, data) {
  const box = $("jobs");
  if (!jobs.length) {
    box.innerHTML = '<div class="job">No jobs found.</div>';
    return;
  }
  box.innerHTML = jobs.map((job) => {
    const status = jobDisplayStatus(job, data);
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
          <span>Reviewer A ${job.reviewer_a_exit === 0 ? "done" : job.reviewer_a_exit !== undefined ? `exit ${escapeHtml(job.reviewer_a_exit)}` : "pending"}</span>
          <span>Reviewer B ${job.reviewer_b_exit === 0 ? "done" : job.reviewer_b_exit !== undefined ? `exit ${escapeHtml(job.reviewer_b_exit)}` : "pending"}</span>
          ${job.reviewers_complete === false ? "<span>Reviewers incomplete</span>" : ""}
          <span>${escapeHtml(job.updated_at || "")}</span>
        </div>
        ${job.base_sha ? `<div class="job-meta"><span>Base ${escapeHtml(String(job.base_sha).slice(0, 12))}</span><span>Workflow ${escapeHtml(job.workflow_commit || "-")}</span></div>` : ""}
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
    state.humanReviewSignature = "";
    state.supervisorChatSignature = "";
    state.supervisorChatHistory = [];
    $("supervisorChatInput").value = "";
    $("supervisorChatMeta").dataset.last = "Read-only guidance";
    renderSupervisorChat();
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
  const signature = JSON.stringify({ gate: supervisor.human_gate || "", items });
  if (signature !== state.supervisorChatSignature) {
    state.supervisorChatSignature = signature;
    state.supervisorChatHistory = [];
    $("supervisorChatInput").value = "";
    $("supervisorChatMeta").dataset.last = "Read-only guidance";
    renderSupervisorChat();
  }
  if (signature === state.humanReviewSignature && form.children.length) {
    return;
  }

  state.humanReviewSignature = signature;
  form.innerHTML = `
    <div class="review-item structural-change">
      <div class="review-question">Major Structural Change</div>
      <label class="check-line">
        <input id="structuralChangeRequested" type="checkbox" name="structural-change-requested" />
        <span>Supersede checklist review and ask the supervisor to revise the plan</span>
      </label>
      <textarea id="structuralChangeComment" name="structural-change-comment" placeholder="Architecture, dependency, roadmap, or milestone change request"></textarea>
    </div>
    <div class="review-item approval-comment">
      <div class="review-question">Optional Approval Comment</div>
      <textarea id="approvalComment" name="approval-comment" placeholder="Recorded only when all checklist items are approved"></textarea>
    </div>
  ` + items.map((item, index) => `
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

function render(data, options = {}) {
  const refreshStaticPanels = options.refreshStaticPanels ?? false;
  state.data = data;
  populateAgentControls();
  $("projectName").textContent = data.project.name;
  $("projectRoot").textContent = data.project.root;
  $("updatedAt").textContent = `Updated ${data.generated_at}`;
  $("gitBranch").textContent = data.git.branch || "-";
  $("gitHead").textContent = data.git.head || "-";
  $("dirtyCount").textContent = data.git.dirty_count || 0;

  const workerActive = Boolean(
    data.controls?.worker?.running || data.processes.worker.length || data.processes.cursor.length
  );
  const supervisorActive = Boolean(
    data.controls?.supervisor?.running || data.processes.supervisor.length || (data.processes.supervisor_agent || []).length
  );
  const modulatorActive = Boolean(
    data.controls?.modulator?.running || (data.processes.modulator || []).length || (data.processes.modulator_agent || []).length
  );
  $("workerState").textContent = workerActive ? "Live" : "Idle";
  $("workerState").className = `state-dot ${workerActive ? "live" : ""}`;
  $("supervisorState").textContent = supervisorActive ? "Live" : "Idle";
  $("supervisorState").className = `state-dot ${supervisorActive ? "live" : ""}`;
  if ($("modulatorState")) {
    $("modulatorState").textContent = modulatorActive ? "Live" : "Idle";
    $("modulatorState").className = `state-dot ${modulatorActive ? "live" : ""}`;
  }
  $("healthPill").textContent = data.supervisor.human_gate_exists ? "Human Review" : "Operational";
  $("healthPill").className = `health ${data.supervisor.human_gate_exists ? "gate" : "live"}`;

  $("jobProgressText").textContent = `${data.job_progress}%`;
  $("jobProgressBar").style.width = `${data.job_progress}%`;
  $("jobCounts").textContent = Object.entries(data.job_counts).map(([key, value]) => `${key}: ${value}`).join(" · ");
  $("currentStatus").textContent = data.activity?.summary || "Workflow status unavailable.";
  $("ledger").textContent = data.supervisor.ledger || "No ledger found.";
  $("latestLog").textContent = data.supervisor.latest_supervisor_log || "";
  $("supervisorLog").textContent = data.supervisor.latest_supervisor_tail || "No supervisor log found.";
  $("workerLoopLog").textContent = data.controls?.worker?.log_tail || "No worker loop log found.";
  $("supervisorLoopLog").textContent = data.controls?.supervisor?.log_tail || "No supervisor loop log found.";
  $("workerLogTitle").textContent = data.controls?.worker?.log_label || "Cursor Worker Output";
  $("workerLoopLogMeta").textContent = data.controls?.worker?.log_file
    ? [
        data.controls.worker.log_file,
        `last ${data.controls.worker.log_display_lines} lines`,
        data.controls.worker.workflow_commit ? `workflow ${data.controls.worker.workflow_commit}` : "",
        data.controls.worker.version_warning || "",
      ].filter(Boolean).join(" · ")
    : "";
  $("supervisorLoopLogMeta").textContent = data.controls?.supervisor?.log_file
    ? [
        data.controls.supervisor.log_file,
        `last ${data.controls.supervisor.log_display_lines} lines`,
        data.controls.supervisor.workflow_commit ? `workflow ${data.controls.supervisor.workflow_commit}` : "",
        data.controls.supervisor.version_warning || "",
      ].filter(Boolean).join(" · ")
    : "";

  renderProcesses("workerProcesses", [...data.processes.worker, ...data.processes.cursor]);
  renderProcesses("supervisorProcesses", [
    ...data.processes.supervisor,
    ...(data.processes.supervisor_agent || []),
  ]);
  if ($("modulatorProcesses")) {
    renderProcesses("modulatorProcesses", [
      ...(data.processes.modulator || []),
      ...(data.processes.modulator_agent || []),
    ]);
  }
  $("reviewerTitle").textContent = data.reviewers?.title || "Reviewer Reports";
  $("reviewerMeta").textContent = data.reviewers?.job_id
    ? [
        data.reviewers.state,
        data.reviewers.reviewer_a_model ? `A: ${data.reviewers.reviewer_a_model}` : "",
        data.reviewers.reviewer_b_model ? `B: ${data.reviewers.reviewer_b_model}` : "",
      ].filter(Boolean).join(" · ")
    : "";
  $("reviewerAReport").textContent = data.reviewers?.reviewer_a || "No reviewer A report found.";
  $("reviewerBReport").textContent = data.reviewers?.reviewer_b || "No reviewer B report found.";
  renderJobs(data.jobs, data);
  renderWorktrees(data.worktrees);
  if (refreshStaticPanels) {
    renderMilestones(data.supervisor.milestones);
    renderTree(data.tree);
  }
  renderHumanReview(data.supervisor);
  refreshModulatorTerminalModel();
  renderModulatorTerminal();
}

async function refresh(options = {}) {
  const response = await fetch("/api/state", { cache: "no-store" });
  if (!response.ok) throw new Error(`State request failed: ${response.status}`);
  render(await response.json(), options);
}

$("refreshButton").addEventListener("click", () => refresh({ refreshStaticPanels: true }).catch(console.error));
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
if ($("modulatorForm")) {
  $("modulatorForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await postJson("/api/modulator/start", formValues(event.currentTarget));
      await refresh();
    } catch (error) {
      alert(error.message);
    }
  });
}
if ($("stopModulatorButton")) {
  $("stopModulatorButton").addEventListener("click", async () => {
    try {
      await postJson("/api/modulator/stop");
      await refresh();
    } catch (error) {
      alert(error.message);
    }
  });
}
$("humanReviewForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const items = [...event.currentTarget.querySelectorAll(".review-item")];
  const structuralRequested = $("structuralChangeRequested")?.checked || false;
  const structuralComment = $("structuralChangeComment")?.value || "";
  const approvalComment = $("approvalComment")?.value || "";
  if (structuralRequested && !structuralComment.trim()) {
    alert("Enter the major structural change request before submitting.");
    return;
  }
  const decisions = items.filter((item) => item.dataset.index !== undefined).map((item) => {
    const index = item.dataset.index;
    const label = item.querySelector(".review-question").textContent;
    const choice = item.querySelector(`input[name="review-${index}"]:checked`).value;
    const comment = item.querySelector(`textarea[name="comment-${index}"]`).value;
    return { item: label, passed: choice === "yes", comment };
  });
  try {
    const result = await postJson("/api/human-review", {
      decisions,
      structural_change: {
        requested: structuralRequested,
        comment: structuralComment,
      },
      approval_comment: approvalComment,
    });
    alert(result.message || "Human review submitted.");
    await refresh({ refreshStaticPanels: true });
  } catch (error) {
    alert(error.message);
  }
});
$("supervisorChatForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("supervisorChatInput");
  const message = input.value.trim();
  if (!message || state.supervisorChatBusy) return;

  state.supervisorChatHistory.push({ role: "user", content: message });
  input.value = "";
  state.supervisorChatBusy = true;
  renderSupervisorChat();

  try {
    const result = await postJson("/api/supervisor-chat", {
      message,
      history: state.supervisorChatHistory.slice(-12),
      draft_review: collectHumanReviewDraft(),
    });
    state.supervisorChatHistory.push({
      role: "assistant",
      content: result.answer || "(No answer returned.)",
    });
    $("supervisorChatMeta").dataset.last = result.model ? `Supervisor ${result.model}` : "Read-only guidance";
  } catch (error) {
    state.supervisorChatHistory.push({
      role: "assistant",
      content: `Supervisor chat failed: ${error.message}`,
    });
    $("supervisorChatMeta").dataset.last = "Read-only guidance";
  } finally {
    state.supervisorChatBusy = false;
    renderSupervisorChat();
  }
});
$("clearSupervisorChatButton").addEventListener("click", () => {
  state.supervisorChatHistory = [];
  $("supervisorChatMeta").dataset.last = "Read-only guidance";
  renderSupervisorChat();
});
$("supervisorChatInput").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) {
    return;
  }
  event.preventDefault();
  $("supervisorChatForm").requestSubmit();
});
$("modulatorTerminalForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("modulatorTerminalInput");
  const message = input.value.trim();
  if (!message || state.modulatorTerminalBusy) return;

  state.modulatorTerminalHistory.push({ role: "user", content: message });
  input.value = "";
  state.modulatorTerminalBusy = true;
  state.modulatorTerminalAtBottom = true;
  $("modulatorTerminalMeta").dataset.last = "Steering channel";
  renderModulatorTerminal({ force: true });

  try {
    const started = await postJson("/api/modulator-terminal", {
      message,
      model: $("modulatorTerminalModel")?.value || "",
    });
    $("modulatorTerminalMeta").dataset.last = started.chat_id
      ? `working · ${started.chat_id.slice(0, 8)}`
      : "working";
    renderModulatorTerminal({ force: true });
    const result = started.state === "running" && started.chat_id
      ? await pollModulatorTerminal(started.chat_id)
      : started;
    state.modulatorTerminalHistory.push({
      role: "modulator",
      content: result.answer || result.message || "(No answer returned.)",
    });
    $("modulatorTerminalMeta").dataset.last = [
      result.model ? result.model : "",
      result.log_file ? result.log_file : "",
    ].filter(Boolean).join(" · ") || "Steering channel";
    await refresh({ refreshStaticPanels: true });
  } catch (error) {
    state.modulatorTerminalHistory.push({
      role: "modulator",
      content: `Modulator terminal failed: ${error.message}`,
    });
    $("modulatorTerminalMeta").dataset.last = "Steering channel";
  } finally {
    state.modulatorTerminalBusy = false;
    renderModulatorTerminal({ force: true });
  }
});
$("clearModulatorTerminalButton").addEventListener("click", () => {
  state.modulatorTerminalHistory = [];
  state.modulatorTerminalAtBottom = true;
  $("modulatorTerminalMeta").dataset.last = "Steering channel";
  renderModulatorTerminal({ force: true });
});
$("modulatorTerminalInput").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) {
    return;
  }
  event.preventDefault();
  $("modulatorTerminalForm").requestSubmit();
});
const modulatorTerminalLog = $("modulatorTerminalLog");
if (modulatorTerminalLog) {
  modulatorTerminalLog.addEventListener("scroll", () => {
    state.modulatorTerminalAtBottom = isNearBottom(modulatorTerminalLog);
  });
}
refresh({ refreshStaticPanels: true }).catch((error) => {
  $("healthPill").textContent = "Error";
  $("healthPill").className = "health gate";
  $("supervisorLoopLog").textContent = error.stack || String(error);
});
loadModulatorTerminalHistory().catch(console.error);

// ----- Architect intake -----
function renderArchitectLog() {
  const log = $("architectLog");
  if (!log) return;
  const entries = state.architectHistory.map((entry) => `
    <div class="chat-message ${entry.role === "user" ? "user" : "assistant"}">
      <span class="role">${entry.role === "user" ? "You" : "Architect"}</span>
      ${escapeHtml(entry.content || "")}
    </div>
  `);
  if (state.architectBusy) {
    entries.push('<div class="chat-message assistant"><span class="role">Architect</span>thinking...</div>');
  }
  log.innerHTML = entries.join("") || '<div class="chat-empty">Start by describing the software you want to build.</div>';
  log.scrollTop = log.scrollHeight;
}

async function pollArchitect(chatId) {
  for (let attempt = 0; attempt < 600; attempt += 1) {
    const result = await getJson(`/api/architect/result?id=${encodeURIComponent(chatId)}`);
    if (result.state === "done") return result;
    await delay(2000);
  }
  throw new Error("Architect is still running after 20 minutes.");
}

async function refreshArchitectState() {
  const box = $("architectStatus");
  if (!box) return;
  try {
    const result = await getJson("/api/architect/state");
    const lines = [result.summary || ""];
    if (result.status) lines.push(`\nstatus: ${result.status}`);
    box.textContent = lines.join("\n");
    const meta = $("architectMeta");
    if (meta) meta.textContent = result.complete ? "Spec complete - ready to gate/hand off" : "Scope a new project, then hand off to the build";
  } catch (error) {
    box.textContent = `Could not load spec state: ${error.message}`;
  }
}

if ($("architectForm")) {
  $("architectForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("architectInput");
    const message = input.value.trim();
    if (!message || state.architectBusy) return;
    state.architectHistory.push({ role: "user", content: message });
    input.value = "";
    state.architectBusy = true;
    renderArchitectLog();
    try {
      const started = await postJson("/api/architect/message", {
        message,
        model: $("architectModel")?.value || "",
      });
      const result = started.state === "running" && started.chat_id ? await pollArchitect(started.chat_id) : started;
      state.architectHistory.push({ role: "architect", content: result.answer || result.message || "(spec updated)" });
    } catch (error) {
      state.architectHistory.push({ role: "architect", content: `Architect failed: ${error.message}` });
    } finally {
      state.architectBusy = false;
      renderArchitectLog();
      await refreshArchitectState();
    }
  });

  $("architectInput").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) return;
    event.preventDefault();
    $("architectForm").requestSubmit();
  });

  $("architectGateButton").addEventListener("click", async () => {
    if (state.architectBusy) return;
    state.architectBusy = true;
    state.architectHistory.push({ role: "architect", content: "Running completeness gate (deterministic + consensus panel)..." });
    renderArchitectLog();
    try {
      const started = await postJson("/api/architect/gate", {});
      const result = started.state === "running" && started.chat_id ? await pollArchitect(started.chat_id) : started;
      const missing = (result.missing || []).map((m) => `\n- ${m}`).join("");
      state.architectHistory.push({ role: "architect", content: `${result.answer || "gate done"}${missing}` });
    } catch (error) {
      state.architectHistory.push({ role: "architect", content: `Gate failed: ${error.message}` });
    } finally {
      state.architectBusy = false;
      renderArchitectLog();
      await refreshArchitectState();
    }
  });

  $("architectHandoffButton").addEventListener("click", async () => {
    if (state.architectBusy) return;
    state.architectBusy = true;
    renderArchitectLog();
    try {
      const result = await postJson("/api/architect/handoff", {
        start: $("architectStartLoops")?.checked || false,
      });
      const written = (result.written || []).map((p) => `\n- ${p}`).join("");
      state.architectHistory.push({ role: "architect", content: `Compiled bootstrap artifacts:${written || " (none)"}` });
      await refresh({ refreshStaticPanels: true });
    } catch (error) {
      state.architectHistory.push({ role: "architect", content: `Handoff failed: ${error.message}` });
    } finally {
      state.architectBusy = false;
      renderArchitectLog();
      await refreshArchitectState();
    }
  });

  renderArchitectLog();
  refreshArchitectState().catch(console.error);
}
state.timer = setInterval(() => refresh({ refreshStaticPanels: false }).catch(console.error), 5000);
