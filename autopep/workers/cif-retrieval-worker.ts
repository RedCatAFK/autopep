import {
	claimNextRun,
	claimRunById,
	executeClaimedRun,
	runLoop,
	runOnce,
	runRunById,
} from "@/server/agent/run-executor";

export {
	claimNextRun,
	claimRunById,
	executeClaimedRun,
	runLoop,
	runOnce,
	runRunById,
};

const parseRunIdArg = () => {
	const equalsArg = process.argv.find((arg) => arg.startsWith("--run-id="));
	if (equalsArg) {
		return equalsArg.slice("--run-id=".length);
	}

	const flagIndex = process.argv.indexOf("--run-id");
	if (flagIndex >= 0) {
		return process.argv[flagIndex + 1];
	}

	return undefined;
};

const runId = parseRunIdArg();

if (
	process.argv.some((arg) => arg === "--run-id" || arg.startsWith("--run-id="))
) {
	if (!runId) {
		throw new Error("Expected a run id after --run-id.");
	}

	await runRunById(runId);
	process.exit(0);
}

if (process.argv.includes("--once")) {
	await runOnce();
	process.exit(0);
}

await runLoop();
