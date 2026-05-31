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

- `cursor-agent`: worker and reviewer roles.
- `codex`: supervisor and chat roles.

To add another wrapper, such as Claude Code:

1. Create `agent_wrappers/claude-code/wrapper.json`.
2. Declare supported roles and suggested models.
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
