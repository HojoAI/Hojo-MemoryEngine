# Contributing to Memory Engine

Thank you for your interest in contributing!

## Getting started

1. Fork the repository and create a feature branch from `main` (or `opensource` for the public release line).
2. Copy `.env.example` to `.env` and configure local dependencies (MySQL, Redis, MongoDB, Qdrant).
3. Install backend dependencies: `cd backend && uv sync`.
4. Run tests: `cd backend && uv run pytest`.

## Code style

- **Python**: type hints, Google-style docstrings, format with `ruff`.
- **Java SDK**: follow existing package layout under `com.memoryengine`.
- Keep changes focused; avoid unrelated refactors in the same PR.

## Pull requests

- Describe the problem and solution clearly.
- Add or update tests when behavior changes.
- Update `docs/` when user-facing APIs or configuration change.
- Ensure CI passes (or note why checks are skipped).

## Reporting issues

Use the issue tracker with:

- Steps to reproduce
- Expected vs actual behavior
- Environment (OS, Python version, deployment mode)

For security vulnerabilities, see [SECURITY.md](./SECURITY.md) — **do not** open public issues for sensitive findings.
