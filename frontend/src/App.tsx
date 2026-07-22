import { useCallback, useEffect, useRef, useState } from "react";

import { readSnapshot } from "./api";
import { Header } from "./Header";
import { Runs } from "./Runs";
import { TaskForm } from "./TaskForm";
import type { Snapshot } from "./types";

export function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [theme, setTheme] = useState("system");
  const workspace = useRef<HTMLElement>(null);
  const refresh = useCallback(async () => {
    try {
      setSnapshot(await readSnapshot());
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Snapshot failed");
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    let reconnects = 0;
    let timer = 0;
    let source: EventSource | null = null;
    let lastEventId = "";
    let stopped = false;
    function scheduleFallbackPoll() {
      if (stopped) return;
      timer = window.setTimeout(
        async () => {
          await refresh();
          scheduleFallbackPoll();
        },
        Math.min(30000, 2000 * (reconnects + 1)),
      );
    }
    function connect() {
      if (!("EventSource" in window) || reconnects >= 5) {
        scheduleFallbackPoll();
        return;
      }
      const replay = lastEventId
        ? `?last_event_id=${encodeURIComponent(lastEventId)}`
        : "";
      source = new EventSource(`/api/v1/events${replay}`);
      source.addEventListener("run", (event) => {
        lastEventId = (event as MessageEvent).lastEventId || lastEventId;
        reconnects = 0;
        void refresh();
      });
      source.addEventListener("reset", (event) => {
        lastEventId = (event as MessageEvent).lastEventId || "";
        reconnects = 0;
        setSnapshot(JSON.parse((event as MessageEvent).data) as Snapshot);
        setError("");
      });
      source.onerror = () => {
        source?.close();
        reconnects += 1;
        timer = window.setTimeout(
          connect,
          Math.min(30000, 1000 * 2 ** reconnects),
        );
      };
    }
    connect();
    return () => {
      stopped = true;
      source?.close();
      window.clearTimeout(timer);
    };
  }, [refresh]);
  return (
    <>
      <a
        className="skip-link"
        href="#workspace"
        onClick={() =>
          window.requestAnimationFrame(() => workspace.current?.focus())
        }
      >
        Skip to task workspace
      </a>
      <Header snapshot={snapshot} theme={theme} setTheme={setTheme} />
      <main
        id="workspace"
        ref={workspace}
        tabIndex={-1}
        data-event-cursor={snapshot?.event_cursor ?? 0}
      >
        <section className="hero" aria-labelledby="task-title">
          <p className="eyebrow">NEW TASK</p>
          <h1 id="task-title">What should we move forward?</h1>
          <p>
            Start with a tight, testable change. AIFLOW keeps the evidence and
            project boundary visible.
          </p>
        </section>
        {snapshot ? (
          <>
            <TaskForm snapshot={snapshot} refresh={refresh} />
            <Runs snapshot={snapshot} refresh={refresh} report={setError} />
          </>
        ) : (
          <p role="status">Loading project contract…</p>
        )}
        {error && (
          <p className="form-message" role="alert">
            {error}
          </p>
        )}
      </main>
      <footer>Local project server · no arbitrary file or shell access</footer>
    </>
  );
}
