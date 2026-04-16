# Dependency Audit and Version Matrix

## Scope and method

This audit covers:

- Python dependencies declared in `requirements.txt`
- Node dependencies declared in `frontend/package.json`
- Lockfile/install state from `frontend/package-lock.json` and `npm ls --depth=0`
- Runtime usage checks via imports/config references in:
  - `backend/app`
  - `tests`
  - `frontend/src`
  - `frontend` build config files

Version signals used:

- Python: `pip list --outdated --format=json`
- Node: `npm outdated --json`

Notes:

- "Current" in tables below means currently declared in manifest files.
- "Installed current" for Node may differ due caret ranges and lockfile resolution.
- Risk is the expected migration risk for moving to the listed intended target.

## Summary findings

- LangChain removal appears successful in source; dependencies are not in `requirements.txt`.
- Several declared dependencies appear unused in current runtime paths:
  - Python: `httpx`, `python-dotenv`, `structlog`, `pypdf`
  - Node: `class-variance-authority`
- Frontend toolchain versions in `package.json` are behind lockfile-resolved versions and can be safely aligned.
- Major-version upgrades (React 18->19, Tailwind 3->4, Vite 5->8) should be deferred to dedicated tickets due higher compatibility risk.

## Python dependency audit

| Package | Current declared | Usage evidence | Intended target | Risk | Recommendation |
|---|---:|---|---|---|---|
| fastapi | `0.135.3` | API routers and app startup in `backend/app/api/*`, `backend/app/main.py` | Keep on current latest stable line; validate with Starlette `0.50.0` | Medium | Completed direct-latest migration with contract tests |
| uvicorn[standard] | `0.44.0` | `import uvicorn` in `backend/app/main.py` | Keep current stable line | Low | Upgraded |
| openai | `2.32.0` | Provider clients in `backend/app/llm_model/providers/openai_provider.py`, `backend/app/embedding/providers/openai_provider.py` | Keep current v2 line and harden parser fallbacks | Medium | Completed migration; monitor runtime response-shape drift |
| pydantic | `2.13.1` | Models/settings in `backend/app/core/models.py`, `backend/app/core/config.py` | Keep current compatible v2 line | Medium | Upgraded to satisfy sqlmodel>=0.0.38 |
| pydantic-settings | `2.13.1` | `BaseSettings` in `backend/app/core/config.py` | Keep current compatible v2 line | Medium | Upgraded with pydantic |
| httpx | `0.25.2` | No runtime imports found (only logger-name string in `backend/app/utils/logging.py`) | Remove | Low | Remove from `requirements.txt` unless planned near-term use |
| python-dotenv | `1.0.0` | No imports found | Remove | Low | Remove if env loading is not reintroduced |
| python-multipart | `0.0.9` | FastAPI `UploadFile/File` endpoints in `backend/app/api/files.py` imply runtime parser dependency | Upgrade (`0.0.26`) | Low | Keep and upgrade patch |
| structlog | `23.2.0` | No imports found | Remove | Low | Remove from `requirements.txt` |
| pytest | `7.4.3` | Tests under `tests/` | Upgrade (`9.0.x`) | Medium | Upgrade with test-runner ticket |
| pytest-asyncio | `0.21.1` | No async test markers/usages found | Remove (or upgrade only if async tests planned) | Low | Remove for now as unused |
| black | `23.11.0` | Makefile/pyproject tooling | Upgrade (`26.x`) | Low | Safe-now tooling upgrade |
| flake8 | `6.1.0` | Makefile lint target | Upgrade (`7.3.x`) | Low | Safe-now tooling upgrade |
| isort | `5.12.0` | `pyproject.toml` has isort config | Upgrade (`8.x`) | Low | Safe-now tooling upgrade |
| faiss-cpu | `1.13.0` | `import faiss` in `backend/app/rag/manager.py`, `backend/app/rag/daily_store.py` | Upgrade patch (`1.13.2`) | Medium | Upgrade carefully; verify wheel/platform behavior |
| tiktoken | `0.7.0` | Multiple runtime token-estimation imports (`chat`, `rag`, `memory`, `dream`, etc.) | Upgrade within major (`0.12.x`) | Medium | Upgrade with prompt/token regression checks |
| filelock | `3.16.0` | Locks in `backend/app/core/memory.py`, `backend/app/api/projects.py`, `backend/app/sleep/cycle.py`, `backend/app/rag/daily_store.py` | Upgrade (`3.28.x`) | Low | Safe-now upgrade candidate |
| sqlmodel | `0.0.38` | DB models/session/select in `backend/app/core/database.py`, `backend/app/core/db_models.py`, project/chat paths | Keep current latest stable | Medium | Upgraded; round-trip migrations validated |
| alembic | `1.18.4` | Migrations and runtime bootstrap in `backend/alembic/*`, `backend/app/core/database.py` | Keep current latest stable | Medium | Upgraded; round-trip migrations validated |
| pypdf | `4.3.1` | No imports found in current backend runtime | Remove | Low | Remove unless PDF support is being restored immediately |
| beautifulsoup4 | unpinned | Used only in tooling scripts (`tools/import_chat_html_to_daily.py`, `tools/extract_chat.py`) | Keep if tools are supported; pin explicit version | Low | Keep but pin version and classify as tool-only |
| APScheduler | `3.10.4` | Scheduler imports in `backend/app/main.py` | Upgrade patch/minor (`3.11.x`) | Low | Safe-now upgrade candidate |

