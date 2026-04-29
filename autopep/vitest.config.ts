import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
	resolve: {
		alias: {
			"@": fileURLToPath(new URL("./src", import.meta.url)),
		},
	},
	test: {
		environment: "node",
		globals: true,
		setupFiles: ["./src/test/setup.ts"],
		env: {
			AUTOPEP_MODAL_RUN_STREAM_URL: "https://example.invalid/run-stream",
			AUTOPEP_MODAL_WEBHOOK_SECRET: "test-modal-webhook-secret",
			BETTER_AUTH_SECRET: "test-secret",
			DATABASE_URL: "postgres://user:password@localhost:5432/autopep_test",
			NODE_ENV: "test",
			R2_ACCESS_KEY_ID: "test-access-key",
			R2_ACCOUNT_ID: "test-account",
			R2_BUCKET: "autopep-test",
			R2_SECRET_ACCESS_KEY: "test-secret-key",
		},
	},
});
