import { afterEach, describe, expect, it, vi } from "vitest";

type RunLauncherModule = typeof import("./run-launcher");

const importRunLauncher = async ({
	backend,
	startModalRun = vi.fn(),
}: {
	backend: "local" | "modal";
	startModalRun?: ReturnType<typeof vi.fn>;
}): Promise<RunLauncherModule> => {
	vi.resetModules();
	vi.doMock("@/env", () => ({
		env: {
			AUTOPEP_RUNNER_BACKEND: backend,
		},
	}));
	vi.doMock("./modal-launcher", () => ({
		startModalRun,
	}));

	return import("./run-launcher");
};

const makeFailedRunUpdateDb = () => {
	const failedRun = {
		id: "11111111-1111-4111-8111-111111111111",
		status: "failed",
	};
	const returning = vi.fn().mockResolvedValue([failedRun]);
	const where = vi.fn(() => ({ returning }));
	const set = vi.fn(() => ({ where }));
	const update = vi.fn(() => ({ set }));

	return { db: { update }, failedRun, returning, set, update, where };
};

describe("launchCreatedRun", () => {
	afterEach(() => {
		vi.doUnmock("@/env");
		vi.doUnmock("./modal-launcher");
		vi.resetModules();
	});

	it("leaves local runs queued without calling Modal", async () => {
		const startModalRun = vi.fn();
		const { launchCreatedRun } = await importRunLauncher({
			backend: "local",
			startModalRun,
		});

		const result = await launchCreatedRun({
			db: { update: vi.fn() } as never,
			projectId: "22222222-2222-4222-8222-222222222222",
			runId: "11111111-1111-4111-8111-111111111111",
		});

		expect(result).toEqual({ backend: "local", launched: false });
		expect(startModalRun).not.toHaveBeenCalled();
	});

	it("marks the run failed when Modal launch fails", async () => {
		const startModalRun = vi
			.fn()
			.mockRejectedValue(new Error("Modal unavailable"));
		const appendRunEvent = vi.fn().mockResolvedValue(undefined);
		const { db, failedRun, set } = makeFailedRunUpdateDb();
		const { launchCreatedRun } = await importRunLauncher({
			backend: "modal",
			startModalRun,
		});

		const result = await launchCreatedRun({
			appendRunEvent,
			db: db as never,
			projectId: "22222222-2222-4222-8222-222222222222",
			runId: "11111111-1111-4111-8111-111111111111",
		});

		expect(startModalRun).toHaveBeenCalledWith({
			projectId: "22222222-2222-4222-8222-222222222222",
			runId: "11111111-1111-4111-8111-111111111111",
		});
		expect(set).toHaveBeenCalledWith(
			expect.objectContaining({
				errorSummary: "Modal unavailable",
				status: "failed",
			}),
		);
		expect(appendRunEvent).toHaveBeenCalledWith(
			expect.objectContaining({
				db,
				detail: "Modal unavailable",
				runId: "11111111-1111-4111-8111-111111111111",
				title: "Modal launch failed",
				type: "run_failed",
			}),
		);
		expect(result).toEqual({
			backend: "modal",
			errorSummary: "Modal unavailable",
			launched: false,
			run: failedRun,
		});
	});
});
