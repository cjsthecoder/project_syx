.PHONY: langfuse-up langfuse-down langfuse-logs langfuse-secrets langfuse-fix-views langfuse-restart

langfuse-build:
	@if [ ! -d "langfuse-source" ]; then \
		echo "📦 Cloning Langfuse source..."; \
		git clone https://github.com/langfuse/langfuse.git langfuse-source; \
	fi
	@cd langfuse-source && git fetch --tags && git checkout main
	@if [ -d ".env.build" ]; then \
		echo "⚠️  .env.build is a directory — fixing it..."; \
		rm -rf .env.build; \
	fi
	@if [ ! -f ".env.build" ]; then \
		echo "🧩 Creating default .env.build for build-time variables..."; \
		cat > .env.build <<'EOF' ;\
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/langfuse ;\
NEXTAUTH_SECRET=dummysecret ;\
NEXTAUTH_URL=http://localhost:3000 ;\
SALT=dummysalt ;\
CLICKHOUSE_URL=clickhouse://langfuse:langfuse@clickhouse:9000/langfuse ;\
CLICKHOUSE_USER=langfuse ;\
CLICKHOUSE_PASSWORD=langfuse ;\
LANGFUSE_S3_EVENT_UPLOAD_BUCKET=dummy-bucket ;\
LANGFUSE_S3_EVENT_UPLOAD_REGION=us-east-1 ;\
LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID=dummy-access-key ;\
LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY=dummy-secret-key ;\
LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT=http://localhost:9000 ;\
LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE=true ;\
SENTRY_SUPPRESS_GLOBAL_ERROR_HANDLER_FILE_WARNING=1 ;\
NEXT_BUILD_SKIP_TYPE_CHECK=1 ;\
EOF ;\
	fi
	@echo "🏗️  Building Langfuse locally in Docker..."
	docker run --rm -it \
		-e COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
		-e NODE_OPTIONS="--max-old-space-size=32768" \
		-e HUSKY=0 \
		-e CI=true \
		-e SENTRY_SUPPRESS_GLOBAL_ERROR_HANDLER_FILE_WARNING=1 \
		-v "$$(pwd)/langfuse-source":/app \
		-v "$$(pwd)/.env.build:/app/.env" \
		-w /app \
		node:20-alpine sh -c "\
			apk add --no-cache git && \
			npm install -g corepack && \
			corepack enable && \
			pnpm install --no-frozen-lockfile && \
			pnpm build && \
			echo '✅ Build complete: package builds created (husky disabled, 32GB heap)'"
	@echo "📁 Copying built artifacts into langfuse-server/dist..."
	mkdir -p langfuse-server/dist
	cp -r langfuse-source/web/.next langfuse-server/dist/web || true
	cp -r langfuse-source/worker/dist langfuse-server/dist/worker || true
	cp -r langfuse-source/ee/dist langfuse-server/dist/ee || true
	cp -r langfuse-source/packages/shared/dist langfuse-server/dist/shared || true
	@echo "✅ Langfuse build artifacts copied to langfuse-server/dist"

langfuse-rebuild:
	@echo "🧹 Cleaning old build artifacts..."
	rm -rf langfuse-server/dist || true
	docker compose -f langfuse-server/docker-compose.yml down || true
	docker system prune -f --volumes || true
	@echo "🏗️  Rebuilding Langfuse..."
	make langfuse-build
	@echo "🚀 Restarting Langfuse stack..."
	make langfuse-up
	@echo "✅ Rebuild complete. Langfuse is live on http://localhost:3000"

langfuse-up:
	docker compose -f langfuse-server/docker-compose.yml up -d

langfuse-down:
	docker compose -f langfuse-server/docker-compose.yml down

langfuse-logs:
	docker compose -f langfuse-server/docker-compose.yml logs -f --tail=200

langfuse-restart:
	@echo "Restarting Langfuse stack (down -> up)..."
	$(MAKE) langfuse-down
	$(MAKE) langfuse-up

# Create/refresh dev views expected by Langfuse UI when running Postgres-only v2
langfuse-fix-views:
	@echo "Creating/refreshing observations_view and traces_view in Postgres..."
	docker compose -f langfuse-server/docker-compose.yml exec postgres psql -U postgres -d langfuse -c "DROP VIEW IF EXISTS observations_view;"
	docker compose -f langfuse-server/docker-compose.yml exec postgres psql -U postgres -d langfuse -c "DROP VIEW IF EXISTS traces_view;"
	docker compose -f langfuse-server/docker-compose.yml exec postgres psql -U postgres -d langfuse -c "CREATE OR REPLACE VIEW observations_view AS SELECT id, start_time, end_time, total_tokens, calculated_total_cost, 0::numeric AS calculated_input_cost, 0::numeric AS calculated_output_cost, type, trace_id, model, project_id, 0::bigint AS prompt_tokens, 0::bigint AS completion_tokens FROM observations;"
	docker compose -f langfuse-server/docker-compose.yml exec postgres psql -U postgres -d langfuse -c "CREATE OR REPLACE VIEW traces_view AS SELECT id, timestamp, 0::numeric AS duration, name, project_id FROM traces;"

