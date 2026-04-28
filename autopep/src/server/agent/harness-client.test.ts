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
			`node -e "process.stdout.write(process.env.AUTOPEP_HARNESS_INPUT || '')"`,
		);

		const result = await runCodexHarness({
			projectId: "project-1",
			prompt: "Design a protein binder for SARS-CoV-2 spike RBD",
			runId: "run-1",
			topK: 5,
		});

		expect(JSON.parse(result.stdout)).toMatchObject({
			projectId: "project-1",
			prompt: "Design a protein binder for SARS-CoV-2 spike RBD",
			runId: "run-1",
			topK: 5,
		});
		expect(result.stderr).toBe("");
	});

	it("requires an explicit harness command", async () => {
		const { runCodexHarness } = await importHarnessClient(undefined);

		await expect(
			runCodexHarness({
				projectId: "project-1",
				prompt: "Design a protein binder",
				runId: "run-1",
				topK: 5,
			}),
		).rejects.toThrow("AUTOPEP_CODEX_COMMAND is required");
	});

	it("includes harness output when the command fails", async () => {
		const { runCodexHarness } = await importHarnessClient(
			`node -e "console.error('harness failed'); process.exit(7)"`,
		);

		await expect(
			runCodexHarness({
				projectId: "project-1",
				prompt: "Design a protein binder",
				runId: "run-1",
				topK: 5,
			}),
		).rejects.toThrow(/code 7[\s\S]*harness failed/u);
	});
});
