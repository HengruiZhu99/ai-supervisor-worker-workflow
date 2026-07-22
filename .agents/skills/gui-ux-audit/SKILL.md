---
name: gui-ux-audit
description: Audit a workflow web interface for task-centered usability, accessibility, responsive behavior, security-visible identity, reconnect semantics, and console/runtime errors. Use for GUI acceptance, regression review, or progressive-disclosure checks.
---

# GUI UX Audit

Exercise the built application at desktop and narrow viewport sizes. Verify:

- Solo TDD is the default and advanced orchestration is progressively disclosed;
- project, checkout, worktree, and run identity remain visible near mutations;
- keyboard navigation, focus, labels, contrast, reduced motion, landmarks, and live
  status are usable;
- stale revisions, wrong origin/token, reconnect/replay gaps, bounded logs, and two
  simultaneous projects fail safely;
- loading, empty, running, success, failure, blocked, and disconnected states are clear;
- browser console and network logs contain no unexplained errors.

Capture screenshots only where they prove layout/state, and retain exact steps plus
machine-checkable results. Report actionable findings by severity and file/surface.
