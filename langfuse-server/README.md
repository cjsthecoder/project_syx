## Langfuse (Local)

Requirements
- Docker Desktop (macOS supported)
- Ports:
  - UI: http://localhost:3000
  - Postgres: internal-only (5432)

Notes
- Uses Langfuse v2 (Postgres-only) for local development.

Setup
1) Generate secrets (optional if already set):
   - `make langfuse-secrets`
   - Put values into `langfuse-server/.env`:
     - `NEXTAUTH_SECRET` (base64, e.g. from command output)
     - `SALT` (64 hex chars)
     - `ENCRYPTION_KEY` (64 hex chars)
2) Start:
   - `make langfuse-up`
3) First login:
   - Open http://localhost:3000
   - Sign up with:
     - Email: `morpheus@shuler.email`
     - Password: `changeme`
   - (Recommended) After creating the admin, set `DISABLE_SIGNUP=true` in `docker-compose.yml` and run `make langfuse-up` again.

Commands
- Start: `make langfuse-up`
- Stop:  `make langfuse-down`
- Logs:  `make langfuse-logs`

Troubleshooting
- If the dashboard shows an Internal Server Error for charts, create lightweight Postgres views:
  - `observations_view` selecting the needed columns from `observations`
  - `traces_view` selecting the needed columns from `traces`


