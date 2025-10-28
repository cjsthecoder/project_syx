## Langfuse (Local)

Requirements
- Docker Desktop (macOS supported)
- Ports:
  - UI: http://localhost:3000
  - Postgres: internal-only (5432)

Setup
1) Generate secrets (optional if already set):
   - `make langfuse-secrets`
   - Put values into `langfuse-server/.env` (NEXTAUTH_SECRET, ENCRYPTION_KEY)
2) Start:
   - `make langfuse-up`
3) First login:
   - Open http://localhost:3000
   - Sign up with:
     - Email: `morpheus@shuler.email`
     - Password: `changeme`
   - (Optional) After creating the admin, set `DISABLE_SIGNUP=true` in `docker-compose.yml` and run `make langfuse-up` again.

Commands
- Start: `make langfuse-up`
- Stop:  `make langfuse-down`
- Logs:  `make langfuse-logs`


