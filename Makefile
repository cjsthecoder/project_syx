# Syx AGI Chatbot Framework - Build Automation
# Make targets for development and deployment

.PHONY: help install build run clean test coverage coverage-backend lint format generate-docs docker-data-dirs docker-data-permissions docker-setup run-docker restart-docker stop-docker docker-rebuild

# Resolve Python interpreter once (prefer local venv, then system python/python3)
PYTHON := $(shell if [ -x venv/bin/python ]; then printf "%s" "$(CURDIR)/venv/bin/python"; else command -v python || command -v python3; fi)

# Default target
help:
	@echo "Syx AGI Chatbot Framework - Available Commands:"
	@echo ""
	@echo "Core:"
	@echo "  make install              - Install all dependencies (Python + Node.js)"
	@echo "  make build                - Build React app (Vite)"
	@echo "  make run                  - Start unified FastAPI server"
	@echo "  make setup                - Generate .env, install, and build"
	@echo "  make setup-env            - Generate a fresh .env with defaults"
	@echo ""
	@echo "Dev:"
	@echo "  make dev-backend          - Run backend only (FastAPI)"
	@echo "  make dev-frontend         - Run frontend only (Vite dev server)"
	@echo "  make copy-static          - No-op (Vite outputs directly to backend/app/static)"
	@echo ""
	@echo "Database:"
	@echo "  make migrate              - Create Alembic revision (autogenerate)"
	@echo "  make upgrade              - Apply DB migrations"
	@echo "  make downgrade            - Revert last DB migration"
	@echo ""
	@echo "Quality:"
	@echo "  make test                 - Run all tests (backend + frontend)"
	@echo "  make test-backend         - Run backend tests"
	@echo "  make test-frontend        - Run frontend tests"
	@echo "  make coverage             - Backend coverage reports (term + html + xml + lcov)"
	@echo "  make lint                 - Lint all code (black/isort/ruff + tsc)"
	@echo "  make lint-backend         - Lint Python code (black --check, isort --check, ruff)"
	@echo "  make lint-frontend        - Lint TypeScript/React code (eslint + tsc --noEmit)"
	@echo "  make format               - Format all code"
	@echo "  make format-backend       - Format Python code"
	@echo "  make format-frontend      - Format TypeScript/React code"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean                - Clean build artifacts (all)"
	@echo "  make clean-backend        - Clean Python artifacts"
	@echo "  make clean-frontend       - Clean Node.js artifacts"
	@echo "  make clean-static         - Clean FastAPI static files"
	@echo ""
	@echo "Docs:"
	@echo "  make generate-docs        - Generate architecture diagram"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-data-dirs     - Create host dirs for bind mounts (data/memory, data/db, runtime/logs, runtime/runs, runtime/state)"
	@echo "  make docker-data-permissions - Set permissions on data dirs for container read/write"
	@echo "  make docker-setup         - Create data dirs and set permissions (run before first docker-compose up)"
	@echo "  make run-docker           - Prepare host dirs and start docker compose stack"
	@echo "  make restart-docker       - Restart docker compose stack cleanly"
	@echo "  make stop-docker          - Stop and remove docker compose stack"
	@echo "  make docker-rebuild      - Git pull, rebuild image, and restart containers (for code updates)"
	@echo ""

# Install all dependencies
install: install-backend install-frontend
	@echo "✅ All dependencies installed successfully"

install-backend:
	@echo "📦 Installing Python dependencies..."
	@if [ ! -x venv/bin/python ]; then \
		echo "🐍 Creating Python virtual environment at ./venv"; \
		python3 -m venv venv; \
	fi
	@echo "⬆️  Upgrading pip/setuptools/wheel in venv..."
	@venv/bin/python -m pip install --upgrade pip setuptools wheel
	@echo "🦀 Checking Rust toolchain for building tiktoken..."
	@sh -c 'if ! command -v rustc >/dev/null 2>&1; then \
		echo "🦀 Installing Rust toolchain (non-interactive)"; \
		curl https://sh.rustup.rs -sSf | sh -s -- -y >/dev/null 2>&1 || true; \
	fi'
	@# Ensure current shell picks up cargo/rustc for the install step
	@sh -c 'if [ -f "$$HOME/.cargo/env" ]; then . "$$HOME/.cargo/env"; fi; \
		PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 venv/bin/python -m pip install -r requirements.txt'
	@echo "✅ Backend dependencies installed"

