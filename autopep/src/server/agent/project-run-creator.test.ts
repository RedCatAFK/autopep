import { describe, expect, it, vi } from "vitest";

import { createProjectRunWithLaunch } from "./project-run-creator";

const insertReturning = (row: unknown) => {
	const returning = vi.fn().mockResolvedValue([row]);
	const values = vi.fn(() => ({ returning }));
	return { returning, values };
};

describe("createProjectRunWithLaunch", () => {
	it("launches the created run and returns the failed run when Modal launch fails", async () => {
		const project = {
			goal: "Design a protein binder for SARS-CoV-2 spike RBD",
			id: "22222222-2222-4222-8222-222222222222",
			name: "Spike RBD binder",
			ownerId: "user-1",
		};
		const queuedRun = {
			createdById: "user-1",
			id: "11111111-1111-4111-8111-111111111111",
			projectId: project.id,
			prompt: project.goal,
			status: "queued",
			topK: 5,
		};
		const failedRun = {
			...queuedRun,
			errorSummary: "Modal unavailable",
			status: "failed",
		};
		const projectInsert = insertReturning(project);
		const runInsert = insertReturning(queuedRun);
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(projectInsert)
				.mockReturnValueOnce(runInsert),
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
				goal: project.goal,
				name: project.name,
				topK: 5,
			},
			launchRun,
			ownerId: "user-1",
		});

		expect(launchRun).toHaveBeenCalledWith({
			db,
			projectId: project.id,
			runId: queuedRun.id,
		});
		expect(result).toEqual({ project, run: failedRun });
	});
});
