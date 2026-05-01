import { createEnv } from "@t3-oss/env-nextjs";
import { z } from "zod";

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
		DATABASE_URL: z.string().url(),
		JULIA_WORKER_START_URL: z.string().url().optional(),
		JULIA_WORKER_WEBHOOK_SECRET: z.string().optional(),
		R2_ACCOUNT_ID: z.string().optional(),
		R2_ACCESS_KEY_ID: z.string().optional(),
		R2_SECRET_ACCESS_KEY: z.string().optional(),
		R2_BUCKET: z.string().default("julia"),
		R2_PUBLIC_BASE_URL: z.string().url().optional(),
		OPENAI_API_KEY: z.string().optional(),
		OPENAI_DEFAULT_MODEL: z.string().default("gpt-5.5"),
		AUTOPEP2_SESSION_ID: z.string().optional(),
		AUTOPEP2_MAX_TOOL_TIMEOUT: z.string().optional(),
		AUTOPEP2_TOOL_OUTPUT_CHARS: z.string().optional(),
		AUTOPEP2_MAX_AGENT_TURNS: z.string().optional(),
		NCBI_API_KEY: z.string().optional(),
		NCBI_TOOL_EMAIL: z.string().optional(),
		MODAL_CHAI_URL: z.string().url().optional(),
		MODAL_CHAI_API_KEY: z.string().optional(),
		MODAL_PROTEINA_URL: z.string().url().optional(),
		MODAL_PROTEINA_API_KEY: z.string().optional(),
		MODAL_PROTEIN_INTERACTION_SCORING_URL: z.string().url().optional(),
		MODAL_PROTEIN_INTERACTION_SCORING_API_KEY: z.string().optional(),
		MODAL_QUALITY_SCORERS_URL: z.string().url().optional(),
		MODAL_QUALITY_SCORERS_API_KEY: z.string().optional(),
		JULIA_DEEPSEEK_PROVIDER: z
			.enum(["openrouter", "fireworks"])
			.default("openrouter"),
		FIREWORKS_API_KEY: z.string().optional(),
		FIREWORKS_BASE_URL: z.string().url().optional(),
		FIREWORKS_DEEPSEEK_MODEL: z
			.string()
			.default("accounts/fireworks/models/deepseek-v4-pro"),
		FIREWORKS_REASONING_EFFORT: z.string().optional(),
		OPENROUTER_API_KEY: z.string().optional(),
		OPENROUTER_BASE_URL: z.string().url().optional(),
		OPENROUTER_DEEPSEEK_MODEL: z
			.string()
			.default("deepseek/deepseek-v4-pro"),
		OPENROUTER_REASONING_EFFORT: z.string().optional(),
		OPENROUTER_APP_TITLE: z.string().optional(),
		OPENROUTER_HTTP_REFERER: z.string().optional(),
		OPENROUTER_PROVIDER_ORDER: z.string().optional(),
		OPENROUTER_PROVIDER_ONLY: z.string().optional(),
		OPENROUTER_PROVIDER_IGNORE: z.string().optional(),
		OPENROUTER_ALLOW_FALLBACKS: z.string().optional(),
		OPENROUTER_REQUIRE_PARAMETERS: z.string().optional(),
		NODE_ENV: z
			.enum(["development", "test", "production"])
			.default("development"),
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
		BETTER_AUTH_SECRET: process.env.BETTER_AUTH_SECRET,
		BETTER_AUTH_URL: process.env.BETTER_AUTH_URL,
		DATABASE_URL: process.env.DATABASE_URL,
		JULIA_WORKER_START_URL: process.env.JULIA_WORKER_START_URL,
		JULIA_WORKER_WEBHOOK_SECRET: process.env.JULIA_WORKER_WEBHOOK_SECRET,
		R2_ACCOUNT_ID: process.env.R2_ACCOUNT_ID,
		R2_ACCESS_KEY_ID: process.env.R2_ACCESS_KEY_ID,
		R2_SECRET_ACCESS_KEY: process.env.R2_SECRET_ACCESS_KEY,
		R2_BUCKET: process.env.R2_BUCKET,
		R2_PUBLIC_BASE_URL: process.env.R2_PUBLIC_BASE_URL,
		OPENAI_API_KEY: process.env.OPENAI_API_KEY,
		OPENAI_DEFAULT_MODEL: process.env.OPENAI_DEFAULT_MODEL,
		AUTOPEP2_SESSION_ID: process.env.AUTOPEP2_SESSION_ID,
		AUTOPEP2_MAX_TOOL_TIMEOUT: process.env.AUTOPEP2_MAX_TOOL_TIMEOUT,
		AUTOPEP2_TOOL_OUTPUT_CHARS: process.env.AUTOPEP2_TOOL_OUTPUT_CHARS,
		AUTOPEP2_MAX_AGENT_TURNS: process.env.AUTOPEP2_MAX_AGENT_TURNS,
		NCBI_API_KEY: process.env.NCBI_API_KEY,
		NCBI_TOOL_EMAIL: process.env.NCBI_TOOL_EMAIL,
		MODAL_CHAI_URL: process.env.MODAL_CHAI_URL,
		MODAL_CHAI_API_KEY: process.env.MODAL_CHAI_API_KEY,
		MODAL_PROTEINA_URL: process.env.MODAL_PROTEINA_URL,
		MODAL_PROTEINA_API_KEY: process.env.MODAL_PROTEINA_API_KEY,
		MODAL_PROTEIN_INTERACTION_SCORING_URL:
			process.env.MODAL_PROTEIN_INTERACTION_SCORING_URL,
		MODAL_PROTEIN_INTERACTION_SCORING_API_KEY:
			process.env.MODAL_PROTEIN_INTERACTION_SCORING_API_KEY,
		MODAL_QUALITY_SCORERS_URL: process.env.MODAL_QUALITY_SCORERS_URL,
		MODAL_QUALITY_SCORERS_API_KEY: process.env.MODAL_QUALITY_SCORERS_API_KEY,
		JULIA_DEEPSEEK_PROVIDER: process.env.JULIA_DEEPSEEK_PROVIDER,
		FIREWORKS_API_KEY: process.env.FIREWORKS_API_KEY,
		FIREWORKS_BASE_URL: process.env.FIREWORKS_BASE_URL,
		FIREWORKS_DEEPSEEK_MODEL: process.env.FIREWORKS_DEEPSEEK_MODEL,
		FIREWORKS_REASONING_EFFORT: process.env.FIREWORKS_REASONING_EFFORT,
		OPENROUTER_API_KEY: process.env.OPENROUTER_API_KEY,
		OPENROUTER_BASE_URL: process.env.OPENROUTER_BASE_URL,
		OPENROUTER_DEEPSEEK_MODEL: process.env.OPENROUTER_DEEPSEEK_MODEL,
		OPENROUTER_REASONING_EFFORT: process.env.OPENROUTER_REASONING_EFFORT,
		OPENROUTER_APP_TITLE: process.env.OPENROUTER_APP_TITLE,
		OPENROUTER_HTTP_REFERER: process.env.OPENROUTER_HTTP_REFERER,
		OPENROUTER_PROVIDER_ORDER: process.env.OPENROUTER_PROVIDER_ORDER,
		OPENROUTER_PROVIDER_ONLY: process.env.OPENROUTER_PROVIDER_ONLY,
		OPENROUTER_PROVIDER_IGNORE: process.env.OPENROUTER_PROVIDER_IGNORE,
		OPENROUTER_ALLOW_FALLBACKS: process.env.OPENROUTER_ALLOW_FALLBACKS,
		OPENROUTER_REQUIRE_PARAMETERS: process.env.OPENROUTER_REQUIRE_PARAMETERS,
		NODE_ENV: process.env.NODE_ENV,
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
