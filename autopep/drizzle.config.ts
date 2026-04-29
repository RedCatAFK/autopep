import type { Config } from "drizzle-kit";

import { env } from "@/env";

export default {
	schema: "./src/server/db/schema.ts",
	dialect: "postgresql",
	dbCredentials: {
		url: env.DATABASE_URL,
	},
	tablesFilter: [
		"autopep_*",
		"pg-drizzle_*",
		"user",
		"session",
		"account",
		"verification",
	],
} satisfies Config;
