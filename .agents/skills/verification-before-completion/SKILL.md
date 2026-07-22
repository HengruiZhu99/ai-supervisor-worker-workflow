---
name: verification-before-completion
description: Audit an engineering completion claim against the original contract using fresh executable evidence and full-scope inspection. Use before saying work is done, accepting a task or milestone, handing off, releasing, or closing a bug.
---

# Verification Before Completion

Treat completion as unproven.

1. Re-read the original objective, constraints, non-goals, acceptance IDs, and mandatory
   commands.
2. Map every requirement to authoritative evidence. Mark missing, indirect, stale, or
   narrower evidence as not proven.
3. Inspect the full current diff and repository state, including untracked and
   pre-existing changes. Verify the claimed identity, branch, and revision.
4. Run fresh focused and broad gates. Confirm tests were discovered, exercised the
   intended behavior, and did not weaken thresholds or workloads.
5. Check negative paths, recovery behavior, documentation, quality/deprecation policy,
   and package contents when applicable.
6. Report exact commands, results, evidence paths, remaining limitations, and a precise
   recovery action for any blocker.

Do not infer broad completion from a narrow unit test, the absence of obvious failures,
a self-authored report, a passing mock, or an accepted commit. Say complete only when
every mandatory item is proved and no required work remains.
