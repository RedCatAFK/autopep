/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

import "./src/env.js";

const appDir = dirname(fileURLToPath(import.meta.url));

/** @type {import("next").NextConfig} */
const config = {
	turbopack: {
		root: appDir,
	},
	transpilePackages: ["molstar"],
};

export default config;
