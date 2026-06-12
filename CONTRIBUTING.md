# Contributing to Syx

Thanks for wanting to help. Syx is an open source AI memory and chatbot framework, and contributions are welcome across code, tests, docs, examples, bug reports, and design discussion.

Syx is also a requirements-driven project. For anything larger than a typo or small bug fix, please read the project specifications before changing behavior:

- [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) is the consolidated as-built specification.
- [`docs/DELTAS.md`](docs/DELTAS.md) is the active change layer for newer engineering decisions,
  migrations, or requirement updates that have not yet been rolled into the
  requirements baseline.
- If those documents conflict, [`docs/DELTAS.md`](docs/DELTAS.md) wins for current implementation work.

For testing and coverage expectations, read [`docs/COVERAGE.md`](docs/COVERAGE.md) before adding or changing tests. It is the authoritative policy for what counts as meaningful test coverage in this project.

## Getting Started

Fork the repo on GitHub first, then clone your fork:

```bash
git clone https://github.com/<your-username>/project_syx.git
cd project_syx
git remote add upstream https://github.com/cjsthecoder/project_syx.git
```

Syx currently targets Python 3.13 and Node.js 20.

Create a Python virtual environment, install backend dependencies, install frontend dependencies, and build the app:

```bash
python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
cd frontend && npm install && cd ..

pip install pre-commit
pre-commit install
```
To build the front end:

```bash
make build
```

To generate a local `.env` file:

```bash
make setup-env
```

Then edit `.env` and set your own `OPENAI_API_KEY` before running the app. Never commit `.env` or real API keys.

Run the unified app:

```bash
make run
```

The app is served at `http://localhost:8000`, API docs at `http://localhost:8000/api/docs`, and health checks at `http://localhost:8000/health`.

## Local Checks

The `pre-commit install` step is important. The repo has a `.pre-commit-config.yaml` that pins the backend formatting and lint hooks close to the versions CI uses, but the actual Git hook is per-machine and must be installed locally:

```bash
pre-commit install
```

Without this step, you can commit code that passes your local ad hoc checks but fails CI on push. Run `make lint`, `make test`, or `make ci` before opening a PR.

## Project Structure

```text
backend/app/              FastAPI backend, LLM/embedding factories, memory, RAG, Sleep, Dream
frontend/                 React + Vite frontend
tests/                    Backend pytest suite
docs/                     Requirements, deltas, testing policy, and project documentation
tools/                    Local tools and examples
data/                     Generated local project memory and database files
runtime/                  Generated logs, run artifacts, and state files
```

Do not commit generated or private local state from `data/`, `runtime/`, `.env`, coverage output, debug artifacts, or built assets unless a maintainer explicitly asks for a specific generated file.

## Development Workflow

1. Open an issue or discussion for meaningful behavior changes.
2. Check [`docs/DELTAS.md`](docs/DELTAS.md) and [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) before implementing.
3. If the change overlaps with or supersedes existing documented behavior, update or propose a delta first.
4. Create a feature branch from `main`.
5. Make the smallest focused change that satisfies the requirement.
6. Add or update tests and docs when behavior changes.
7. Run the relevant checks locally before opening a PR.

Small documentation fixes, typo fixes, and clearly isolated bug fixes do not need a new delta.

## Running Tests

Run all tests:

```bash
make test
```

Run backend tests only:

```bash
make test-backend
```

Run frontend tests only:

```bash
make test-frontend
```

Run the full local CI gate:

```bash
make ci
```

The local CI gate runs backend and frontend linting, backend coverage, and frontend tests. It uses a safe placeholder `OPENAI_API_KEY` for coverage so tests can exercise config-dependent paths without using real credentials.

Backend tests run from the `backend/` working directory and import modules through `app.*`. Do not mix `backend.app.*` imports into tests; that can load SQLModel table classes twice and cause duplicate-table errors.

## Coverage Policy

[`docs/COVERAGE.md`](docs/COVERAGE.md) is the authoritative testing and coverage policy.

The short version:

