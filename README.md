# Morpheus

## Project Overview
Morpheus is a modular system that provides a web-based chat interface backed by a FastAPI server and LangChain for LLM integration.  

## Setup (Python venv)
Use a local virtual environment to isolate Python dependencies.

```bash
# 1) Create venv (one time)
python3 -m venv venv

# 2) Activate it (each new shell)
source venv/bin/activate

# 3) Install backend dependencies
pip install -r backend/requirements.txt

# 4) Install frontend dependencies (optional here; `make install` also does this)
cd frontend && npm install && cd ..

# 5) Build frontend and run the app
make build
make run
```

Notes:
- If you forget to activate your venv, `make run` will auto-create and use `./venv` for you.
- You can also run a full setup via: `make setup`.

## Logging level
Set log level via the `LOG_LEVEL` environment variable (e.g., DEBUG, INFO):

```bash
export LOG_LEVEL=DEBUG
```

Or add it to your `.env` file alongside other settings (see `.env.example`).

## Key environment variables
- OPENAI_API_KEY
- MODEL_NAME (default gpt-5)
- MODEL_TEMPERATURE (default 1.0)
- MODEL_MAX_TOKENS (default 32000)
- LOG_LEVEL (default INFO)
- LOG_FORMAT (json or text)
- DB_PATH
- MAX_UPLOAD_MB, MAX_BATCH_MB, STORAGE_LIMIT_MB
- EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP
- RAG_ON_CHAT, RAG_TOP_K, RAG_SNIPPET_MAX_TOKENS, RAG_CONTEXT_MAX_TOKENS, RAG_SCORE_THRESHOLD
- AVAILABLE_MODELS (optional JSON array)

Refer to `docs/REQUIREMENTS.md` for full details.
