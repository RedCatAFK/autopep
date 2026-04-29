import { afterEach, describe, expect, it, vi } from "vitest";

type RunExecutorModule = typeof import("./run-executor");

const importRunExecutor = async (): Promise<RunExecutorModule> => {
	vi.resetModules();
	vi.doMock("@/env", () => ({
		env: {
			AUTOPEP_AGENT_MODE: "direct",
		},
	}));
	vi.doMock("@/server/db", () => ({
		db: {},
	}));
	return import("./run-executor");
};

const makeUpdateChain = (returningValue: unknown[]) => {
	const returning = vi.fn().mockResolvedValue(returningValue);
	const where = vi.fn(() => ({ returning }));
	const set = vi.fn(() => ({ where }));
	const update = vi.fn(() => ({ set }));

	return { returning, set, update, where };
};

describe("run executor", () => {
	afterEach(() => {
		vi.doUnmock("@/env");
		vi.doUnmock("@/server/db");
		vi.resetModules();
	});

	it("claims and executes only the requested queued run", async () => {
		const run = {
			id: "11111111-1111-4111-8111-111111111111",
			projectId: "22222222-2222-4222-8222-222222222222",
			prompt: "Design a protein binder for SARS-CoV-2 spike RBD",
			status: "running",
			topK: 5,
		};
		const updateChain = makeUpdateChain([run]);
		const db = {
			query: {
				agentRuns: {
					findFirst: vi.fn(),
				},
			},
			update: updateChain.update,
		};
		const runCifRetrievalPipeline = vi.fn().mockResolvedValue({
			runId: run.id,
		});

		const { runRunById } = await importRunExecutor();
		const didWork = await runRunById(run.id, {
			agentMode: "direct",
			db: db as never,
			runCifRetrievalPipeline,
			workerId: "test-worker",
		});

		expect(didWork).toBe(true);
		expect(updateChain.update).toHaveBeenCalledTimes(1);
		expect(db.query.agentRuns.findFirst).not.toHaveBeenCalled();
		expect(runCifRetrievalPipeline).toHaveBeenCalledWith({
			db,
			runId: run.id,
		});
	}, 10_000);

	it("does not fall back to another queued run when the requested run is already active", async () => {
		const requestedRun = {
			id: "33333333-3333-4333-8333-333333333333",
			projectId: "44444444-4444-4444-8444-444444444444",
			prompt: "Design a protein to bind to 3CL-protease",
			status: "running",
			topK: 5,
		};
		const updateChain = makeUpdateChain([]);
		const db = {
			query: {
				agentRuns: {
					findFirst: vi.fn().mockResolvedValue(requestedRun),
				},
			},
			update: updateChain.update,
		};
		const appendRunEvent = vi.fn().mockResolvedValue(undefined);
		const runCifRetrievalPipeline = vi.fn();

		const { runRunById } = await importRunExecutor();
		const didWork = await runRunById(requestedRun.id, {
			appendRunEvent,
			agentMode: "direct",
			db: db as never,
			runCifRetrievalPipeline,
			workerId: "test-worker",
		});

		expect(didWork).toBe(false);
		expect(runCifRetrievalPipeline).not.toHaveBeenCalled();
		expect(db.query.agentRuns.findFirst).toHaveBeenCalledTimes(1);
		expect(appendRunEvent).toHaveBeenCalledWith(
			expect.objectContaining({
				db,
				runId: requestedRun.id,
				title: "Run start skipped",
				type: "run_start_skipped",
			}),
		);
	}, 10_000);

	it("falls back to deterministic retrieval when the Codex harness cannot produce a ready CIF", async () => {
		const run = {
			id: "55555555-5555-4555-8555-555555555555",
			projectId: "66666666-6666-4666-8666-666666666666",
			prompt: "Design a protein binder for SARS-CoV-2 spike RBD",
			status: "running",
			topK: 5,
		};
		const where = vi.fn().mockResolvedValue([]);
		const from = vi.fn(() => ({ where }));
		const db = {
			select: vi.fn(() => ({ from })),
		};
		const appendRunEvent = vi.fn().mockResolvedValue(undefined);
		const runCodexHarness = vi
			.fn()
			.mockRejectedValue(new Error("401 Unauthorized"));
		const runCifRetrievalPipeline = vi.fn().mockResolvedValue({
			runId: run.id,
		});
		const validateRunCompletion = vi.fn().mockReturnValue({
			ok: false,
			reason: "No proteina-ready candidate exists.",
		});
		const logger = {
			error: vi.fn(),
			log: vi.fn(),
		};

		const { executeClaimedRun } = await importRunExecutor();
		const didWork = await executeClaimedRun(run as never, {
			appendRunEvent,
			agentMode: "codex",
			db: db as never,
			logger,
			runCifRetrievalPipeline,
			runCodexHarness,
			validateRunCompletion,
		});

		expect(didWork).toBe(true);
		expect(runCodexHarness).toHaveBeenCalledWith({
			projectId: run.projectId,
			prompt: run.prompt,
			runId: run.id,
			topK: run.topK,
		});
		expect(appendRunEvent).toHaveBeenCalledWith(
			expect.objectContaining({
				runId: run.id,
				title: "Codex agent fallback",
				type: "codex_agent_fallback",
			}),
		);
		expect(runCifRetrievalPipeline).toHaveBeenCalledWith({
			db,
			runId: run.id,
		});
	});
});
