# AIFLOW v2 source verification

Verified on 2026-07-22 against the current Codex manual, official OpenAI pages, and the
installed local CLI (`codex-cli 0.145.0-alpha.18`). Version-sensitive behavior is kept
behind command/config builders and validation rather than assumed from model memory.

## Codex subagents and project custom agents

- Source: [Subagents](https://developers.openai.com/codex/subagents/)
- Verified facts: project agents are standalone TOML files under `.codex/agents/`;
  `name`, `description`, and `developer_instructions` are required; child sessions
  inherit the parent turn's live sandbox and approval overrides; current concurrency is
  configured with `agents.max_concurrent_threads_per_session`.
- Design impact: AIFLOW validates parent permissions before orchestration, uses narrow
  project agents with `[agents] enabled = false`, includes an explicit no-spawn contract,
  audits returned results for recursive delegation, and does not claim perfect child
  isolation from configuration alone. No undocumented recursion-depth option is used.

## Codex configuration

- Source: [Configuration reference](https://developers.openai.com/codex/config-reference/)
- Verified facts: durable settings use TOML; approval policy and sandbox mode are
  separate controls; `danger-full-access` is an explicit unrestricted sandbox; unknown
  keys can be rejected with strict configuration validation.
- Design impact: role commands always spell out both approval and sandbox choices,
  read-only roles use `read-only`, writers use `workspace-write`, and orchestrated mode
  refuses an unrestricted parent preflight.

## Skills

- Source: [Build skills](https://developers.openai.com/codex/skills/)
- Verified facts: repository skills are discovered from `.agents/skills` between the
  current directory and repository root; user skills live in `$HOME/.agents/skills`;
  duplicate names are not merged; `SKILL.md` requires `name` and `description`.
- Design impact: `.agents/skills` is canonical, profiles vendor selected skills, the
  project lock stores hashes, and `aiflow skills doctor` reports cross-scope name
  collisions rather than choosing silently.

## Non-interactive permissions and sandboxing

- Sources: [Codex security](https://developers.openai.com/codex/security/) and the
  installed `codex exec --help`.
- Verified facts: `codex exec` supports explicit `--ask-for-approval` and `--sandbox`;
  approval choices are `untrusted`, `on-request`, and `never`; sandbox choices are
  `read-only`, `workspace-write`, and `danger-full-access`; bypassing approval and the
  sandbox is separately marked dangerous.
- Design impact: the compatibility wrapper removes the hidden full-access/bypass
  default, command construction is role-aware and testable, and permission-invalid
  runs fail closed.

## App Server and SDK

- Sources: [Codex App Server](https://developers.openai.com/codex/app-server/) and
  [Codex SDK](https://developers.openai.com/codex/sdk/).
- Verified facts: App Server is a JSON-RPC surface with thread/turn identities and
  streamed events; the SDK is the intended programmatic automation surface; sandbox
  presets include read-only, workspace-write, and full access; local transports and
  generated version-specific schemas are available.
- Design impact: AIFLOW keeps its deterministic state engine authoritative, records
  Codex thread/cwd/checkout/run identity, and treats App Server integration as a bounded
  adapter. The local GUI uses the AIFLOW API and does not expose arbitrary App Server,
  file, or shell endpoints.

## Goal mode

- Source: [Prompting and Goal mode](https://developers.openai.com/codex/prompting/).
- Verified facts: `/goal` carries a durable objective and completion criteria in one
  task; it can be steered, paused, and resumed; Goal mode does not grant broader sandbox
  or approval authority; parallel changing work should use separate worktrees.
- Design impact: `$aiflow-autonomous` is explicit and goal-oriented, terminal budgets
  remain finite, state is durable outside chat history, and the tool never treats Goal
  mode as a permission escalation.

## Current model-family defaults

- Sources: [GPT-5.6 Sol migration guide](https://developers.openai.com/api/docs/guides/upgrading-to-gpt-5p6-sol.md)
  and [GPT-5.6 prompting guidance](https://developers.openai.com/api/docs/guides/prompt-guidance-gpt-5p6.md),
  resolved live through the official latest-model resolver on 2026-07-22.
- Verified facts: `gpt-5.6-sol` is the explicit flagship target; Terra is the balanced
  lower-cost/medium-throughput tier; Luna is the high-volume, routing, extraction, or
  strict-latency tier. A role-aware migration must not replace every model with Sol.
- Design impact: supervisor, architect, implementation worker, scientific/engineering
  reviewer, test architect, release auditor, and difficult diagnosis default to Sol;
  codebase mapping, documentation research, UI audit, ordinary read-heavy review, and
  workflow chat default to Terra; narrow routing/classification defaults to Luna.
  Deterministic style/format/quality gates and the idle watchdog make zero model calls.
  All role mappings and reasoning efforts remain configurable; historical fixtures and
  explicit user pins are not rewritten blindly.

## CI runtimes

- Sources: the official [`actions/checkout`](https://github.com/actions/checkout),
  [`actions/setup-python` releases](https://github.com/actions/setup-python/releases),
  [`actions/setup-node` releases](https://github.com/actions/setup-node/releases), and
  [Python active releases](https://www.python.org/downloads/), checked 2026-07-22.
- Verified facts: the official action documentation uses `checkout@v6`,
  `setup-python@v6`, and `setup-node@v6`; Python 3.11 through 3.14 remain supported while
  3.15 is pre-release.
- Design impact: CI uses the v6 action lines and tests Python 3.11–3.14; pre-release
  Python is not a mandatory gate.
