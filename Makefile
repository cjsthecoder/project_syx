# Morpheus AGI Chatbot Framework - Build Automation
# Make targets for development and deployment

.PHONY: help install build run clean test lint format generate-docs

# Resolve Python interpreter once (prefer local venv, then system python/python3)
PYTHON := $(shell if [ -x venv/bin/python ]; then printf "%s" "$(CURDIR)/venv/bin/python"; else command -v python || command -v python3; fi)

# Default target
help:
	@echo "Morpheus AGI Chatbot Framework - Available Commands:"
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
	@echo "  make lint                 - Lint all code"
	@echo "  make lint-backend         - Lint Python code"
	@echo "  make lint-frontend        - Lint TypeScript/React code"
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
		PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 venv/bin/python -m pip install -r backend/requirements.txt'
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
	@echo "🚀 Starting Morpheus server..."
	@echo "   Frontend: http://localhost:8000"
	@echo "   API Docs: http://localhost:8000/docs"
	@echo "   Health:   http://localhost:8000/health"
	@echo ""
	@if [ -z "$$VIRTUAL_ENV" ]; then \
		if [ ! -d venv ]; then \
			echo "🐍 Creating Python virtual environment at ./venv"; \
			python3 -m venv venv; \
			echo "📦 Installing backend requirements into ./venv"; \
			. venv/bin/activate && pip install -r backend/requirements.txt; \
		else \
			echo "ℹ️  Using existing ./venv"; \
		fi; \
		echo "✅ Virtual environment ready"; \
		venv/bin/python -c "import fastapi" 2>/dev/null || (echo "📦 Installing backend requirements into ./venv" && venv/bin/python -m pip install -r backend/requirements.txt); \
		cd backend && ../venv/bin/python -m app.main; \
	else \
		python -c "import fastapi" 2>/dev/null || (echo "📦 Installing backend requirements into active venv" && python -m pip install -r backend/requirements.txt); \
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
	@echo "   - Removing memory/*"
	@echo "   - Removing backend/app/data/morpheus.db"
	@echo "   - Recreating empty DB (alembic upgrade)"
	@echo ""
	@read -p "Type 'YES' to proceed: " CONFIRM; \
	if [ "$$CONFIRM" != "YES" ]; then echo "Aborted."; exit 1; fi; \
	echo "Deleting memory/* ..."; \
	rm -rf memory/* 2>/dev/null || true; \
	rm -rf backend/memory/* 2>/dev/null || true; \
	echo "Deleting SQLite DB ..."; \
	rm -f backend/app/data/morpheus.db 2>/dev/null || true; \
	echo "Removing runtime sleep lock if present ..."; \
	rm -f backend/runtime/sleep.lock 2>/dev/null || true; \
	echo "Deleting logs ..."; \
	rm -f backend/logs/*.log 2>/dev/null || true; \
	echo "Recreating DB schema ..."; \
	mkdir -p backend/app/data; \
	cd backend && alembic upgrade head; \
	echo "✅ HARD RESET complete. Start the server and Continuum will be reseeded."

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
	cd backend && $(PYTHON) -m pytest tests/ -v
	@echo "✅ Backend tests completed"

test-frontend:
	@echo "🧪 Running frontend tests..."
	cd frontend && npm test -- --run
	@echo "✅ Frontend tests completed"

# Run linting
lint: lint-backend lint-frontend
	@echo "✅ Linting completed"

lint-backend:
	@echo "🔍 Linting Python code..."
	cd backend && $(PYTHON) -m flake8 app/ tests/
	@echo "✅ Backend linting completed"

lint-frontend:
	@echo "🔍 Linting TypeScript/React code..."
	cd frontend && npm run lint
	@echo "✅ Frontend linting completed"

# Format code
format: format-backend format-frontend
	@echo "✅ Code formatting completed"

format-backend:
	@echo "🎨 Formatting Python code..."
	cd backend && $(PYTHON) -m black app/ tests/
	@echo "✅ Backend formatting completed"

format-frontend:
	@echo "🎨 Formatting TypeScript/React code..."
	cd frontend && npm run format
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
		echo "# Morpheus AGI Chatbot Framework - Environment Variables"; \
		echo "# Edit values as needed. Comments are placed after each variable to avoid parser conflicts."; \
		echo ""; \
		echo "OPENAI_API_KEY=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"; \
		echo "# OpenAI API key used for chat and embeddings"; \
		echo ""; \
		echo "MODEL_NAME=gpt-5.2"; \
		echo "# Default chat model name"; \
		echo ""; \
		echo "MODEL_TEMPERATURE=1.0"; \
		echo "# Sampling temperature (0.0–2.0)"; \
		echo ""; \
		echo "MODEL_MAX_TOKENS=128000"; \
		echo "# Max tokens in a single model response"; \
		echo ""; \
		echo "HOST=0.0.0.0"; \
		echo "# Server host interface"; \
		echo ""; \
		echo "PORT=8000"; \
		echo "# Server port"; \
		echo ""; \
		echo "RELOAD=true"; \
		echo "# Enable auto-reload in development"; \
		echo ""; \
		echo "LOG_LEVEL=INFO"; \
		echo "# Log level (DEBUG, INFO, WARNING, ERROR)"; \
		echo ""; \
		echo "LOG_FORMAT=json"; \
		echo "# Log format: json or text"; \
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
		echo "NAMESPACE_BOOST=1.20"; \
		echo "# V2.5: Multiplicative boost for namespace match"; \
		echo ""; \
		echo "LOG_PREVIEW_MAX_CHARS=1024"; \
		echo "# Max chars for log previews"; \
		echo ""; \
		echo "CORS_ORIGINS=[\"http://localhost:3000\",\"http://localhost:5173\"]"; \
		echo "# Allowed browser origins for API"; \
		echo ""; \
		echo "DB_PATH=app/data/morpheus.db"; \
		echo "# SQLite database file path (or full URL like sqlite:///...)"; \
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
		echo "EMBEDDING_MODEL=text-embedding-3-large"; \
		echo "# Embedding model for document indexing"; \
		echo ""; \
		echo "CHUNK_SIZE=800"; \
		echo "# Text chunk size used during embedding"; \
		echo ""; \
		echo "CHUNK_OVERLAP=100"; \
		echo "# Overlap between chunks during embedding"; \
		echo ""; \
		echo "AVAILABLE_MODELS=[\"gpt-5.2\",\"gpt-5.1\",\"gpt-5.1-mini\",\"gpt-5.1-nano\",\"gpt-5\",\"gpt-5-mini\",\"gpt-5-nano\",\"gpt-4o\",\"gpt-4o-mini\",\"gpt-4.1\",\"gpt-4.1-mini\",\"gpt-4.1-nano\"]"; \
		echo "# Whitelisted chat models for the UI selector"; \
		echo ""; \
		echo "RAG_ON_CHAT=true"; \
		echo "# If true, inject retrieved context into chat when index exists"; \
		echo ""; \
		echo "RAG_TOP_K=10"; \
		echo "# Number of top snippets to retrieve"; \
		echo ""; \
		echo "RAG_SNIPPET_MAX_TOKENS=500"; \
		echo "# Max tokens per RAG snippet"; \
		echo ""; \
		echo "RAG_CONTEXT_MAX_TOKENS=10000"; \
		echo "# Max total tokens for injected context block"; \
		echo ""; \
		echo "RAG_SCORE_THRESHOLD=0.5"; \
		echo "# Cosine similarity threshold (0..1) to include snippet"; \
		echo ""; \
		echo "CHAT_HISTORY_LIMIT_PAIRS=3"; \
		echo "# V2.3: Number of prompt/response pairs kept in working memory:: 10 is working well"; \
		echo ""; \
		echo "DAILY_RAG_ENABLED=true"; \
		echo "# V2.3: Global default toggle; per-project override via UI"; \
		echo ""; \
		echo "DAILY_RAG_K=9"; \
		echo "# V2.3: Top-K results from daily index"; \
		echo ""; \
		echo "DAILY_RAG_SCORE_THRESHOLD=0.40"; \
		echo "# V2.3: Similarity threshold for daily results"; \
		echo ""; \
		echo "DAILY_RAG_MAX_TOKENS=3000"; \
		echo "# V2.3: Max tokens contributed by daily layer"; \
		echo ""; \
		echo "DAILY_RAG_WEIGHT=1.2"; \
		echo "# V2.3: Weight multiplier for daily scores before merging"; \
		echo ""; \
		echo "DEDUPE_EXACT=true"; \
		echo "# V2.3: Remove exact-text duplicates across daily/main"; \
		echo ""; \
		echo "DEDUPE_NEAR=true"; \
		echo "# V2.3: Remove near-duplicates by similarity"; \
		echo ""; \
		echo "DEDUPE_SIMILARITY_THRESHOLD=0.98"; \
		echo "# V2.3: Cosine threshold for near-duplicate detection"; \
		echo ""; \
		echo "DEDUPE_KEEP_DAILY=true"; \
		echo "# V2.3: Prefer keeping the daily hit on dedupe"; \
		echo ""; \
		echo "BUILDER_MODEL=gpt-4o-mini"; \
		echo "# V2.3.1: LLM for query builder/router"; \
		echo ""; \
		echo "BUILDER_CONFIDENCE_MIN=0.75"; \
		echo "# V2.3.1: Confidence threshold for full retrieval"; \
		echo ""; \
		echo "BUILDER_MAX_TOKENS=512"; \
		echo "# V2.3.1: Max tokens for builder output"; \
		echo ""; \
		echo "BUILDER_CACHE=true"; \
		echo "# V2.3.1: Enable in-memory builder cache"; \
		echo ""; \
		echo "AMBIGUITY_MODEL=gpt-5-nano"; \
		echo "# DELTA-A.2: LLM for roll-off ambiguity detection"; \
		echo ""; \
		echo "TOPIC_BOOST=1.10"; \
		echo "# V2.3.1: Multiplicative boost for topic overlap"; \
		echo ""; \
		echo "DECISION_BOOST=1.05"; \
		echo "# V2.3.1: Multiplicative boost for decision overlap"; \
		echo ""; \
        echo "QUESTION_BOOST=1.02"; \
		echo "# V2.3.1: Multiplicative boost for open-question overlap"; \
		echo ""; \
		echo "CHAT_HISTORY_LIMIT=20"; \
		echo "# Number of recent messages kept per project in working memory"; \
		echo ""; \
		echo "DEFAULT_SYSTEM_PROMPT_PATH=app/config/defaults/system_prompt.txt"; \
		echo "# V2.6: Default system prompt file path (relative to backend/ cwd)"; \
		echo ""; \
		echo "DEFAULT_PERSONALITY_PROMPT_PATH=app/config/defaults/personality.json"; \
		echo "# V2.6: Default personality JSON file path (relative to backend/ cwd)"; \
		echo ""; \
		echo "ENABLE_SCHEDULER=true"; \
		echo "# V3.1: Enable daily sleep scheduler"; \
		echo ""; \
		echo "SLEEP_CYCLE_HOUR=15"; \
		echo "# V3.1: Local hour of day (0-23) to run sleep cycle"; \
		echo ""; \
		echo "SLEEP_CYCLE_MINUTE=17"; \
		echo "# V3.1: Local minute of day (0-59) to run sleep cycle"; \
		echo ""; \
		echo "VERIFY_RAG=true"; \
		echo "# V3.3: Enable post-rebuild verification"; \
		echo ""; \
		echo "STREAMING_ENABLED=true"; \
		echo "# V3.5: Enable streaming chat endpoint"; \
		echo ""; \
		echo "STREAM_FLUSH_MS=50"; \
		echo "# V3.5: Flush cadence for streaming chunks (ms)"; \
		echo ""; \
		echo "STREAM_TIMEOUT_MS=60000"; \
		echo "# V3.5: Overall stream timeout (ms)"; \
		echo ""; \
		echo "ENABLE_DREAM=true"; \
		echo "# V4.1: Enable Dream orchestrator"; \
		echo ""; \
		echo "MAX_WORKERS=1"; \
		echo "# V4.1: Dream executor workers"; \
		echo ""; \
		echo "DREAM_MODEL=gpt-5.2"; \
		echo "DREAM_TEMPERATURE=1.0"; \
		echo "DREAM_MAX_TOKENS=32000"; \
		echo "DREAM_ENABLE_REMOTE_RESEARCH=true"; \
		echo "DREAM_REMOTE_CONTEXT_MAX_TOKENS=32000"; \
		echo "DREAM_TOPIC_BOOST=1.5"; \
		echo "# V4.1.2: Dream agent configuration"; \
		echo ""; \
		echo "GENERATE_DEBUG_FILES=true"; \
		echo "# V4.1.3.1: Enable debug file generation (e.g., debug_context.txt)"; \
		echo ""; \
	} > .env
	@echo "✅ Created .env with defaults (update OPENAI_API_KEY)"

unlock-sleep:
	@rm -f backend/runtime/sleep.lock backend/app/runtime/sleep.lock 2>/dev/null || true
	@echo "✅ Sleep lock cleared (if it existed)"

# Full setup from scratch
setup: setup-env install build
	@echo "🎉 Morpheus setup completed!"
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
	( [ -f docs/morpheus_architecture.png ] && echo "✅ Diagram updated at docs/morpheus_architecture.png" || (echo "❌ Failed to generate docs/morpheus_architecture.png" && exit 1) )
