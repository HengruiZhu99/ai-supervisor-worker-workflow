# AIFLOW v2 RED evidence

Captured on 2026-07-22 against base implementation commit `e9311a9`, after the P0
documentation-only commit and before production implementation.

Command:

```text
python3 -m unittest discover -s tests/regression -p 'test_*_red.py' -v
```

Result: 23 tests ran; all 23 failed for the intended legacy behavior after correcting a
test-discovery key from `members` to the repository's actual `panelists` schema.

## Intended failure signatures

| Group | Tests | Observed RED reason |
|---|---:|---|
| Backend/model defaults | 3 | Codex has no recommended roles; active defaults are GPT-5.5; all panelists still use Cursor/older models |
| Permissions | 3 | reviewer and writer commands both emit `danger-full-access`; parent preflight is absent |
| Project contamination | 2 | inherited project-A environment resolves A while launched in B; generic entrypoints contain BBHK/oneAPI/site tokens |
| Progress starvation | 3 | changing subsystems resets the streak; fake implementation metadata passes; a free-text future job passes as an unlock |
| State concurrency | 3 | mutation without expected revision succeeds; the CAS flag is absent; no single-writer store exists |
| Quality/deprecation | 4 | worker loop has 1,699 logical lines; quality command and hard-limit/expiry/layer gates are absent |
| Integration | 2 | the first apply operation is a direct target merge; target-HEAD CAS and integrated-state gates are absent |
| Finite execution | 3 | all three loops contain permanent polling; worker/test timeout defaults are zero; finite controller is absent |

The failures are retained as executable tests. They are not waived, skipped, or inverted
during implementation.

## Baseline guard

The independent legacy suite remained green immediately before RED creation:

```text
python3 -m unittest discover -s scripts -p 'test_*.py' -v
Ran 85 tests ... OK
```
