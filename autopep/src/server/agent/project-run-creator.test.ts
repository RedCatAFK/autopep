import { describe, expect, it, vi } from "vitest";

import {
	createMessageRunWithLaunch,
	createProjectRunWithLaunch,
} from "./project-run-creator";

const insertReturning = (row: unknown) => {
	const returning = vi.fn().mockResolvedValue([row]);
	const values = vi.fn(() => ({ returning }));
	return { returning, values };
};

const insertReturningNoRows = () => {
	const returning = vi.fn().mockResolvedValue([]);
	const values = vi.fn(() => ({ returning }));
	return { returning, values };
};

const updateReturning = (row: unknown) => {
	const returning = vi.fn().mockResolvedValue([row]);
	const where = vi.fn(() => ({ returning }));
	const set = vi.fn(() => ({ where }));
	return { returning, set, where };
};

describe("createMessageRunWithLaunch", () => {
	it("creates a workspace and thread when missing, links the user message to the run, and launches it", async () => {
		const workspace = {
			description: null,
			id: "22222222-2222-4222-8222-222222222222",
			name: "Design binders for SARS-CoV-2 3CL protease",
			ownerId: "user-1",
		};
		const thread = {
			id: "33333333-3333-4333-8333-333333333333",
			title: "Main thread",
			workspaceId: workspace.id,
		};
		const updatedWorkspace = {
			...workspace,
			activeThreadId: thread.id,
		};
		const queuedRun = {
			createdById: "user-1",
			id: "11111111-1111-4111-8111-111111111111",
			prompt: "Design binders for SARS-CoV-2 3CL protease",
			status: "queued",
			taskKind: "chat",
			threadId: thread.id,
			workspaceId: workspace.id,
		};
		const message = {
			content: queuedRun.prompt,
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
		const workspaceUpdate = updateReturning(updatedWorkspace);
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(workspaceInsert)
				.mockReturnValueOnce(threadInsert)
				.mockReturnValueOnce(runInsert)
				.mockReturnValueOnce(messageInsert),
			update: vi.fn().mockReturnValueOnce({ set: workspaceUpdate.set }),
		};
		const launchRun = vi.fn().mockResolvedValue({
			backend: "modal",
			errorSummary: "Modal unavailable",
			launched: false,
			run: failedRun,
		});

		const result = await createMessageRunWithLaunch({
			db: db as never,
			input: {
				prompt: message.content,
			},
			launchRun,
			ownerId: "user-1",
		});

		expect(runInsert.values).toHaveBeenCalledWith(
			expect.objectContaining({
				createdById: "user-1",
				prompt: message.content,
				rootRunId: null,
				status: "queued",
				taskKind: "chat",
				threadId: thread.id,
				workspaceId: workspace.id,
			}),
		);
		expect(messageInsert.values).toHaveBeenCalledWith({
			attachmentRefsJson: [],
			content: message.content,
			contextRefsJson: [],
			recipeRefsJson: [],
			role: "user",
			runId: queuedRun.id,
			threadId: thread.id,
		});
		expect(launchRun).toHaveBeenCalledWith({
			db,
			runId: queuedRun.id,
			threadId: thread.id,
			workspaceId: workspace.id,
		});
		expect(result).toEqual({
			message,
			run: failedRun,
			thread,
			workspace: updatedWorkspace,
		});
	});

	it("uses an owned workspace and its active thread when a workspace id is provided", async () => {
		const workspace = {
			activeThreadId: "33333333-3333-4333-8333-333333333333",
			id: "22222222-2222-4222-8222-222222222222",
			name: "3CL protease",
			ownerId: "user-1",
		};
		const thread = {
			id: workspace.activeThreadId,
			title: "Main thread",
			workspaceId: workspace.id,
		};
		const queuedRun = {
			createdById: "user-1",
			id: "11111111-1111-4111-8111-111111111111",
			prompt: "Continue with a folding run",
			status: "queued",
			taskKind: "prepare_structure",
			threadId: thread.id,
			workspaceId: workspace.id,
		};
		const message = {
			content: queuedRun.prompt,
			id: "44444444-4444-4444-8444-444444444444",
			role: "user",
			runId: queuedRun.id,
			threadId: thread.id,
		};
		const runInsert = insertReturning(queuedRun);
		const messageInsert = insertReturning(message);
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(runInsert)
				.mockReturnValueOnce(messageInsert),
			query: {
				recipeVersions: { findFirst: vi.fn() },
				recipes: { findFirst: vi.fn() },
				threads: { findFirst: vi.fn().mockResolvedValue(thread) },
				workspaces: { findFirst: vi.fn().mockResolvedValue(workspace) },
			},
		};
		const launchRun = vi.fn().mockResolvedValue({
			backend: "modal",
			launched: true,
		});

		const result = await createMessageRunWithLaunch({
			db: db as never,
			input: {
				attachmentRefs: ["77777777-7777-4777-8777-777777777777"],
				contextRefs: ["55555555-5555-4555-8555-555555555555"],
				prompt: message.content,
				recipeRefs: ["66666666-6666-4666-8666-666666666666"],
				taskKind: "prepare_structure",
				workspaceId: workspace.id,
			},
			launchRun,
			ownerId: "user-1",
		});

		expect(runInsert.values).toHaveBeenCalledWith(
			expect.objectContaining({
				taskKind: "prepare_structure",
				threadId: thread.id,
				workspaceId: workspace.id,
			}),
		);
		expect(messageInsert.values).toHaveBeenCalledWith({
			attachmentRefsJson: ["77777777-7777-4777-8777-777777777777"],
			content: message.content,
			contextRefsJson: ["55555555-5555-4555-8555-555555555555"],
			recipeRefsJson: ["66666666-6666-4666-8666-666666666666"],
			role: "user",
			runId: queuedRun.id,
			threadId: thread.id,
		});
		expect(launchRun).toHaveBeenCalledWith({
			db,
			runId: queuedRun.id,
			threadId: thread.id,
			workspaceId: workspace.id,
		});
		expect(result).toEqual({
			message,
			run: queuedRun,
			thread,
			workspace,
		});
	});

	it("snapshots selected recipe versions onto the run", async () => {
		const workspace = {
			activeThreadId: "33333333-3333-4333-8333-333333333333",
			id: "22222222-2222-4222-8222-222222222222",
			name: "3CL protease",
			ownerId: "user-1",
		};
		const thread = {
			id: workspace.activeThreadId,
			title: "Main thread",
			workspaceId: workspace.id,
		};
		const queuedRun = {
			createdById: "user-1",
			id: "11111111-1111-4111-8111-111111111111",
			prompt: "Generate a protein that binds to 3CL-protease",
			status: "queued",
			taskKind: "branch_design",
			threadId: thread.id,
			workspaceId: workspace.id,
		};
		const message = {
			content: queuedRun.prompt,
			id: "44444444-4444-4444-8444-444444444444",
			role: "user",
			runId: queuedRun.id,
			threadId: thread.id,
		};
		const recipe = {
			id: "66666666-6666-4666-8666-666666666666",
			name: "One-loop 3CL-protease binder demo",
			ownerId: "user-1",
		};
		const recipeVersion = {
			bodyMarkdown: "search literature, search PDB, generate, fold, score",
			id: "77777777-7777-4777-8777-777777777777",
			recipeId: recipe.id,
			version: 1,
		};
		const runInsert = insertReturning(queuedRun);
		const messageInsert = insertReturning(message);
		const runRecipeInsert = insertReturning({
			id: "88888888-8888-4888-8888-888888888888",
		});
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(runInsert)
				.mockReturnValueOnce(messageInsert)
				.mockReturnValueOnce(runRecipeInsert),
			query: {
				recipeVersions: { findFirst: vi.fn().mockResolvedValue(recipeVersion) },
				recipes: { findFirst: vi.fn().mockResolvedValue(recipe) },
				threads: { findFirst: vi.fn().mockResolvedValue(thread) },
				workspaces: { findFirst: vi.fn().mockResolvedValue(workspace) },
			},
		};
		const launchRun = vi.fn().mockResolvedValue({
			backend: "modal",
			launched: true,
		});

		await createMessageRunWithLaunch({
			db: db as never,
			input: {
				prompt: message.content,
				recipeRefs: [recipe.id],
				taskKind: "branch_design",
				workspaceId: workspace.id,
			},
			launchRun,
			ownerId: "user-1",
		});

		expect(runRecipeInsert.values).toHaveBeenCalledWith({
			bodySnapshot: recipeVersion.bodyMarkdown,
			nameSnapshot: recipe.name,
			recipeId: recipe.id,
			recipeVersionId: recipeVersion.id,
			runId: queuedRun.id,
		});
	});

	it("does not launch when the linked user message cannot be inserted", async () => {
		const workspace = {
			activeThreadId: "33333333-3333-4333-8333-333333333333",
			id: "22222222-2222-4222-8222-222222222222",
			name: "3CL protease",
			ownerId: "user-1",
		};
		const thread = {
			id: workspace.activeThreadId,
			title: "Main thread",
			workspaceId: workspace.id,
		};
		const queuedRun = {
			createdById: "user-1",
			id: "11111111-1111-4111-8111-111111111111",
			prompt: "Continue with a folding run",
			status: "queued",
			taskKind: "chat",
			threadId: thread.id,
			workspaceId: workspace.id,
		};
		const runInsert = insertReturning(queuedRun);
		const messageInsert = insertReturningNoRows();
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(runInsert)
				.mockReturnValueOnce(messageInsert),
			query: {
				threads: { findFirst: vi.fn().mockResolvedValue(thread) },
				workspaces: { findFirst: vi.fn().mockResolvedValue(workspace) },
			},
		};
		const launchRun = vi.fn();

		await expect(
			createMessageRunWithLaunch({
				db: db as never,
				input: {
					prompt: queuedRun.prompt,
					workspaceId: workspace.id,
				},
				launchRun,
				ownerId: "user-1",
			}),
		).rejects.toThrow("Failed to create user message.");

		expect(launchRun).not.toHaveBeenCalled();
	});

	it("accepts smoke task kinds when called directly (internal smoke harness)", async () => {
		const workspace = {
			activeThreadId: "33333333-3333-4333-8333-333333333333",
			id: "22222222-2222-4222-8222-222222222222",
			name: "Smoke",
			ownerId: "user-1",
		};
		const thread = {
			id: workspace.activeThreadId,
			title: "Main thread",
			workspaceId: workspace.id,
		};
		const queuedRun = {
			createdById: "user-1",
			id: "11111111-1111-4111-8111-111111111111",
			prompt: "ping",
			status: "queued",
			taskKind: "smoke_chat",
			threadId: thread.id,
			workspaceId: workspace.id,
		};
		const message = {
			content: queuedRun.prompt,
			id: "44444444-4444-4444-8444-444444444444",
			role: "user",
			runId: queuedRun.id,
			threadId: thread.id,
		};
		const runInsert = insertReturning(queuedRun);
		const messageInsert = insertReturning(message);
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(runInsert)
				.mockReturnValueOnce(messageInsert),
			query: {
				threads: { findFirst: vi.fn().mockResolvedValue(thread) },
				workspaces: { findFirst: vi.fn().mockResolvedValue(workspace) },
			},
		};
		const launchRun = vi.fn().mockResolvedValue({
			backend: "modal",
			launched: true,
		});

		await createMessageRunWithLaunch({
			db: db as never,
			input: {
				prompt: queuedRun.prompt,
				taskKind: "smoke_chat",
				workspaceId: workspace.id,
			},
			launchRun,
			ownerId: "user-1",
		});

		expect(runInsert.values).toHaveBeenCalledWith(
			expect.objectContaining({
				taskKind: "smoke_chat",
			}),
		);
	});
});

