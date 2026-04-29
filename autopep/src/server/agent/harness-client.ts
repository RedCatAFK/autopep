import { spawn } from "node:child_process";

import { env } from "@/env";

type RunCodexHarnessInput = {
	runId: string;
	workspaceId: string;
	prompt: string;
	topK: number;
};

type RunCodexHarnessResult = {
	stdout: string;
	stderr: string;
};

export const runCodexHarness = async ({
	runId,
	prompt,
	topK,
	workspaceId,
}: RunCodexHarnessInput): Promise<RunCodexHarnessResult> => {
	const command = env.AUTOPEP_CODEX_COMMAND;

	if (!command) {
		throw new Error(
			"AUTOPEP_CODEX_COMMAND is required when AUTOPEP_AGENT_MODE is codex.",
		);
	}

	const payload = {
		projectId: workspaceId,
		prompt,
		runId,
		topK,
		workspaceId,
	};

	return new Promise((resolve, reject) => {
		const child = spawn(command, {
			env: {
				...process.env,
				AUTOPEP_HARNESS_INPUT: JSON.stringify(payload),
				AUTOPEP_PROMPT: prompt,
				AUTOPEP_PROJECT_ID: workspaceId,
				AUTOPEP_RUN_ID: runId,
				AUTOPEP_TOP_K: String(topK),
				AUTOPEP_WORKSPACE_ID: workspaceId,
			},
			shell: true,
			stdio: ["ignore", "pipe", "pipe"],
		});

		let stdout = "";
		let stderr = "";

		child.stdout.on("data", (chunk: Buffer | string) => {
			stdout += chunk.toString();
		});

		child.stderr.on("data", (chunk: Buffer | string) => {
			stderr += chunk.toString();
		});

		child.on("error", (error) => {
			reject(error);
		});

		child.on("close", (code) => {
			if (code !== 0) {
				reject(
					new Error(
						`Codex harness exited with code ${code ?? "unknown"}.\n` +
							`stderr:\n${stderr || "(empty)"}\n` +
							`stdout:\n${stdout || "(empty)"}`,
					),
				);
				return;
			}

			resolve({ stderr, stdout });
		});
	});
};
