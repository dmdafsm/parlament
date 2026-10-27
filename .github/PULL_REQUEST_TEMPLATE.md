## Problem and result

Related task: Px.n / REPO. Describe the trigger, resulting behavior and acceptance criteria.

Architecture impact: existing pattern (owning module/table), or material change with a linked decision record.

## Validation

| Command or check | Actual result |
| --- | --- |
| `python3 scripts/verify.py` | Passed / failed / not run, with reason |
| Real-data check (collector run, spot check against cdep.ro/senat.ro) | Result or not applicable, with reason |
| Browser check (desktop and phone width) | Result or not applicable, with reason |

## Data and source impact

Affected sources and request volume; new migrations; provenance; personal data. Use "not applicable" with a reason when appropriate.

## Review notes

Material tradeoffs, dependency changes, known limitations. Review status: self-review / independent review / not run, with scope.

- [ ] The diff is focused; docs and `uv.lock` match the implementation.
- [ ] Acceptance criteria have evidence; incomplete work is stated explicitly.
- [ ] No secrets, collected data or real pages committed; fixtures are synthetic.