langfuse-secrets:
	@echo "NEXTAUTH_SECRET: $$(openssl rand -base64 32)"
	@echo "SALT:            $$(openssl rand -hex 32)"
	@echo "ENCRYPTION_KEY:  $$(openssl rand -hex 32)"
# Morpheus AGI Chatbot Framework - Build Automation
# Make targets for development and deployment

.PHONY: help install build run clean test lint format generate-docs

# Default target
help:
	@echo "Morpheus AGI Chatbot Framework - Available Commands:"
	@echo ""
	@echo "  make install    - Install all dependencies (Python + Node.js)"
	@echo "  make build      - Build React app and copy to FastAPI static folder"
	@echo "  make run        - Start the unified FastAPI server"
	@echo "  make migrate    - Create Alembic revision"
	@echo "  make upgrade    - Apply DB migrations"
	@echo "  make downgrade  - Revert DB migrations"
	@echo "  make clean      - Clean build artifacts and dependencies"
	@echo "  make test       - Run all tests (backend + frontend)"
	@echo "  make lint       - Run linting on all code"
	@echo "  make format     - Format all code"
	@echo ""

# Install all dependencies
install: install-backend install-frontend
	@echo "✅ All dependencies installed successfully"

install-backend:
	@echo "📦 Installing Python dependencies..."
	cd backend && pip install -r requirements.txt
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
		. venv/bin/activate && cd backend && python -m app.main; \
	else \
		cd backend && python -m app.main; \
	fi

# Alembic helpers
migrate:
	cd backend && alembic revision --autogenerate -m "update"

upgrade:
	cd backend && alembic upgrade head

downgrade:
	cd backend && alembic downgrade -1

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
	cd backend && python -m pytest tests/ -v
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
	cd backend && python -m flake8 app/ tests/
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
	cd backend && python -m black app/ tests/
	@echo "✅ Backend formatting completed"

format-frontend:
	@echo "🎨 Formatting TypeScript/React code..."
	cd frontend && npm run format
	@echo "✅ Frontend formatting completed"

# Development helpers
dev-backend:
	@echo "🔧 Starting backend in development mode..."
	cd backend && python -m app.main

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
		echo "MODEL_NAME=gpt-5"; \
		echo "# Default chat model name"; \
		echo ""; \
		echo "MODEL_TEMPERATURE=1.0"; \
		echo "# Sampling temperature (0.0–2.0)"; \
		echo ""; \
		echo "MODEL_MAX_TOKENS=32000"; \
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
		echo "CORS_ORIGINS=[\"http://localhost:3000\",\"http://localhost:5173\"]"; \
		echo "# Allowed browser origins for API"; \
		echo ""; \
		echo "DB_PATH=backend/app/data/morpheus.db"; \
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
		echo "AVAILABLE_MODELS=[\"gpt-5\",\"gpt-5-mini\",\"gpt-5-nano\",\"gpt-4o\",\"gpt-4o-mini\",\"gpt-4.1\",\"gpt-4.1-mini\",\"gpt-4.1-nano\"]"; \
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
		echo "# V2.3: Number of prompt/response pairs kept in working memory"; \
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
		echo "LANGFUSE_ENABLED=True"; \
		echo "# V2.4.2: Enable Langfuse tracing"; \
		echo ""; \
		echo "LANGFUSE_BASE_URL=http://localhost:3000"; \
		echo "# V2.4.1: Langfuse base URL"; \
		echo ""; \
		echo "LANGFUSE_PROJECT_ID=cmhayuox200069rdvsnyfdkh7"; \
		echo "# V2.4.2: Langfuse Project ID"; \
		echo ""; \
		echo "LANGFUSE_PUBLIC_KEY=pk-lf-424c82e2-0b37-4b02-9eae-53e8648a03b6"; \
		echo "# V2.4.2: Langfuse Public key"; \
		echo ""; \
		echo "LANGFUSE_SECRET_KEY=sk-lf-f72e1b14-0972-4c31-9eb3-845fae333a6a"; \
		echo "# V2.4.2: Langfuse Secret key"; \
		echo ""; \
		echo "LANGFUSE_SAMPLE_RATE=1.0"; \
		echo "# V2.4.2: Trace sampling rate (0..1)"; \
		echo ""; \
		echo "LANGFUSE_LOG_LEVEL=INFO"; \
		echo "# V2.4.2: SDK log level"; \
	} > .env; \
	echo "✅ Created .env with defaults (update OPENAI_API_KEY)"

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
