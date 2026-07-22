# AIFLOW v2 live baseline

Captured 2026-07-22 before modernization changes.

## Repository state

- Root: `/Users/hengrui/Desktop/research/gr/ai-supervisor-worker-workflow`
- Original branch: `master`
- Original HEAD: `e9311a932dc2d5bab57c2cfd7ed734b8e1ca5466`
- Upstream: `origin/master`, ahead 0, behind 0
- New local branch: `codex/aiflow-v2-lightweight-multiproject`
- Worktrees: one, at the repository root
- Submodules: none
- Staged changes: none
- Tracked unstaged changes: none
- Pre-existing untracked state preserved: `.DS_Store` and
  `aiflow-v2-lightweight-multiproject-kit/`
- Ignored state reported by `git status --ignored`: none

The observed HEAD matches the upgrade prompt's reference commit. No remote mutation was
performed.

## Seed verification

- Input: `aiflow-v2-lightweight-multiproject-kit/nr-design-tdd-v0.2.0.zip`
- Expected and actual SHA-256:
  `195f2de8b4f164f276695ead06c875328b6b17d469c1df4cfefe5bf64a5cd705`
- Safe-extraction validation covered empty/duplicate names, absolute/traversal/backslash
  paths, escaping targets, symbolic links, devices, FIFOs, sockets, and existing-path
  conflicts.
- Result: 20 members extracted only to a newly-created temporary directory; repository
  files were not overwritten.

## Baseline commands

```text
git status --porcelain=v2 --branch
git remote -v
git worktree list --porcelain
git submodule status --recursive
git status --short --ignored
python3 -m unittest discover -s scripts -p 'test_*.py' -v
codex --version
codex --help
codex exec --help
codex app-server --help
```

Results:

- 85 legacy unit tests passed in 0.886 seconds.
- Local Codex is `codex-cli 0.145.0-alpha.18`.
- Installed CLI exposes explicit approval/sandbox flags, `exec`, and App Server.

## Confirmed current defects

- `scripts/agent_wrapper.py` builds Codex commands with approval `never` and sandbox
  `danger-full-access` regardless of role.
- Multiple generic scripts contain `BBHK` headers; `worker_loop.sh` contains named
  oneAPI/SYCL/project setup and an absolute host path.
- `AIFLOW_PROJECT_ROOT` is trusted by legacy project resolvers.
- worker/test timeouts default to `0` (unbounded).
- reviewer and supervisor consensus default on.
- worker, supervisor, and modulator scripts use permanent `while true` loops.
- progress is stored as self-reported classification with a same-subsystem metadata
  streak, not acceptance closure.
- several scripts and the GUI independently write workflow state.
- integration lacks a tested temporary integrated-state transaction and final target CAS.
- repository skill discovery still scans legacy Cursor/Codex paths.
- primary wrapper/panel/profile defaults are `cursor-agent`.

These are the RED targets; repository evidence supersedes any prompt observation.
