import { afterEach, describe, expect, it, vi } from "vitest";

type HarnessClientModule = typeof import("./harness-client");

const importHarnessClient = async (
	command: string | undefined,
): Promise<HarnessClientModule> => {
	vi.resetModules();
	vi.doMock("@/env", () => ({
		env: {
			AUTOPEP_CODEX_COMMAND: command,
		},
	}));

	return import("./harness-client");
};

describe("runCodexHarness", () => {
	afterEach(() => {
		vi.doUnmock("@/env");
		vi.resetModules();
	});

	it("passes run metadata through environment variables", async () => {
		const { runCodexHarness } = await importHarnessClient(
			`node -e "process.stdout.write(JSON.stringify({ harnessInput: JSON.parse(process.env.AUTOPEP_HARNESS_INPUT || '{}'), projectId: process.env.AUTOPEP_PROJECT_ID, workspaceId: process.env.AUTOPEP_WORKSPACE_ID }))"`,
		);

		const result = await runCodexHarness({
			prompt: "Design a protein binder for SARS-CoV-2 spike RBD",
			runId: "run-1",
			topK: 5,
			workspaceId: "workspace-1",
		});
		const output = JSON.parse(result.stdout);

		expect(output).toMatchObject({
			harnessInput: {
				projectId: "workspace-1",
				prompt: "Design a protein binder for SARS-CoV-2 spike RBD",
				runId: "run-1",
				topK: 5,
				workspaceId: "workspace-1",
			},
			projectId: "workspace-1",
			workspaceId: "workspace-1",
		});
		expect(result.stderr).toBe("");
	});

	it("requires an explicit harness command", async () => {
		const { runCodexHarness } = await importHarnessClient(undefined);

		await expect(
			runCodexHarness({
				prompt: "Design a protein binder",
				runId: "run-1",
				topK: 5,
				workspaceId: "workspace-1",
			}),
		).rejects.toThrow("AUTOPEP_CODEX_COMMAND is required");
	});

	it("includes harness output when the command fails", async () => {
		const { runCodexHarness } = await importHarnessClient(
			`node -e "console.error('harness failed'); process.exit(7)"`,
		);

		await expect(
			runCodexHarness({
				prompt: "Design a protein binder",
				runId: "run-1",
				topK: 5,
				workspaceId: "workspace-1",
			}),
		).rejects.toThrow(/code 7[\s\S]*harness failed/u);
	});
});
