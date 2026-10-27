# GitHub settings outside the working tree

Repository files provide instructions and a workflow; they do not enable server-side protections.

The default branch is main. [Branch policy](branch-policy.md) describes the local hooks, the CI branch guard and the importable [ruleset](../../.github/rulesets/protected-branches.json). After the first push and a successful workflow run, configure the default branch ruleset as the repository plan allows:

- Require a pull request and resolved conversations. With a sole maintainer, keep review evidence and explicit owner merge judgment instead of an impossible self-approval gate. See [review process](code-review.md).
- Require the `Repository verification` check from the `Verify` workflow.
- Prevent force pushes and deletion of the default branch, and limit bypass rights deliberately.
- Enable secret scanning/push protection, private vulnerability reporting and dependency alerts where supported.
- The repository is public: code and documentation only, no collected data or database dumps. Test fixtures are synthetic. See [security and data](security-and-data.md).
- Enable secret scanning push protection: on a public repository a pushed secret is exposed immediately.

Workflow permissions are contents:read. Verification needs no deployment, external message or production secret.

The workflow must run on pull requests and pushes. Avoid path filters on a required workflow, which can leave its required check missing. A merge queue needs the merge_group trigger.

Dependabot monitors GitHub Actions and the uv lockfile. Review updates and lockfile changes instead of auto-merging them.

Local validation cannot prove GitHub-hosted execution or active branch protection; check an actual run after publishing.
