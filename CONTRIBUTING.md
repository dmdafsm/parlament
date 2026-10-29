# Contributing

Start with [AGENTS.md](AGENTS.md) and the [architecture](docs/architecture.md).

Run `python3 scripts/install_hooks.py` once per clone, then work on a `<type>/<topic>` branch such as `feat/senate-votes` or `fix/agenda-dates`. main is protected locally and integrates through PRs. See the [branch policy](docs/engineering/branch-policy.md).

## Workflow

1. Pick a feature or data task, or a `REPO` maintenance task.
2. Do the [readiness pass](docs/engineering/task-readiness.md): the smallest coherent result and the evidence needed to accept it.
3. Implement following the [coding standards](docs/engineering/coding-standards.md) and the [security/data rules](docs/engineering/security-and-data.md).
4. Run focused checks (`uv run pytest tests/test_x.py`), then `python3 scripts/verify.py`. See [testing and verification](docs/engineering/testing-and-verification.md).
5. Review the diff ([code review](docs/engineering/code-review.md)). Open a PR using the template.

Code, identifiers and engineering docs are in English; user-facing text (site, CLI output) is Romanian. Keep one language per file.

## Toolchain

- [uv](https://docs.astral.sh/uv/) manages Python 3.12 and dependencies (`pyproject.toml`, `uv.lock`).
- PostgreSQL 18 for development and tests: `docker compose up -d db`.
- Ruff formats and lints; pytest runs the tests.
- `scripts/` checks use only the Python standard library.
- Frontend assets (Beer CSS, htmx) are vendored by `scripts/vendor_assets.py` with pinned versions and SHA-256 hashes.

## Dependencies and decisions

Add dependencies with `uv add` and commit `uv.lock`. Check documentation, license and maintenance first. Use [the decision template](docs/engineering/decisions/template.md) for an architecture, data-source or security tradeoff.

## Definition of done

- The behavior works, with evidence appropriate to its risk; data changes are spot-checked against the official source.
- Provenance (source URL), idempotency and polite source access are preserved.
- Formatting, lint and tests pass. Skipped or unavailable checks are listed as such.
- Docs, README and `uv.lock` match the implementation. No secrets or collected data committed.

See [maintainer setup](docs/engineering/maintainer-setup.md) for GitHub settings that repository files cannot activate.