describe("createProjectRunWithLaunch", () => {
	it("keeps the legacy project run wrapper while creating a message-backed run", async () => {
		const workspace = {
			description: null,
			id: "22222222-2222-4222-8222-222222222222",
			name: "Spike RBD binder",
			ownerId: "user-1",
		};
		const thread = {
			id: "33333333-3333-4333-8333-333333333333",
			title: "Main thread",
			workspaceId: workspace.id,
		};
		const updatedWorkspace = {
			...workspace,
			activeThreadId: thread.id,
		};
		const queuedRun = {
			createdById: "user-1",
			id: "11111111-1111-4111-8111-111111111111",
			prompt: "Design a protein binder for SARS-CoV-2 spike RBD",
			status: "queued",
			taskKind: "structure_search",
			threadId: thread.id,
			workspaceId: workspace.id,
		};
		const message = {
			content: queuedRun.prompt,
			id: "44444444-4444-4444-8444-444444444444",
			role: "user",
			runId: queuedRun.id,
			threadId: thread.id,
		};
		const workspaceInsert = insertReturning(workspace);
		const threadInsert = insertReturning(thread);
		const runInsert = insertReturning(queuedRun);
		const messageInsert = insertReturning(message);
		const workspaceUpdate = updateReturning(updatedWorkspace);
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(workspaceInsert)
				.mockReturnValueOnce(threadInsert)
				.mockReturnValueOnce(runInsert)
				.mockReturnValueOnce(messageInsert),
			update: vi.fn().mockReturnValueOnce({ set: workspaceUpdate.set }),
		};
		const launchRun = vi.fn().mockResolvedValue({
			backend: "modal",
			launched: true,
		});

		const result = await createProjectRunWithLaunch({
			db: db as never,
			input: {
				goal: message.content,
				name: workspace.name,
				topK: 5,
			},
			launchRun,
			ownerId: "user-1",
		});

		expect(runInsert.values).toHaveBeenCalledWith(
			expect.objectContaining({
				sdkStateJson: { requestedTopK: 5 },
				taskKind: "structure_search",
			}),
		);
		expect(workspaceInsert.values).toHaveBeenCalledWith({
			description: message.content,
			name: workspace.name,
			ownerId: "user-1",
		});
		expect(messageInsert.values).toHaveBeenCalledWith(
			expect.objectContaining({
				content: message.content,
				runId: queuedRun.id,
			}),
		);
		expect(result).toEqual({
			message,
			project: updatedWorkspace,
			run: queuedRun,
			thread,
			workspace: updatedWorkspace,
		});
	});
});
