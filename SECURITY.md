# Security Policy

## Supported Scope

Syx is currently intended for local development and trusted deployments only.

Do not expose Syx directly to the public internet or to untrusted users. The project does not currently provide a hardened multi-tenant security model, user authentication, role-based authorization, or a production-ready public internet deployment profile.

## Reporting a Vulnerability

Please do not publish suspected vulnerabilities publicly before maintainers have had a reasonable chance to investigate.

If GitHub private vulnerability reporting is enabled for this repository, use that channel first. If it is not available, open a GitHub issue with a minimal description such as "Security report contact request" and do not include exploit details, secrets, private memory, logs, or proof-of-concept payloads in the public issue.

When reporting, include:

- Affected Syx version or commit.
- The component involved, such as backend API, agent memory interface, file upload, Docker deployment, or frontend.
- A concise description of the impact.
- Reproduction steps that avoid exposing real secrets or private project data.
- Any suggested mitigation, if known.

## Secrets and Credentials

Never commit real secrets to the repository.

Do not commit:

- `.env` files.
- OpenAI or other provider API keys.
- Database credentials.
- Agent tokens intended for private use.
- Private project data or memory artifacts.
- Runtime logs or debug files containing prompts, responses, retrieved context, or uploads.

Use `.env.example` and `make setup-env` as templates only. After generating `.env`, set your own provider API key locally.

If a secret is accidentally committed, rotate it immediately. Removing it from a later commit is not enough, because it may remain in Git history.

## Local Data and Memory Privacy

Syx stores project data, memory artifacts, debug files, logs, and runtime outputs on disk. Treat these files as potentially sensitive.

Common local/generated paths include:

- `data/memory/`
- `data/db/`
- `runtime/logs/`
- `runtime/runs/`
- `runtime/state/`
- backend coverage/build artifacts

These files may contain user prompts, assistant responses, uploaded document text, retrieved RAG context, model outputs, or project-specific metadata. Do not include them in bug reports or pull requests unless they are intentionally sanitized examples.

## Agent Memory Interface

The local agent memory search endpoint includes an `agent_token` field in its request contract. This field exists so the current interface matches the future secured interface.

At the moment, token authorization is a local-development stub. The authorization boundary exists in `backend/app/security/agent_tokens.py`, but the current implementation authorizes requests rather than enforcing a real secret or project-level access policy.

Do not treat the default `local-token` or `SYX_AGENT_TOKEN` value as production security.

The agent memory search endpoint is designed to be read-only, but it can return project memory. Only run it in trusted local environments unless you have added your own authentication, network restrictions, and access controls.

## File Uploads

Uploaded files are stored and indexed for retrieval. Only upload files you are allowed to process and store locally.

For untrusted files or untrusted users, add your own operational controls before deployment, including file-type restrictions, storage quotas, malware scanning, authentication, and network isolation as appropriate.

## Network and Model Providers

Syx can call external model or embedding providers depending on configuration. Any content sent to those providers is subject to the provider's terms, retention policies, and security practices.

Review your configured provider before using Syx with private or regulated data.

## Deployment Guidance

For local development:

- Bind to localhost when possible.
- Keep `.env` private.
- Use trusted project data.
- Keep generated `data/` and `runtime/` paths out of Git.

For shared or production-like deployments:

- Put Syx behind HTTPS.
- Add authentication and authorization at the network or application boundary.
- Restrict access to trusted users.
- Protect mounted data volumes and backups.
- Review logs and debug settings before enabling them.
- Disable or secure agent-facing interfaces unless explicitly needed.

## Dependency and Supply Chain Hygiene

Keep dependencies current through normal maintenance, and review new dependencies before adding them. New dependencies should have a clear purpose and should not be added casually.

Before opening a pull request, run the local quality gate when practical:

```bash
make ci
```

## Security Status Summary

Current public-release assumptions:

- Local/trusted deployment is the supported security posture.
- General user authentication is not implemented.
- Multi-tenant authorization is not implemented.
- Agent-token validation is present as a boundary but currently stubbed.
- Generated memory, logs, uploads, debug files, and run artifacts may contain sensitive content.