install-frontend:
	@echo "📦 Installing Node.js dependencies..."
	cd frontend && npm install
	@echo "✅ Frontend dependencies installed"

# Build React app into FastAPI static folder
build: build-frontend
	@echo "✅ Build completed successfully"

build-frontend:
	@echo "🔨 Building React app with Vite..."
	cd frontend && npm run build
	@echo "✅ React app built"

copy-static:
	@echo "ℹ️  Skipping copy: Vite is configured to output directly to backend/app/static"

# Start the unified FastAPI server
run: build
	@echo "🚀 Starting Syx server..."
	@echo "   Frontend: http://localhost:8000"
	@echo "   API Docs: http://localhost:8000/api/docs"
	@echo "   Health:   http://localhost:8000/health"
	@echo ""
	@if [ -z "$$VIRTUAL_ENV" ]; then \
		if [ ! -d venv ]; then \
			echo "🐍 Creating Python virtual environment at ./venv"; \
			python3 -m venv venv; \
			echo "📦 Installing backend requirements into ./venv"; \
			. venv/bin/activate && pip install -r requirements.txt; \
		else \
			echo "ℹ️  Using existing ./venv"; \
		fi; \
		echo "✅ Virtual environment ready"; \
		venv/bin/python -c "import fastapi" 2>/dev/null || (echo "📦 Installing backend requirements into ./venv" && venv/bin/python -m pip install -r requirements.txt); \
		cd backend && ../venv/bin/python -m app.main; \
	else \
		python -c "import fastapi" 2>/dev/null || (echo "📦 Installing backend requirements into active venv" && python -m pip install -r requirements.txt); \
		cd backend && python -m app.main; \
	fi

# Alembic helpers
migrate:
	cd backend && alembic revision --autogenerate -m "update"

upgrade:
	cd backend && alembic upgrade head

downgrade:
	cd backend && alembic downgrade -1

