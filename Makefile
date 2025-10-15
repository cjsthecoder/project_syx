# Morpheus AGI Chatbot Framework - Build Automation
# Make targets for development and deployment

.PHONY: help install build run clean test lint format

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
		echo "OPENAI_API_KEY=***REMOVED***"; \
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
		echo "RAG_CONTEXT_MAX_TOKENS=5000"; \
		echo "# Max total tokens for injected context block"; \
		echo ""; \
		echo "RAG_SCORE_THRESHOLD=0.5"; \
		echo "# Cosine similarity threshold (0..1) to include snippet"; \
		echo ""; \
		echo "CHAT_HISTORY_LIMIT=20"; \
		echo "# Number of recent messages kept per project in working memory"; \
	} > .env; \
	echo "✅ Created .env with defaults (update OPENAI_API_KEY)"

# Full setup from scratch
setup: setup-env install build
	@echo "🎉 Morpheus setup completed!"
	@echo "   Next steps:"
	@echo "   1. Edit .env file with your OpenAI API key"
	@echo "   2. Run 'make run' to start the server"
