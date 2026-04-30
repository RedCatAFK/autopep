# Create T3 App

This is a [T3 Stack](https://create.t3.gg/) project bootstrapped with `create-t3-app`.

## What's next? How do I make an app with this?

We try to keep this project as simple as possible, so you can start with just the scaffolding we set up for you, and add additional things later when they become necessary.

If you are not familiar with the different technologies used in this project, please refer to the respective docs. If you still are in the wind, please join our [Discord](https://t3.gg/discord) and ask for help.

- [Next.js](https://nextjs.org)
- [NextAuth.js](https://next-auth.js.org)
- [Prisma](https://prisma.io)
- [Drizzle](https://orm.drizzle.team)
- [Tailwind CSS](https://tailwindcss.com)
- [tRPC](https://trpc.io)

## Learn More

To learn more about the [T3 Stack](https://create.t3.gg/), take a look at the following resources:

- [Documentation](https://create.t3.gg/)
- [Learn the T3 Stack](https://create.t3.gg/en/faq#what-learning-resources-are-currently-available) — Check out these awesome tutorials

You can check out the [create-t3-app GitHub repository](https://github.com/t3-oss/create-t3-app) — your feedback and contributions are welcome!

## How do I deploy this?

Follow our deployment guides for [Vercel](https://create.t3.gg/en/deployment/vercel), [Netlify](https://create.t3.gg/en/deployment/netlify) and [Docker](https://create.t3.gg/en/deployment/docker) for more information.

## Agent Smoke Roundtrip

After the controller applies DB migrations and deploys the Modal worker, enable smoke runs in the worker environment with `AUTOPEP_ALLOW_SMOKE_RUNS=1`. Then run one or more roundtrips from a shell with production `DATABASE_URL` and Modal launch env configured:

```sh
bun run scripts/smoke-roundtrip.ts smoke_chat
bun run scripts/smoke-roundtrip.ts smoke_tool
bun run scripts/smoke-roundtrip.ts smoke_sandbox
bun run scripts/smoke-roundtrip.ts branch_design
```

The three `smoke_*` modes use `gpt-5.4-mini` and only verify launch, streaming, tool, sandbox, Neon, and event plumbing. `branch_design` seeds the one-loop 3CL-protease demo recipe, calls the deployed Proteina, Chai-1, and protein interaction scoring endpoints, and verifies required Neon rows plus R2 object existence. The script creates a Better Auth smoke user, workspace, and thread if `AUTOPEP_SMOKE_OWNER_ID`, `AUTOPEP_SMOKE_WORKSPACE_ID`, and `AUTOPEP_SMOKE_THREAD_ID` are unset. It prints those IDs for reuse, launches through `createMessageRunWithLaunch`, waits for completion, and checks contiguous event sequencing plus required events.

## Cheap CI Evals

The PR-safe orchestration eval is deterministic and does not touch Modal, R2, Neon, or model endpoints:

```sh
bun run test:ci-evals
```

It checks the minimum full-loop trace contract: run lifecycle, ordered tool calls for literature/PDB/generation/folding/scoring, completed tool pairs, artifact persistence events, candidate ranking events, and a final assistant response after scoring. The same evaluator can later be pointed at real `agent_events` rows for deployed canaries.

## Nightly Live Science Canaries

The deployed-stack canary suite creates real Modal-backed agent runs for a fixed target set, then checks the persisted Neon trace, artifacts, candidates, model inferences, score rows, latency, and final assistant evidence:

```sh
AUTOPEP_RUNNER_BACKEND=modal \
AUTOPEP_MODAL_START_URL="https://..." \
AUTOPEP_MODAL_WEBHOOK_SECRET="..." \
DATABASE_URL="postgresql://..." \
bun run eval:live-canaries -- --target prod --limit 1
```

Defaults run three bounded targets (`sars-cov-2-3clpro`, `pd-l1`, `ace2`) with `num_candidates=3` prompts. Set `AUTOPEP_LIVE_CANARIES` to a comma-separated subset, `AUTOPEP_LIVE_CANARY_OUTPUT` to write a JSON report, and `AUTOPEP_LIVE_CANARY_CLEANUP=success` to delete passing canary workspaces after evaluation. The GitHub Actions workflow `.github/workflows/live-science-canaries.yml` runs nightly when the canary database and Modal webhook secrets are configured.
