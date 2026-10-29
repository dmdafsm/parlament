# Task readiness: analysis and architecture check

A short pass done by whoever implements the task, before editing. Not a separate meeting, agent or approval gate.

## Analysis pass

For a feature or data task, establish:

1. What question the result answers for the maintainer (for example "how often does my deputy vote?") and the observable output (a page section, an API field, a command).
2. The open limitations it touches; reduce the task to a coherent, implementable behavior.
3. Concrete examples of input and expected output, including failure cases: a member whose mandate ended, an unaffiliated member, a secret vote, a bill without a Senate number, a page that changed shape.
4. The source's terms, access limits and protections ([security and data](security-and-data.md)).
5. What evidence will establish the result: fixture tests, a hand-computed example, a reconciliation on real data, a browser check.

Small fixes need a few sentences in the PR. New analysis or open questions go into a local note under `.research/tasks/` using [the task brief template](templates/task-brief.md).

Do not invent a data rule to avoid a clarification. Ask only when the missing decision materially changes results; continue independent work meanwhile.

## Architecture impact

Record one of:

- **Existing pattern**: name the owning module/table; no decision record needed.
- **Material change**: write the smallest useful [decision record](decisions/template.md) first. Examples: a new data source, a new table owner, a change to how an indicator is defined, new infrastructure (a cache, queue, another database), anything touching personal data.
- **Missing decision**: name it and continue the work that does not depend on it.

## Before handoff

Run the applicable verification and real-data checks, inspect the diff, follow [code review](code-review.md) and record what is still limited.
