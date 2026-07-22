import { useState } from "react";
import type { FormEvent } from "react";

import { post } from "./api";
import type { Snapshot } from "./types";

export function TaskForm({
  snapshot,
  refresh,
}: {
  snapshot: Snapshot;
  refresh: () => Promise<void>;
}) {
  const [mode, setMode] = useState<"solo" | "orchestrated">("solo");
  const [message, setMessage] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const acceptance = String(data.get("acceptance") ?? "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const allowedScope = String(data.get("allowed_scope") ?? "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    setMessage("Creating a project-scoped run…");
    try {
      await post("/api/v1/runs", {
        objective: String(data.get("objective") ?? ""),
        mode,
        acceptance_ids: acceptance,
        allowed_scope: allowedScope,
        checkout_id: snapshot.project.checkout_id,
        parent_sandbox: snapshot.parent_sandbox,
      });
      form.reset();
      setMode("solo");
      setMessage(
        "Run created and paused. Resume it here or from the CLI when ready.",
      );
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Request failed");
    }
  }
  return (
    <form className="task-card" onSubmit={submit}>
      <label htmlFor="objective">Describe the outcome</label>
      <textarea
        id="objective"
        name="objective"
        rows={4}
        required
        maxLength={4000}
        placeholder="Fix the vector norm and add a regression test…"
      />
      <label htmlFor="allowed-scope">
        Allowed paths <span>(comma separated)</span>
      </label>
      <input
        id="allowed-scope"
        name="allowed_scope"
        required
        placeholder="src/vector_norm.cpp, tests/vector_norm_test.cpp"
      />
      <fieldset>
        <legend>Choose a working mode</legend>
        <label className={`mode-card ${mode === "solo" ? "selected" : ""}`}>
          <input
            type="radio"
            name="mode"
            value="solo"
            checked={mode === "solo"}
            onChange={() => setMode("solo")}
          />
          <span>
            <strong>Solo TDD</strong>
            <small>Inspect → RED → GREEN → Refactor → Verify → Review</small>
          </span>
          <span className="recommended">DEFAULT</span>
        </label>
        <label
          className={`mode-card ${mode === "orchestrated" ? "selected" : ""}`}
        >
          <input
            type="radio"
            name="mode"
            value="orchestrated"
            checked={mode === "orchestrated"}
            onChange={() => setMode("orchestrated")}
          />
          <span>
            <strong>Autonomous Program</strong>
            <small>Milestones, bounded agents, review, and integration</small>
          </span>
        </label>
      </fieldset>
      <details open={mode === "orchestrated"}>
        <summary>Advanced contract settings</summary>
        <label htmlFor="acceptance">
          Acceptance IDs <span>(comma separated)</span>
        </label>
        <input id="acceptance" name="acceptance" placeholder="AC-SOLO-001" />
        <p>Models, agent permissions, and budgets remain project-configured.</p>
      </details>
      <div className="contract" aria-live="polite">
        <span>Compact contract</span>
        <strong>
          {mode === "solo"
            ? "Solo · test-first · current checkout only"
            : "Autonomous · bounded agents · reviewed integration"}
        </strong>
      </div>
      <button className="primary" type="submit">
        Create paused run <span aria-hidden="true">→</span>
      </button>
      <p className="form-message" role="status">
        {message}
      </p>
    </form>
  );
}
