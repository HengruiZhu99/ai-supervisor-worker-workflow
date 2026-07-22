# Agent Wrappers

Agent wrappers decouple workflow roles from the command-line tool used to run an
agent.

Each wrapper lives in:

```text
agent_wrappers/<wrapper-id>/wrapper.json
```

The registry is read by:

```bash
python3 scripts/agent_wrapper.py list --json
```

Built-in wrappers:

- `codex`: available for worker, reviewer, supervisor, modulator, and chat
  roles; recommended for every role. Sol is the default for implementation,
  review, supervision, and modulation; Terra is the default for chat.
- `cursor-agent`: legacy compatibility wrapper available only by explicit
  opt-in. It is not recommended for any role.

To add another wrapper, such as Claude Code:

1. Create `agent_wrappers/claude-code/wrapper.json`.
2. Declare supported roles, recommended roles, role defaults, and suggested
   models.
3. Either add a built-in runner in `scripts/agent_wrapper.py`, or provide a
   `command` array in `wrapper.json`.

Command templates may use:

```text
{role}
{workspace}
{prompt_file}
{model}
{output_format}
{reasoning_effort}
{extra_args}
```

Keep wrapper scripts role-neutral. The workflow loops decide whether an agent is
acting as worker, reviewer, supervisor, or chat.

## Consensus panels

The multi-model consensus orchestrator (`scripts/orchestrator.py`) reads panel
definitions from:

```text
agent_wrappers/panels/<panel-id>.json
```

Each panel lists `panelists` (id, wrapper, model, optional focus), a
`decision_schema` (`reviewer`, `supervisor`, or `generic`), a `quorum`
(`unanimous` or `majority`), and `max_rounds`. List them with:

```bash
python3 scripts/orchestrator.py list-panels
```

The built-in panels use Codex throughout. Reviewer and supervisor panels put
GPT-5.6 Sol on the hardest correctness and decision work, with GPT-5.6 Terra on
read-heavy process checks. The specification panel adds GPT-5.6 Luna for narrow
consistency and testability classification. Override models per run without
editing the file via `--models "m1,m2,m3"` (or the
`REVIEWER_CONSENSUS_MODELS` / `SUPERVISOR_CONSENSUS_MODELS` environment
variables). Panelists always run read-only; prefer read-only-capable wrappers
(the Codex wrapper enforces the reviewer permission profile) for panel members.
