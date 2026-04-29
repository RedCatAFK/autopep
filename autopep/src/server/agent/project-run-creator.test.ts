import { describe, expect, it, vi } from "vitest";

import { createProjectRunWithLaunch } from "./project-run-creator";

const insertReturning = (row: unknown) => {
	const returning = vi.fn().mockResolvedValue([row]);
	const values = vi.fn(() => ({ returning }));
	return { returning, values };
};

describe("createProjectRunWithLaunch", () => {
	it("launches the created run and returns the failed run when Modal launch fails", async () => {
		const workspace = {
			description: "Design a protein binder for SARS-CoV-2 spike RBD",
			id: "22222222-2222-4222-8222-222222222222",
			name: "Spike RBD binder",
			ownerId: "user-1",
		};
		const thread = {
			id: "33333333-3333-4333-8333-333333333333",
			title: workspace.name,
			workspaceId: workspace.id,
		};
		const queuedRun = {
			createdById: "user-1",
			id: "11111111-1111-4111-8111-111111111111",
			prompt: workspace.description,
			status: "queued",
			threadId: thread.id,
			workspaceId: workspace.id,
		};
		const message = {
			content: workspace.description,
			id: "44444444-4444-4444-8444-444444444444",
			role: "user",
			runId: queuedRun.id,
			threadId: thread.id,
		};
		const failedRun = {
			...queuedRun,
			errorSummary: "Modal unavailable",
			status: "failed",
		};
		const workspaceInsert = insertReturning(workspace);
		const threadInsert = insertReturning(thread);
		const runInsert = insertReturning(queuedRun);
		const messageInsert = insertReturning(message);
		const where = vi.fn().mockResolvedValue(undefined);
		const set = vi.fn(() => ({ where }));
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(workspaceInsert)
				.mockReturnValueOnce(threadInsert)
				.mockReturnValueOnce(runInsert)
				.mockReturnValueOnce(messageInsert),
			update: vi.fn(() => ({ set })),
		};
		const launchRun = vi.fn().mockResolvedValue({
			backend: "modal",
			errorSummary: "Modal unavailable",
			launched: false,
			run: failedRun,
		});

		const result = await createProjectRunWithLaunch({
			db: db as never,
			input: {
				goal: workspace.description,
				name: workspace.name,
				topK: 5,
			},
			launchRun,
			ownerId: "user-1",
		});

		expect(launchRun).toHaveBeenCalledWith({
			db,
			projectId: workspace.id,
			runId: queuedRun.id,
		});
		expect(result).toEqual({
			message,
			project: workspace,
			run: failedRun,
			thread,
			workspace,
		});
	});
});