### Python notes

- `requirements.txt` currently mixes runtime, test, formatting, and tool-script dependencies. Consider splitting into:
  - `requirements.txt` (runtime only)
  - `requirements-dev.txt` (test/format/lint)
  - `requirements-tools.txt` (optional scripts like BeautifulSoup HTML import)
- `beautifulsoup4` is currently unpinned while most other packages are pinned; this is inconsistent with deterministic builds.

## Node dependency audit

### Runtime dependencies (`frontend/package.json` -> `dependencies`)

| Package | Declared range | Installed current | Usage evidence | Intended target | Risk | Recommendation |
|---|---:|---:|---|---|---|---|
| react | `^18.3.1` | `18.3.1` | App/components in `frontend/src` | Keep React 18 line for now | Medium (to 19) | Keep now; defer React 19 migration |
| react-dom | `^18.3.1` | `18.3.1` | `frontend/src/main.tsx` | Keep React 18 line for now | Medium (to 19) | Keep now; defer React 19 migration |
| clsx | `^2.1.1` | `2.1.1` | `frontend/src/lib/utils.ts` | Keep | Low | Keep as-is |
| tailwind-merge | `^3.3.1` | `3.3.1` | `frontend/src/lib/utils.ts` | Upgrade to `^3.5.0` | Low | Safe-now upgrade candidate |
| class-variance-authority | `^0.7.1` | `0.7.1` | No imports found | Remove | Low | Remove from dependencies |

### Dev dependencies (`frontend/package.json` -> `devDependencies`)

| Package | Declared range | Installed current | Latest | Usage evidence | Intended target | Risk | Recommendation |
|---|---:|---:|---:|---|---|---|---|
| @types/react | `^18.3.5` | `18.3.25` | `19.2.14` | TS React typing | Update within React 18 (`^18.3.28`) | Low | Safe-now upgrade candidate |
| @types/react-dom | `^18.3.0` | `18.3.7` | `19.2.3` | TS React DOM typing | Keep current React 18 type line | Low | Optional small bump |
| @vitejs/plugin-react | `^4.3.1` | `4.7.0` | `6.0.1` | `frontend/vite.config.ts` | Keep plugin 4 line with Vite 5 | Medium/High to v6 | Keep now |
| autoprefixer | `^10.4.20` | `10.4.21` | `10.5.0` | `frontend/postcss.config.js` | Upgrade to `^10.5.0` | Low | Safe-now upgrade candidate |
| baseline-browser-mapping | `^2.9.19` | `2.9.19` | `2.10.19` | Lockfile transitive support | Upgrade to latest 2.x | Low | Safe-now upgrade candidate |
| postcss | `^8.4.47` | `8.5.6` | `8.5.10` | Tailwind/PostCSS toolchain | Upgrade to `^8.5.10` | Low | Safe-now upgrade candidate |
| tailwindcss | `^3.4.13` | `3.4.18` | `4.2.2` | Tailwind config files | Upgrade patch in v3 (`^3.4.19`) | Medium (to v4 high) | Keep v3 line now; defer v4 migration |
| typescript | `^5.6.3` | `5.9.3` | `6.0.2` | TS build/typecheck | Keep on 5.x (`^5.9.3`) | Medium (to v6) | Safe-now minor update in v5 |
| vite | `^5.4.8` | `5.4.20` | `8.0.8` | Build/dev scripts and config | Keep Vite 5 line (`^5.4.21`) | Medium/High to v8 | Safe-now patch update only |