# Danger: wipe all project data and DB; recreate schema
HARD_RESET:
	@echo "⚠️  HARD RESET will DELETE all project data and the SQLite DB."
	@echo "   - Removing data/memory/*"
	@echo "   - Removing data/db/syx.db"
	@echo "   - Recreating empty DB (alembic upgrade)"
	@echo ""
	@read -p "Type 'YES' to proceed: " CONFIRM; \
	if [ "$$CONFIRM" != "YES" ]; then echo "Aborted."; exit 1; fi; \
	echo "Deleting data/memory/* ..."; \
	rm -rf data/memory/* 2>/dev/null || true; \
	echo "Deleting SQLite DB ..."; \
	rm -f data/db/syx.db 2>/dev/null || true; \
	echo "Removing runtime sleep lock if present ..."; \
	rm -f runtime/state/sleep.lock 2>/dev/null || true; \
	echo "Deleting logs ..."; \
	rm -f runtime/logs/*.log 2>/dev/null || true; \
	echo "Recreating DB schema ..."; \
	mkdir -p data/db; \
	cd backend && alembic upgrade head; \
	echo "✅ HARD RESET complete. Start the server and Main will be reseeded."

# Clean build artifacts and dependencies
clean: clean-backend clean-frontend clean-static
	@echo "🧹 Cleanup completed"

clean-backend:
	@echo "🧹 Cleaning Python artifacts..."
	@find backend -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find backend -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅ Backend cleaned"

clean-frontend:
	@echo "🧹 Cleaning Node.js artifacts..."
	cd frontend && rm -rf node_modules dist .vite 2>/dev/null || true
	@echo "✅ Frontend cleaned"

clean-static:
	@echo "🧹 Cleaning static files..."
	@rm -rf backend/app/static/* 2>/dev/null || true
	@echo "✅ Static files cleaned"

# Run tests
test: test-backend test-frontend
	@echo "✅ All tests completed"

test-backend:
	@echo "🧪 Running backend tests..."
	cd backend && $(PYTHON) -m pytest ../tests/ -v
	@echo "✅ Backend tests completed"

test-frontend:
	@echo "🧪 Running frontend tests..."
	@if node -e "const s=require('./frontend/package.json').scripts||{}; process.exit(s.test?0:1)"; then \
		cd frontend && npm run test -- --run; \
	else \
		echo "ℹ️  Skipping frontend tests: no 'test' script in frontend/package.json"; \
	fi
	@echo "✅ Frontend tests completed"

# Coverage (backend): run the suite once and emit every report format we use.
# Outputs land under backend/: htmlcov/ (browse), coverage.xml (Cobertura),
# and lcov.info (Coverage Gutters / Codecov). All are gitignored.
coverage: coverage-backend
	@echo "✅ Coverage reports generated"

coverage-backend:
	@echo "📊 Measuring backend coverage (term-missing + html + xml + lcov)..."
	cd backend && $(PYTHON) -m pytest ../tests/ \
		--cov=app \
		--cov-config=../pyproject.toml \
		--cov-report=term-missing \
		--cov-report=html \
		--cov-report=xml \
		--cov-report=lcov:lcov.info
	@echo "✅ Reports: backend/htmlcov/index.html | backend/coverage.xml | backend/lcov.info"

# Run linting
lint: lint-backend lint-frontend
	@echo "✅ Linting completed"

lint-backend:
	@echo "🔍 Linting Python code (black --check, isort --check, ruff)..."
	$(PYTHON) -m black --check backend tests tools
	$(PYTHON) -m isort --check-only backend tests tools
	$(PYTHON) -m ruff check backend tests tools
	@echo "✅ Backend linting completed"

lint-frontend:
	@echo "🔍 Linting TypeScript/React code (eslint + tsc --noEmit)..."
	@if node -e "const s=require('./frontend/package.json').scripts||{}; process.exit(s.lint?0:1)"; then \
		cd frontend && npm run lint; \
	else \
		echo "ℹ️  Skipping frontend lint: no 'lint' script in frontend/package.json"; \
	fi
	@if node -e "const s=require('./frontend/package.json').scripts||{}; process.exit(s.typecheck?0:1)"; then \
		cd frontend && npm run typecheck; \
	else \
		echo "ℹ️  Skipping frontend type-check: no 'typecheck' script in frontend/package.json"; \
	fi
	@echo "✅ Frontend lint + type-check completed"

# Format code
format: format-backend format-frontend
	@echo "✅ Code formatting completed"

format-backend:
	@echo "🎨 Formatting Python code (isort + black)..."
	$(PYTHON) -m isort backend tests tools
	$(PYTHON) -m black backend tests tools
	@echo "✅ Backend formatting completed"

format-frontend:
	@echo "🎨 Formatting TypeScript/React code..."
	@if node -e "const s=require('./frontend/package.json').scripts||{}; process.exit(s.format?0:1)"; then \
		cd frontend && npm run format; \
	else \
		echo "ℹ️  Skipping frontend format: no 'format' script in frontend/package.json"; \
	fi
	@echo "✅ Frontend formatting completed"

# Development helpers
dev-backend:
	@echo "🔧 Starting backend in development mode..."
	cd backend && $(PYTHON) -m app.main

dev-frontend:
	@echo "🔧 Starting frontend in development mode..."
	cd frontend && npm run dev

# Environment setup
setup-env:
	@echo "⚙️  Setting up environment..."
	@if [ -f .env ]; then \
		echo "🔁 Backing up existing .env to .env.old"; \
		mv -f .env .env.old; \
	fi; \
	echo "📝 Generating .env with defaults"; \
	{ \
		echo "# Syx AGI Chatbot Framework - Environment Variables"; \
		echo "# Edit values as needed. Comments are placed after each variable to avoid parser conflicts."; \
		echo ""; \
		echo "# === Core: OpenAI + Chat Model ==="; \
		echo "#OPENAI_API_KEY=your-openai-api-key-here"; \
		echo "# OpenAI API key used for chat and embeddings"; \
		echo ""; \
		echo "LLM_PROVIDER=openai"; \
		echo "# LLM provider selector"; \
		echo ""; \
		echo "MODEL_NAME=gpt-5.5"; \
		echo "# Main runtime chat model selected by llm factory"; \
		echo ""; \
		echo "LLM_MINI_MODEL=gpt-5-mini"; \
		echo "# Mini runtime model selected by llm factory"; \
		echo ""; \
		echo "MODEL_TEMPERATURE=1.0"; \
		echo "# Sampling temperature (0.0–2.0)"; \
		echo ""; \
		echo "MODEL_MAX_TOKENS=128000"; \
		echo "# Max tokens in a single model response"; \
		echo ""; \
		echo "AVAILABLE_MODELS=[\"gpt-5.5\",\"gpt-5-mini\",\"gpt-5.2\",\"gpt-5.1\",\"gpt-5.1-mini\",\"gpt-5.1-nano\",\"gpt-5\",\"gpt-5-nano\",\"gpt-4o\",\"gpt-4o-mini\",\"gpt-4.1\",\"gpt-4.1-mini\",\"gpt-4.1-nano\"]"; \
		echo "# Whitelisted chat models for the UI selector"; \
		echo ""; \
		echo "# === Server + CORS ==="; \
		echo "HOST=0.0.0.0"; \
		echo "# Server host interface"; \
		echo ""; \
		echo "PORT=8000"; \
		echo "# Server port"; \
		echo ""; \
		echo "RELOAD=true"; \
		echo "# Enable auto-reload in development"; \
		echo ""; \
		echo "CORS_ORIGINS=[\"http://localhost:3000\",\"http://localhost:5173\"]"; \
		echo "# Allowed browser origins for API"; \
		echo ""; \
		echo "# === Logging ==="; \
		echo "LOG_LEVEL=INFO"; \
		echo "# Log level (DEBUG, INFO, WARNING, ERROR)"; \
		echo ""; \
		echo "LOG_LEVEL_CONSOLE=INFO"; \
		echo "# Console log level (DEBUG, INFO, WARNING, ERROR)"; \
		echo ""; \
		echo "LOG_LEVEL_FILE=DEBUG"; \
		echo "# File log level (DEBUG, INFO, WARNING, ERROR)"; \
		echo ""; \
		echo "LOG_MAX_BYTES=10485760"; \
		echo "# Max bytes per rotating log file"; \
		echo ""; \
		echo "LOG_BACKUP_COUNT=5"; \
		echo "# Number of rotated log files per session"; \
		echo ""; \
		echo "LOG_PREVIEW_MAX_CHARS=1024"; \
		echo "# Max chars for log previews"; \
		echo ""; \
		echo "# === Database + Storage ==="; \
		echo "DB_PATH=../data/db/syx.db"; \
		echo "# SQLite database file path (or full URL like sqlite:///...)"; \
		echo ""; \
		echo "MEMORY_ROOT=../data/memory"; \
		echo "RUNS_DIR=../runtime/runs"; \
		echo "LOGS_DIR=../runtime/logs"; \
		echo "LOCK_DIR=../runtime/state"; \
		echo "# Runtime and storage roots"; \
		echo ""; \
		echo "MAX_UPLOAD_MB=10"; \
		echo "# Max size per uploaded file (MB)"; \
		echo ""; \
		echo "MAX_BATCH_MB=50"; \
		echo "# Max total size per upload request (MB)"; \
		echo ""; \
		echo "STORAGE_LIMIT_MB=500"; \
		echo "# Per-project storage cap (MB)"; \
		echo ""; \
		echo "# === Embeddings + Indexing ==="; \
		echo "EMBEDDING_PROVIDER=sentence_transformers"; \
		echo "# Embedding provider selector (openai|sentence_transformers)"; \
		echo ""; \
		echo "EMBEDDING_MODEL=text-embedding-3-large"; \
		echo "# OpenAI embedding model for document indexing"; \
		echo ""; \
		echo "SENTENCE_TRANSFORMERS_MODEL_ID=BAAI/bge-m3"; \
		echo "# Local sentence-transformers model id (used when EMBEDDING_PROVIDER=sentence_transformers)"; \
		echo ""; \
		echo "CHUNK_SIZE=600"; \
		echo "# Text chunk size used during embedding"; \
		echo ""; \
		echo "CHUNK_OVERLAP=80"; \
		echo "# Overlap between chunks during embedding"; \
		echo ""; \
		echo "MAX_EMBED_TOKENS_PER_REQUEST=180000"; \
		echo "# Safety cap: max total tokens per embeddings API request (headroom under provider cap)"; \
		echo ""; \
		echo "RAG_EMBED_REBUILD_WORKERS=3"; \
		echo "# Parallel workers for LTM embedding during rebuild (range 1-8)"; \
		echo ""; \
		echo "# === RAG (Main / LTM) ==="; \
		echo "RAG_ON_CHAT=true"; \
		echo "# If true, inject retrieved context into chat when index exists"; \
		echo ""; \
		echo "BASE_TOP_K=6"; \
		echo "# Base top-K used to derive per-source retrieval K"; \
		echo ""; \
		echo "RETRIEVAL_MULTIPLIER=2.0"; \
		echo "# PER_SOURCE_K = ceil(BASE_TOP_K * RETRIEVAL_MULTIPLIER)"; \
		echo ""; \
		echo "AGENT_MEMORY_MAX_ENTRY_CHARS=25000"; \
		echo "# Max serialized agent memory snippet size for full-entry expansion"; \
		echo ""; \
		echo "# === Daily Memory + Daily RAG ==="; \
		echo "CHAT_HISTORY_LIMIT_PAIRS=3"; \
		echo "# Number of prompt/response pairs kept in working memory"; \
		echo ""; \
		echo "# === Query Builder + Reranking ==="; \
		echo "BUILDER_MODEL=gpt-5-mini"; \
		echo "# LLM for query builder/router"; \
		echo ""; \
		echo "TAGGER_MODEL=gpt-5-mini"; \
		echo "# LLM used for tagging"; \
		echo ""; \
		echo "BUILDER_MAX_TOKENS=1024"; \
		echo "# Max tokens for builder output"; \
		echo ""; \
		echo "BUILDER_CACHE=true"; \
		echo "# Enable in-memory builder cache"; \
		echo ""; \
		echo "# === Working Memory ==="; \
		echo "CHAT_HISTORY_LIMIT=20"; \
		echo "# Number of recent messages kept per project in working memory"; \
		echo ""; \
		echo "# === Project Defaults (seeded files) ==="; \
		echo "DEFAULT_SYSTEM_PROMPT_PATH=backend/app/config/defaults/system_prompt.txt"; \
		echo "# Default system prompt file path"; \
		echo ""; \
		echo "DEFAULT_PERSONALITY_PROMPT_PATH=backend/app/config/defaults/personality.json"; \
		echo "# Default personality JSON file path"; \
		echo ""; \
		echo "# === Sleep Cycle + Verification ==="; \
		echo "ENABLE_SCHEDULER=true"; \
		echo "# Enable daily sleep scheduler"; \
		echo ""; \
		echo "SLEEP_CYCLE_HOUR=3"; \
		echo "# Local hour of day (0-23) to run sleep cycle"; \
		echo ""; \
		echo "SLEEP_CYCLE_MINUTE=0"; \
		echo "# Local minute of day (0-59) to run sleep cycle"; \
		echo ""; \
		echo "VERIFY_RAG=true"; \
		echo "# Enable post-rebuild verification"; \
		echo ""; \
		echo "FORCE_RAG_REBUILD_ON_STARTUP=false"; \
		echo "# Optional startup sweep: rebuild all project RAG indexes from uploads"; \
		echo ""; \
		echo "# === Instrumentation (V5.0) ==="; \
		echo "INSTRUMENTATION_ENABLED=false"; \
		echo "# Enable run/turn/invocation telemetry collection"; \
		echo ""; \
		echo "INSTRUMENTATION_MODE=metrics"; \
		echo "# metrics|research (research permits artifact capture)"; \
		echo ""; \
		echo "# INSTRUMENTATION_RUN_ID=<optional-run-id>"; \
		echo "# Optional run id override; leave commented to use runtime-generated ids"; \
		echo ""; \
		echo "INSTRUMENTATION_RUNS_DIR=../runtime/runs"; \
		echo "# Root folder for instrumentation outputs"; \
		echo ""; \
		echo "INSTRUMENTATION_PROMPT_TOL_ABS_TOKENS=25"; \
		echo "# Absolute prompt token tolerance for accounting validation"; \
		echo ""; \
		echo "INSTRUMENTATION_PROMPT_TOL_PCT=0.02"; \
		echo "# Relative prompt token tolerance (fraction)"; \
		echo ""; \
		echo "# === Streaming Chat ==="; \
		echo "STREAMING_ENABLED=true"; \
		echo "# Enable streaming chat endpoint"; \
		echo ""; \
		echo "TAGGER_CURRENT_RESPONSE_MIDDLE_CUT_PERCENT=50"; \
		echo "# Tagger prompt optimization: percent removed from center of current assistant text (range: 10-90, int)"; \
		echo ""; \
		echo "TAGGER_PREVIOUS_RESPONSE_MIDDLE_CUT_PERCENT=75"; \
		echo "# Tagger prompt optimization: percent removed from center of previous assistant text (range: 10-90, int)"; \
		echo ""; \
		echo "TAGGER_MIN_RESPONSE_LENGTH_FOR_CHOP=600"; \
		echo "# Tagger prompt optimization: apply chopping only when assistant text length is greater than this value"; \
		echo ""; \
		echo "# === Response Pruning ==="; \
		echo "RESPONSE_PRUNING_RULES_PATH=backend/app/config/rules.json"; \
		echo "# JSON rule file for deterministic response pruning"; \
		echo ""; \
		echo "RESPONSE_PRUNING_MAX_FRONT_UNITS=3"; \
		echo "# Max leading sentence units removed by response pruning"; \
		echo ""; \
		echo "RESPONSE_PRUNING_SIMILARITY_THRESHOLD=90"; \
		echo "# Similarity threshold for duplicate-sentence response pruning (0-100)"; \
		echo ""; \
		echo "RESPONSE_PRUNING_WHITESPACE_MODE=compact_prose"; \
		echo "# Response-pruning whitespace mode: off|compact_prose|preserve_code"; \
		echo ""; \
		echo "RESPONSE_PRUNING_ENABLED=true"; \
		echo "# Enable deterministic response pruning"; \
		echo ""; \
		echo "RESPONSE_PRUNING_FRONT_ENABLED=true"; \
		echo "# Enable response-pruning front sentence trimming"; \
		echo ""; \
		echo "RESPONSE_PRUNING_END_ENABLED=true"; \
		echo "# Enable response-pruning trailing paragraph trimming"; \
		echo ""; \
		echo "RESPONSE_PRUNING_MARKDOWN_ENABLED=false"; \
		echo "# Enable response-pruning markdown cleanup"; \
		echo ""; \
		echo "RESPONSE_PRUNING_WHITESPACE_ENABLED=true"; \
		echo "# Enable response-pruning whitespace cleanup"; \
		echo ""; \
		echo "RESPONSE_PRUNING_SIMILARITY_ENABLED=true"; \
		echo "# Enable response-pruning duplicate-sentence similarity scan"; \
		echo ""; \
		echo "# === Dream Pipeline ==="; \
		echo "ENABLE_DREAM=true"; \
		echo "# Enable Dream orchestrator"; \
		echo ""; \
		echo "AUTO_ACCEPT_DREAMS=true"; \
		echo "# Automatically persist all pending dream.json items during sleep"; \
		echo ""; \
		echo "DREAM_MODEL=gpt-5.5"; \
		echo "DREAM_TEMPERATURE=1.0"; \
		echo "DREAM_MAX_TOKENS=32000"; \
		echo "DREAM_ENABLE_REMOTE_RESEARCH=true"; \
		echo "DREAM_REMOTE_CONTEXT_MAX_TOKENS=32000"; \
		echo "# Dream agent configuration"; \
		echo ""; \
		echo "# === Debug / Observability ==="; \
		echo "GENERATE_DEBUG_FILES=true"; \
		echo "# Enable debug file generation (e.g., debug_context.txt)"; \
		echo ""; \
		echo "VITE_SHOW_DEBUG_VALUES=false"; \
		echo "# Frontend: show stats/debug values bar in chat UI"; \
		echo ""; \
	} > .env
	@echo "✅ Created .env with defaults (update OPENAI_API_KEY)"

unlock-sleep:
	@rm -f runtime/state/sleep.lock 2>/dev/null || true
	@echo "✅ Sleep lock cleared (if it existed)"

# Docker: create host directories for bind mounts (run before first docker-compose up)
docker-data-dirs:
	@echo "📁 Creating host directories for Docker bind mounts..."
	@mkdir -p data/memory data/db data/hf-cache runtime/logs runtime/runs runtime/state
	@echo "✅ Created data/memory data/db data/hf-cache runtime/logs runtime/runs runtime/state"

# Docker: set permissions so container process can read/write (container typically runs as root)
docker-data-permissions:
	@chmod -R 755 data runtime 2>/dev/null || true
	@echo "✅ Set permissions on data/ and runtime/ (755)"

# Docker: full host prep for first run (dirs + permissions)
docker-setup: docker-data-dirs docker-data-permissions
	@echo "✅ Docker host setup complete. Run: docker-compose up -d"

# Docker: prepare host and start containers
run-docker: docker-setup
	@echo "🚀 Starting Docker stack..."
	@docker compose up -d
	@echo "✅ Docker stack is running"

# Docker: clean restart of compose stack
restart-docker: docker-setup
	@echo "🔁 Restarting Docker stack..."
	@docker compose down --remove-orphans
	@docker compose up -d
	@echo "✅ Docker stack restarted"

# Docker: stop and remove compose stack
stop-docker:
	@echo "🛑 Stopping Docker stack..."
	@docker compose down --remove-orphans
	@echo "✅ Docker stack stopped"

# Docker: pull latest code, rebuild image, and restart (for frequent code deploys)
docker-rebuild:
	@echo "📥 Pulling latest code..."
	@git pull
	@echo "🔨 Rebuilding and starting containers..."
	@docker compose up -d --build
	@echo "✅ docker-rebuild complete"

# Full setup from scratch
setup: setup-env install build
	@echo "🎉 Syx setup completed!"
	@echo "   Next steps:"
	@echo "   1. Edit .env file with your OpenAI API key"
	@echo "   2. Run 'make run' to start the server"

# Generate architecture docs (PNG) from diagrams script
generate-docs:
	@echo "🖼  Generating architecture diagram..."
	@# Run from repo root so output path in script (docs/...) resolves correctly
	@( \
		if [ -x venv/bin/python ]; then \
			venv/bin/python docs/architecture_diagram.py; \
		else \
			python docs/architecture_diagram.py; \
		fi \
	) && \
	( [ -f docs/syx_architecture.png ] && echo "✅ Diagram updated at docs/syx_architecture.png" || (echo "❌ Failed to generate docs/syx_architecture.png" && exit 1) )
