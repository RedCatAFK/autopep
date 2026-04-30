# Julia

Julia is the vertical-slice app for chat-driven protein-design runs.

## App deployment

Deploy the web app from the `/julia` directory as the Vercel project root.

Required Vercel env groups:

- Auth: `BETTER_AUTH_SECRET`, `BETTER_AUTH_URL`
- Database: `DATABASE_URL`
- Worker callback: `JULIA_WORKER_START_URL`, `JULIA_WORKER_WEBHOOK_SECRET`
- R2 artifacts: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL`
- Model/runtime: `OPENAI_API_KEY`, `OPENAI_DEFAULT_MODEL`
- Tool endpoints as enabled: `MODAL_CHAI_URL`, `MODAL_PROTEINA_URL`, scorer URLs, and their API keys

Run a local check before deploy:

```bash
SKIP_ENV_VALIDATION=1 bun run check
```

## Worker deployment

The Python worker lives in `/julia/worker` and exposes a Modal FastAPI app named
`julia-agent-worker` from `modal_app.py`.

Start with dry-run mode:

```bash
cd julia/worker
uv run pytest
modal deploy modal_app.py
```

Keep `JULIA_WORKER_DRY_RUN=1` for the first deployment so `/runs/start` writes
ordered events and a dry-run artifact without calling the live SandboxAgent path.

Live runs are guarded separately. The worker returns a clear 501 response unless:

```bash
JULIA_WORKER_ALLOW_LIVE_RUNS=1
```

Required Modal worker env:

- `DATABASE_URL`
- `JULIA_WORKER_WEBHOOK_SECRET`
- `OPENAI_API_KEY`
- `OPENAI_DEFAULT_MODEL`
- R2 env when artifact upload is enabled: `R2_BUCKET`, `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_REGION`, `R2_PUBLIC_BASE_URL`
- Autopep2/tool env as needed: `AUTOPEP2_SESSION_ID`, `AUTOPEP2_MAX_TOOL_TIMEOUT`, endpoint URLs, and API keys

The live runner uses the OpenAI Agents SDK sandbox imports lazily. If the installed
SDK does not provide `agents.sandbox` and `agents.extensions.sandbox`, the worker
will fail the live path with an explicit Modal sandbox extension error while dry
runs and unit tests remain importable.