- Test real behavior, not coverage numbers.
- Use real `faiss` and `numpy` when available.
- Fake only external boundaries such as embedding clients, settings, DB sessions, and debug writers.
- Reset module-level global state between tests.
- Make background work deterministic in tests.
- Assert on logs with `caplog` for best-effort failure branches.
- Do not use `# pragma: no cover` for reachable business logic.

Generate backend coverage reports with:

```bash
make coverage-backend
```

Coverage reports are written under `backend/` as terminal output, HTML, XML, and LCOV. These outputs are generated artifacts and should not be committed.

## Linting and Formatting

Run all lint checks:

```bash
make lint
```

Run backend lint checks:

```bash
make lint-backend
```

Run frontend lint and type checks:

```bash
make lint-frontend
```

Format code:

```bash
make format
```

Backend formatting and linting use Black, isort, and Ruff with settings in `pyproject.toml`. Frontend checks use the scripts in `frontend/package.json`, including ESLint and TypeScript.

## Code Style

Python:

- Use type hints where they improve clarity.
- Use Google-style docstrings for public functions, API handlers, service-layer functions, lifecycle functions, Pydantic models, dataclasses, and architecture-boundary classes.
- Keep functions focused. Prefer small named helpers over large multi-phase functions.
- Catch specific exception types when possible.
- Never swallow exceptions silently. Every `except` block must log, re-raise, or return an explicit fallback.

Frontend:

- Prefer functional React components, hooks, and plain functions.
- Keep API clients separate from UI components.
- Add JSDoc for exported functions, custom hooks, shared utilities, API clients, reducers, context providers, and complex components.
- Do not add comments or JSDoc that only restate obvious type information.

New Python and TypeScript/JavaScript source files must include the repository SPDX header. Existing helper tooling may be used to normalize headers when available.

## Dependencies

Do not add dependencies casually. New dependencies should have a clear purpose, fit the existing architecture, and be discussed in the PR or issue.

When adding frontend dependencies, use npm from `frontend/`. When adding Python dependencies, update the appropriate Python dependency file and explain why the dependency is needed.

## Documentation

Documentation changes are part of the implementation when behavior changes.

Use these documents intentionally:

- [`README.md`](README.md) for onboarding and the public landing page.
- [`docs/DELTAS.md`](docs/DELTAS.md) for current behavior changes and overrides.
- [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) for baseline requirements.
- [`docs/COVERAGE.md`](docs/COVERAGE.md) for testing and coverage rules.
- Focused docs under `docs/` for architecture, memory lifecycle, Sleep, Dream, and agent interfaces.

If a change alters documented behavior, update the relevant doc in the same PR.

## Security and Privacy

Do not commit:

- `.env` files.
- API keys or provider credentials.
- Private project memory.
- Local database files.
- Runtime logs.
- Debug artifacts containing private prompts, responses, or retrieved context.
- Generated coverage/build outputs.

Syx is intended for local development and trusted deployments. Treat generated memory and debug files as potentially sensitive.

See [`SECURITY.md`](SECURITY.md) for vulnerability reporting and current security assumptions.

## PR Guidelines

Before opening a PR:

1. Make sure the change is scoped and understandable.
2. Add or update tests when behavior changes.
3. Update docs when requirements, workflows, configuration, or public behavior change.
4. Run `make ci` if practical.
5. Include a clear PR summary, test plan, and any known risks.

Use clear commit messages. Conventional commits are welcome but not required for the first public release. Good examples:

- `docs: add memory lifecycle guide`
- `fix: handle empty daily memory during sleep`
- `test: cover agent memory search filters`
- `refactor: split sleep startup helpers`

## Git Identity for Contributions

Before pushing commits, verify that Git is configured with an email address GitHub can associate with your account:

```bash
git config user.name
git config user.email
```

This matters especially when commits are created through agentic coding tools or automation, because those tools may not inherit your normal shell Git configuration. Avoid placeholder values such as `your@email.com`.

## Community and Support

Use GitHub issues for bug reports and feature requests. Use discussions, if enabled, for questions, design ideas, and broader project conversation.

See [`SUPPORT.md`](SUPPORT.md) for support expectations.

## License

Syx is MIT licensed. Contributions are accepted under the same license. See [`LICENSE`](LICENSE).
