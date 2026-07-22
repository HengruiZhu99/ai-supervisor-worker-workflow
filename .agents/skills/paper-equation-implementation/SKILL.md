---
name: paper-equation-implementation
description: Guide implementation and review of algorithms from papers, equations, or technical references.
---

# Paper Equation Implementation

## When to Use

Use when a worker job maps equations, algorithms, or methods from a paper or technical reference into code.

## Checklist

- Map paper notation to code names explicitly.
- Preserve equation numbers or reference labels in comments, docs, or tests when useful.
- Document assumptions, approximations, boundary conditions, and units.
- Test limiting cases and simple analytic cases.
- Check dimensions and array shapes against the equations.
- Avoid silent formula changes to make tests pass.
- Separate reference implementation from optimized implementation where practical.

## Output Format

Return:
1. Equation-to-code mapping.
2. Assumptions and conventions.
3. Tests and limiting cases.
4. Validation references.
5. Risks or ambiguities.

## Common Failure Modes

- Off-by-one indexing changes mathematical meaning.
- Transposed dimensions or layout assumptions are undocumented.
- Constants are copied without units.
- Formula changes are hidden in implementation details.
- Tests validate only one nominal case.