## Recommended change set

### Safe-now (low risk)

1. Remove clearly unused dependencies:
   - Python: `httpx`, `python-dotenv`, `structlog`, `pypdf`, `pytest-asyncio` (if async tests are not expected imminently)
   - Node: `class-variance-authority`
2. Normalize and bump low-risk versions:
   - Python: `uvicorn`, `python-multipart`, `black`, `flake8`, `isort`, `filelock`, `APScheduler`
   - Node: `tailwind-merge`, `autoprefixer`, `baseline-browser-mapping`, `postcss`, `@types/react` (React 18 line), `vite` patch-level
3. Pin `beautifulsoup4` explicitly (if kept) and mark it as tool-only dependency.

### Defer to dedicated upgrade tickets

1. Frontend major upgrades:
   - React 18 -> 19
   - Tailwind 3 -> 4
   - Vite 5 -> 8 and plugin alignment
   - TypeScript 5 -> 6

## Validation checklist for follow-up dependency-change PR

- Backend:
  - `python3 -m compileall backend/app`
  - `make test-backend`
  - `make lint-backend`
- Frontend:
  - `cd frontend && npm install`
  - `make build`
  - `make test-frontend` (or explicit skip if no test script by design)
- Migration smoke:
  - `make upgrade`
  - run app startup and verify `/health`, `/chat`, `/projects`, `/sleep`, `/dream` paths

## SQLModel + Alembic compatibility pass results

- Final pinned versions:
  - `sqlmodel==0.0.38`
  - `alembic==1.18.4`
  - resolved `SQLAlchemy==2.0.44`
  - required compatible bump: `pydantic==2.13.1`, `pydantic-settings==2.13.1`
- ORM API compatibility update:
  - replaced legacy `session.query(Project).all()` with `session.exec(select(Project)).all()` in `backend/app/core/personality.py`
- Alembic cohesion hardening:
  - `backend/app/core/database.py` now sets Alembic `script_location` to an absolute path before `command.upgrade(...)` so migrations run reliably regardless of process working directory
  - normalized no-op revision metadata in `backend/alembic/versions/9e31b730e007_update.py` (`branch_labels` / `depends_on` now `None`, not string literals)
- Migration validation evidence:
  - disposable DB round-trip `upgrade head -> downgrade -1 -> upgrade head` succeeds
  - `alembic_version` returns `0010` after round-trip
  - key schema artifacts confirmed: `project.last_semantic_handle`, `chatmessage.tags_meta_json`, `chatmessage.semantic_handle`
  - `pip check` returns clean dependency graph
- Runtime smoke evidence:
  - `pytest tests/test_main.py tests/test_llm.py` passes
  - startup migration path via `init_db()` now yields `alembic_version=0010` on disposable DB (no missing `script_location` failure)
- Operational caveats:
  - `alembic.ini` `sqlalchemy.url` remains the offline/default URL while online migrations use `get_engine()` in `env.py`; this is intentional but should be kept in sync with deployment DB conventions
  - `TestClient` only runs lifespan startup when entered as a context manager (important for DB startup smoke scripts)

