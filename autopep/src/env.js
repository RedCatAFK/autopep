import { createEnv } from "@t3-oss/env-nextjs";
import * as z from "zod";

export const env = createEnv({
	/**
	 * Specify your server-side environment variables schema here. This way you can ensure the app
	 * isn't built with invalid env vars.
	 */
	server: {
		BETTER_AUTH_SECRET:
			process.env.NODE_ENV === "production"
				? z.string()
				: z.string().optional(),
		BETTER_AUTH_URL: z.string().url().optional(),
		AUTOPEP_AGENT_MODE: z.enum(["direct", "codex"]).default("direct"),
		AUTOPEP_ALLOW_SMOKE_RUNS: z.enum(["0", "1"]).optional(),
		AUTOPEP_CODEX_COMMAND: z.string().optional(),
		AUTOPEP_CODEX_MODEL: z.string().default("gpt-5.5"),
		AUTOPEP_LIVE_CANARIES: z.string().optional(),
		AUTOPEP_LIVE_CANARY_ALLOW_FAILED_INFERENCES: z.enum(["0", "1"]).optional(),
		AUTOPEP_LIVE_CANARY_CLEANUP: z
			.enum(["always", "never", "success"])
			.optional(),
		AUTOPEP_LIVE_CANARY_LIMIT: z.string().optional(),
		AUTOPEP_LIVE_CANARY_MAX_TOTAL_MS: z.string().optional(),
		AUTOPEP_LIVE_CANARY_MIN_ARTIFACTS: z.string().optional(),
		AUTOPEP_LIVE_CANARY_MIN_CANDIDATES: z.string().optional(),
		AUTOPEP_LIVE_CANARY_MIN_OK_SCORE_ROWS: z.string().optional(),
		AUTOPEP_LIVE_CANARY_MIN_SCORE_ROWS: z.string().optional(),
		AUTOPEP_LIVE_CANARY_OUTPUT: z.string().optional(),
		AUTOPEP_LIVE_CANARY_OWNER_ID: z.string().optional(),
		AUTOPEP_LIVE_CANARY_POLL_INTERVAL_MS: z.string().optional(),
		AUTOPEP_LIVE_CANARY_REQUIRE_CITATION: z.enum(["0", "1"]).optional(),
		AUTOPEP_LIVE_CANARY_REQUIRE_EXPECTED_PDB: z.enum(["0", "1"]).optional(),
		AUTOPEP_LIVE_CANARY_TIMEOUT_MS: z.string().optional(),
		AUTOPEP_MODAL_RUN_STREAM_URL: z.string().url().optional(),
		AUTOPEP_MODAL_START_URL: z.string().url().optional(),
		AUTOPEP_MODAL_WEBHOOK_SECRET: z.string().optional(),
		AUTOPEP_NEXT_PUBLIC_URL: z.string().url().optional(),
		AUTOPEP_RUNNER_BACKEND: z.enum(["local", "modal"]).default("local"),
		AUTOPEP_SMOKE_OWNER_ID: z.string().optional(),
		AUTOPEP_SMOKE_THREAD_ID: z.string().uuid().optional(),
		AUTOPEP_SMOKE_WORKSPACE_ID: z.string().uuid().optional(),
		AUTOPEP_WORKER_ID: z.string().optional(),
		DATABASE_URL: z.string().url(),
		MODAL_CHAI_API_KEY: z.string().optional(),
		MODAL_CHAI_URL: z.string().url().optional(),
		MODAL_PROTEIN_INTERACTION_SCORING_API_KEY: z.string().optional(),
		MODAL_PROTEIN_INTERACTION_SCORING_URL: z.string().url().optional(),
		MODAL_PROTEINA_API_KEY: z.string().optional(),
		MODAL_PROTEINA_URL: z.string().url().optional(),
		MODAL_TOKEN_ID: z.string().optional(),
		MODAL_TOKEN_SECRET: z.string().optional(),
		NODE_ENV: z
			.enum(["development", "test", "production"])
			.default("development"),
		OPENAI_API_KEY: z.string().optional(),
		OPENAI_DEFAULT_MODEL: z.string().default("gpt-5.5"),
		R2_ACCESS_KEY_ID:
			process.env.NODE_ENV === "production"
				? z.string()
				: z.string().default("local-access-key"),
		R2_ACCOUNT_ID:
			process.env.NODE_ENV === "production"
				? z.string()
				: z.string().default("local-account"),
		R2_BUCKET:
			process.env.NODE_ENV === "production"
				? z.string()
				: z.string().default("autopep-local"),
		R2_PUBLIC_BASE_URL: z.string().url().optional(),
		R2_SECRET_ACCESS_KEY:
			process.env.NODE_ENV === "production"
				? z.string()
				: z.string().default("local-secret-key"),
	},

	/**
	 * Specify your client-side environment variables schema here. This way you can ensure the app
	 * isn't built with invalid env vars. To expose them to the client, prefix them with
	 * `NEXT_PUBLIC_`.
	 */
	client: {
		// NEXT_PUBLIC_CLIENTVAR: z.string(),
	},

	/**
	 * You can't destruct `process.env` as a regular object in the Next.js edge runtimes (e.g.
	 * middlewares) or client-side so we need to destruct manually.
	 */
	runtimeEnv: {
		AUTOPEP_AGENT_MODE: process.env.AUTOPEP_AGENT_MODE,
		AUTOPEP_ALLOW_SMOKE_RUNS: process.env.AUTOPEP_ALLOW_SMOKE_RUNS,
		AUTOPEP_CODEX_COMMAND: process.env.AUTOPEP_CODEX_COMMAND,
		AUTOPEP_CODEX_MODEL: process.env.AUTOPEP_CODEX_MODEL,
		AUTOPEP_LIVE_CANARIES: process.env.AUTOPEP_LIVE_CANARIES,
		AUTOPEP_LIVE_CANARY_ALLOW_FAILED_INFERENCES:
			process.env.AUTOPEP_LIVE_CANARY_ALLOW_FAILED_INFERENCES,
		AUTOPEP_LIVE_CANARY_CLEANUP: process.env.AUTOPEP_LIVE_CANARY_CLEANUP,
		AUTOPEP_LIVE_CANARY_LIMIT: process.env.AUTOPEP_LIVE_CANARY_LIMIT,
		AUTOPEP_LIVE_CANARY_MAX_TOTAL_MS:
			process.env.AUTOPEP_LIVE_CANARY_MAX_TOTAL_MS,
		AUTOPEP_LIVE_CANARY_MIN_ARTIFACTS:
			process.env.AUTOPEP_LIVE_CANARY_MIN_ARTIFACTS,
		AUTOPEP_LIVE_CANARY_MIN_CANDIDATES:
			process.env.AUTOPEP_LIVE_CANARY_MIN_CANDIDATES,
		AUTOPEP_LIVE_CANARY_MIN_OK_SCORE_ROWS:
			process.env.AUTOPEP_LIVE_CANARY_MIN_OK_SCORE_ROWS,
		AUTOPEP_LIVE_CANARY_MIN_SCORE_ROWS:
			process.env.AUTOPEP_LIVE_CANARY_MIN_SCORE_ROWS,
		AUTOPEP_LIVE_CANARY_OUTPUT: process.env.AUTOPEP_LIVE_CANARY_OUTPUT,
		AUTOPEP_LIVE_CANARY_OWNER_ID: process.env.AUTOPEP_LIVE_CANARY_OWNER_ID,
		AUTOPEP_LIVE_CANARY_POLL_INTERVAL_MS:
			process.env.AUTOPEP_LIVE_CANARY_POLL_INTERVAL_MS,
		AUTOPEP_LIVE_CANARY_REQUIRE_CITATION:
			process.env.AUTOPEP_LIVE_CANARY_REQUIRE_CITATION,
		AUTOPEP_LIVE_CANARY_REQUIRE_EXPECTED_PDB:
			process.env.AUTOPEP_LIVE_CANARY_REQUIRE_EXPECTED_PDB,
		AUTOPEP_LIVE_CANARY_TIMEOUT_MS: process.env.AUTOPEP_LIVE_CANARY_TIMEOUT_MS,
		AUTOPEP_MODAL_RUN_STREAM_URL: process.env.AUTOPEP_MODAL_RUN_STREAM_URL,
		AUTOPEP_MODAL_START_URL: process.env.AUTOPEP_MODAL_START_URL,
		AUTOPEP_MODAL_WEBHOOK_SECRET: process.env.AUTOPEP_MODAL_WEBHOOK_SECRET,
		AUTOPEP_NEXT_PUBLIC_URL: process.env.AUTOPEP_NEXT_PUBLIC_URL,
		AUTOPEP_RUNNER_BACKEND: process.env.AUTOPEP_RUNNER_BACKEND,
		AUTOPEP_SMOKE_OWNER_ID: process.env.AUTOPEP_SMOKE_OWNER_ID,
		AUTOPEP_SMOKE_THREAD_ID: process.env.AUTOPEP_SMOKE_THREAD_ID,
		AUTOPEP_SMOKE_WORKSPACE_ID: process.env.AUTOPEP_SMOKE_WORKSPACE_ID,
		AUTOPEP_WORKER_ID: process.env.AUTOPEP_WORKER_ID,
		BETTER_AUTH_SECRET: process.env.BETTER_AUTH_SECRET,
		BETTER_AUTH_URL: process.env.BETTER_AUTH_URL,
		DATABASE_URL: process.env.DATABASE_URL,
		MODAL_CHAI_API_KEY: process.env.MODAL_CHAI_API_KEY,
		MODAL_CHAI_URL: process.env.MODAL_CHAI_URL,
		MODAL_PROTEIN_INTERACTION_SCORING_API_KEY:
			process.env.MODAL_PROTEIN_INTERACTION_SCORING_API_KEY,
		MODAL_PROTEIN_INTERACTION_SCORING_URL:
			process.env.MODAL_PROTEIN_INTERACTION_SCORING_URL,
		MODAL_PROTEINA_API_KEY: process.env.MODAL_PROTEINA_API_KEY,
		MODAL_PROTEINA_URL: process.env.MODAL_PROTEINA_URL,
		MODAL_TOKEN_ID: process.env.MODAL_TOKEN_ID,
		MODAL_TOKEN_SECRET: process.env.MODAL_TOKEN_SECRET,
		NODE_ENV: process.env.NODE_ENV,
		OPENAI_API_KEY: process.env.OPENAI_API_KEY,
		OPENAI_DEFAULT_MODEL: process.env.OPENAI_DEFAULT_MODEL,
		R2_ACCESS_KEY_ID: process.env.R2_ACCESS_KEY_ID,
		R2_ACCOUNT_ID: process.env.R2_ACCOUNT_ID,
		R2_BUCKET: process.env.R2_BUCKET,
		R2_PUBLIC_BASE_URL: process.env.R2_PUBLIC_BASE_URL,
		R2_SECRET_ACCESS_KEY: process.env.R2_SECRET_ACCESS_KEY,
	},
	/**
	 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially
	 * useful for Docker builds.
	 */
	skipValidation: !!process.env.SKIP_ENV_VALIDATION,
	/**
	 * Makes it so that empty strings are treated as undefined. `SOME_VAR: z.string()` and
	 * `SOME_VAR=''` will throw an error.
	 */
	emptyStringAsUndefined: true,
});
