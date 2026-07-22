import { useState } from "react";

import { post } from "./api";
import type { Run, Snapshot } from "./types";

export function Runs({
  snapshot,
  refresh,
  report,
}: {
  snapshot: Snapshot;
  refresh: () => Promise<void>;
  report: (message: string) => void;
}) {
  const [limit, setLimit] = useState(40);
  const ordered = [...snapshot.runs].reverse();
  const runs = ordered.slice(0, limit);
  async function action(
    run: Run,
    name: "pause" | "resume" | "stop" | "handoff",
  ) {
    try {
      const result = await post<{ handoff_path?: string }>(
        `/api/v1/runs/${encodeURIComponent(run.run_id)}/${name}`,
        {
          expected_revision: run.state_revision,
          checkout_id: snapshot.project.checkout_id,
        },
      );
      if (result.handoff_path)
        report(`Portable handoff written to ${result.handoff_path}`);
      await refresh();
    } catch (error) {
      report(error instanceof Error ? error.message : "Mutation failed");
      await refresh();
    }
  }
  return (
    <section className="runs" aria-labelledby="runs-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">RUNS</p>
          <h2 id="runs-title">Recent evidence</h2>
        </div>
        <button onClick={refresh} type="button">
          Refresh
        </button>
      </div>
      <div className="run-list">
        {runs.length ? (
          runs.map((run) => (
            <article className="run-card" key={run.run_id}>
              <h3>{run.objective || run.run_id}</h3>
              <p>
                {run.mode} · {run.status} · rev {run.state_revision}
              </p>
              {!["STOPPED", "SUCCEEDED"].includes(run.status) && (
                <div className="run-actions">
                  {run.status === "RUNNING" && (
                    <button type="button" onClick={() => action(run, "pause")}>
                      Pause
                    </button>
                  )}
                  {run.status === "PAUSED" && (
                    <button type="button" onClick={() => action(run, "resume")}>
                      Resume
                    </button>
                  )}
                  {run.status === "PAUSED" && (
                    <button
                      type="button"
                      onClick={() => action(run, "handoff")}
                    >
                      Export handoff
                    </button>
                  )}
                  <button type="button" onClick={() => action(run, "stop")}>
                    Stop
                  </button>
                </div>
              )}
            </article>
          ))
        ) : (
          <p className="empty">
            No runs yet. Your first run starts paused and resumable.
          </p>
        )}
      </div>
      {ordered.length > runs.length && (
        <button
          className="load-more"
          type="button"
          onClick={() => setLimit((value) => value + 40)}
        >
          Show 40 older runs ({ordered.length - runs.length} hidden)
        </button>
      )}
    </section>
  );
}
