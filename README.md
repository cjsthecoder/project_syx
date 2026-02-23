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
- RAG_ON_CHAT, BASE_TOP_K, RETRIEVAL_MULTIPLIER, RAG_SCORE_THRESHOLD, DAILY_RAG_SCORE_THRESHOLD, DAILY_RAG_WEIGHT
- AVAILABLE_MODELS (optional JSON array)

## Docker (Ubuntu, Python 3.13.3)

Run Morpheus in a container with bind-mounted data and a mounted `.env` (no secrets in the image).

1. **Create host directories** for persistence (run once):
   ```bash
   make docker-data-dirs
   ```
   Optionally set permissions: `make docker-data-permissions`, or run the full prep: `make docker-setup`.

2. **Ensure `.env` exists** at repo root with at least `OPENAI_API_KEY` and any other settings (see Key environment variables above). The container mounts this file at `/app/.env` read-only.

3. **Build and run**:
   ```bash
   docker-compose up -d
   ```
   App: http://localhost:8000 — API docs: http://localhost:8000/api/docs — Health: http://localhost:8000/health.

4. **Bind mounts**: Data is stored on the host under `./data/memory`, `./data/db`, and `./data/logs`, so it survives container rebuilds and is easy to back up. If you use a different host or port, set `CORS_ORIGINS` in `.env` to include that origin.

# Organization Verification Required for Streaming

Some OpenAI models require your organization to be verified before streaming responses is allowed.

## Why Verification Is Needed

Certain models (including newer GPT-5 series models) will return errors if streaming is requested before the organization is verified. This typically appears as:

```
Your organization must be verified to stream this model.
```

## Verification Steps

1. Sign in to your OpenAI account.
2. Navigate to **Settings → Organization → General**.
3. Click **Verify Organization**.
4. Submit a valid government-issued ID and a portrait photo.
5. Verification usually completes within about 30 minutes.

## Notes

* If verification is pending, you can temporarily disable streaming (`STREAMING_ENABLED=false`) or use a model that does not require verification.
* Verification is required even when using these models through external platforms such as Azure.


Refer to `docs/REQUIREMENTS.md` for full details.
