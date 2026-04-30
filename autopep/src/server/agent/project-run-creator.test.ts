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

const sequenceSelect = (next: number) => {
	const where = vi.fn().mockResolvedValue([{ next }]);
	const from = vi.fn(() => ({ where }));
	const select = vi.fn(() => ({ from }));
	return { from, select, where };
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
		const promptText = queuedRun.prompt;
		const threadItem = {
			contentJson: { text: promptText, type: "input_text" },
			id: "44444444-4444-4444-8444-444444444444",
			itemType: "message",
			role: "user",
			runId: queuedRun.id,
			sequence: 1,
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
		const itemInsert = insertReturning(threadItem);
		const workspaceUpdate = updateReturning(updatedWorkspace);
		const seqSelect = sequenceSelect(1);
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(workspaceInsert)
				.mockReturnValueOnce(threadInsert)
				.mockReturnValueOnce(runInsert)
				.mockReturnValueOnce(itemInsert),
			select: seqSelect.select,
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
				prompt: promptText,
			},
			launchRun,
			ownerId: "user-1",
		});

		expect(runInsert.values).toHaveBeenCalledWith(
			expect.objectContaining({
				createdById: "user-1",
				prompt: promptText,
				rootRunId: null,
				status: "queued",
				taskKind: "chat",
				threadId: thread.id,
				workspaceId: workspace.id,
			}),
		);
		expect(itemInsert.values).toHaveBeenCalledWith({
			attachmentRefsJson: [],
			contentJson: { text: promptText, type: "input_text" },
			contextRefsJson: [],
			itemType: "message",
			recipeRefsJson: [],
			role: "user",
			runId: queuedRun.id,
			sequence: 1,
			threadId: thread.id,
		});
		expect(launchRun).toHaveBeenCalledWith({
			db,
			runId: queuedRun.id,
			threadId: thread.id,
			workspaceId: workspace.id,
		});
		expect(result).toEqual({
			run: failedRun,
			thread,
			threadItem,
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
		const promptText = queuedRun.prompt;
		const threadItem = {
			contentJson: { text: promptText, type: "input_text" },
			id: "44444444-4444-4444-8444-444444444444",
			itemType: "message",
			role: "user",
			runId: queuedRun.id,
			sequence: 2,
			threadId: thread.id,
		};
		const runInsert = insertReturning(queuedRun);
		const itemInsert = insertReturning(threadItem);
		const seqSelect = sequenceSelect(2);
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(runInsert)
				.mockReturnValueOnce(itemInsert),
			query: {
				contextReferences: { findMany: vi.fn().mockResolvedValue([]) },
				recipeVersions: { findFirst: vi.fn() },
				recipes: { findFirst: vi.fn() },
				threads: { findFirst: vi.fn().mockResolvedValue(thread) },
				workspaces: { findFirst: vi.fn().mockResolvedValue(workspace) },
			},
			select: seqSelect.select,
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
				prompt: promptText,
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
		expect(itemInsert.values).toHaveBeenCalledWith({
			attachmentRefsJson: ["77777777-7777-4777-8777-777777777777"],
			contentJson: { text: promptText, type: "input_text" },
			contextRefsJson: ["55555555-5555-4555-8555-555555555555"],
			itemType: "message",
			recipeRefsJson: ["66666666-6666-4666-8666-666666666666"],
			role: "user",
			runId: queuedRun.id,
			sequence: 2,
			threadId: thread.id,
		});
		expect(launchRun).toHaveBeenCalledWith({
			db,
			runId: queuedRun.id,
			threadId: thread.id,
			workspaceId: workspace.id,
		});
		expect(result).toEqual({
			run: queuedRun,
			thread,
			threadItem,
			workspace,
		});
	});

	it("materializes selected context references into the launched run prompt", async () => {
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
		const reference = {
			artifactId: "11111111-1111-4111-8111-111111111111",
			candidateId: "33333333-3333-4333-8333-333333333333",
			id: "55555555-5555-4555-8555-555555555555",
			kind: "protein_selection",
			label: "6M0J chain A residue 145",
			selectorJson: {
				authAsymId: "A",
				residueRanges: [{ end: 145, start: 145 }],
			},
			workspaceId: workspace.id,
		};
		const expectedPrompt = [
			"Explain this region",
			"",
			"Selected workspace context:",
			"- 6M0J chain A residue 145 [protein_selection] (artifactId: 11111111-1111-4111-8111-111111111111, candidateId: 33333333-3333-4333-8333-333333333333)",
			'  selector: {"authAsymId":"A","residueRanges":[{"end":145,"start":145}]}',
		].join("\n");
		const queuedRun = {
			createdById: "user-1",
			id: "11111111-1111-4111-8111-111111111111",
			prompt: expectedPrompt,
			status: "queued",
			taskKind: "chat",
			threadId: thread.id,
			workspaceId: workspace.id,
		};
		const userPrompt = "Explain this region";
		const threadItem = {
			contentJson: { text: userPrompt, type: "input_text" },
			id: "44444444-4444-4444-8444-444444444444",
			itemType: "message",
			role: "user",
			runId: queuedRun.id,
			sequence: 1,
			threadId: thread.id,
		};
		const runInsert = insertReturning(queuedRun);
		const itemInsert = insertReturning(threadItem);
		const contextReferencesFindMany = vi.fn().mockResolvedValue([reference]);
		const seqSelect = sequenceSelect(1);
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(runInsert)
				.mockReturnValueOnce(itemInsert),
			query: {
				contextReferences: { findMany: contextReferencesFindMany },
				threads: { findFirst: vi.fn().mockResolvedValue(thread) },
				workspaces: { findFirst: vi.fn().mockResolvedValue(workspace) },
			},
			select: seqSelect.select,
		};
		const launchRun = vi.fn().mockResolvedValue({
			backend: "modal",
			launched: true,
		});

		await createMessageRunWithLaunch({
			db: db as never,
			input: {
				contextRefs: [reference.id],
				prompt: userPrompt,
				workspaceId: workspace.id,
			},
			launchRun,
			ownerId: "user-1",
		});

		expect(runInsert.values).toHaveBeenCalledWith(
			expect.objectContaining({
				prompt: expectedPrompt,
			}),
		);
		expect(itemInsert.values).toHaveBeenCalledWith(
			expect.objectContaining({
				contentJson: { text: userPrompt, type: "input_text" },
				contextRefsJson: [reference.id],
			}),
		);
		expect(contextReferencesFindMany).toHaveBeenCalledOnce();
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
			taskKind: "chat",
			threadId: thread.id,
			workspaceId: workspace.id,
		};
		const threadItem = {
			contentJson: { text: queuedRun.prompt, type: "input_text" },
			id: "44444444-4444-4444-8444-444444444444",
			itemType: "message",
			role: "user",
			runId: queuedRun.id,
			sequence: 1,
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
		const itemInsert = insertReturning(threadItem);
		const runRecipeInsert = insertReturning({
			id: "88888888-8888-4888-8888-888888888888",
		});
		const seqSelect = sequenceSelect(1);
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(runInsert)
				.mockReturnValueOnce(itemInsert)
				.mockReturnValueOnce(runRecipeInsert),
			query: {
				recipeVersions: { findFirst: vi.fn().mockResolvedValue(recipeVersion) },
				recipes: { findFirst: vi.fn().mockResolvedValue(recipe) },
				threads: { findFirst: vi.fn().mockResolvedValue(thread) },
				workspaces: { findFirst: vi.fn().mockResolvedValue(workspace) },
			},
			select: seqSelect.select,
		};
		const launchRun = vi.fn().mockResolvedValue({
			backend: "modal",
			launched: true,
		});

		await createMessageRunWithLaunch({
			db: db as never,
			input: {
				prompt: queuedRun.prompt,
				recipeRefs: [recipe.id],
				taskKind: "chat",
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
		const itemInsert = insertReturningNoRows();
		const seqSelect = sequenceSelect(1);
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(runInsert)
				.mockReturnValueOnce(itemInsert),
			query: {
				threads: { findFirst: vi.fn().mockResolvedValue(thread) },
				workspaces: { findFirst: vi.fn().mockResolvedValue(workspace) },
			},
			select: seqSelect.select,
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
		const threadItem = {
			contentJson: { text: queuedRun.prompt, type: "input_text" },
			id: "44444444-4444-4444-8444-444444444444",
			itemType: "message",
			role: "user",
			runId: queuedRun.id,
			sequence: 1,
			threadId: thread.id,
		};
		const runInsert = insertReturning(queuedRun);
		const itemInsert = insertReturning(threadItem);
		const seqSelect = sequenceSelect(1);
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(runInsert)
				.mockReturnValueOnce(itemInsert),
			query: {
				threads: { findFirst: vi.fn().mockResolvedValue(thread) },
				workspaces: { findFirst: vi.fn().mockResolvedValue(workspace) },
			},
			select: seqSelect.select,
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
		const threadItem = {
			contentJson: { text: queuedRun.prompt, type: "input_text" },
			id: "44444444-4444-4444-8444-444444444444",
			itemType: "message",
			role: "user",
			runId: queuedRun.id,
			sequence: 1,
			threadId: thread.id,
		};
		const workspaceInsert = insertReturning(workspace);
		const threadInsert = insertReturning(thread);
		const runInsert = insertReturning(queuedRun);
		const itemInsert = insertReturning(threadItem);
		const workspaceUpdate = updateReturning(updatedWorkspace);
		const seqSelect = sequenceSelect(1);
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(workspaceInsert)
				.mockReturnValueOnce(threadInsert)
				.mockReturnValueOnce(runInsert)
				.mockReturnValueOnce(itemInsert),
			select: seqSelect.select,
			update: vi.fn().mockReturnValueOnce({ set: workspaceUpdate.set }),
		};
		const launchRun = vi.fn().mockResolvedValue({
			backend: "modal",
			launched: true,
		});

		const result = await createProjectRunWithLaunch({
			db: db as never,
			input: {
				goal: queuedRun.prompt,
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
			description: queuedRun.prompt,
			name: workspace.name,
			ownerId: "user-1",
		});
		expect(itemInsert.values).toHaveBeenCalledWith(
			expect.objectContaining({
				contentJson: { text: queuedRun.prompt, type: "input_text" },
				runId: queuedRun.id,
			}),
		);
		expect(result).toEqual({
			project: updatedWorkspace,
			run: queuedRun,
			thread,
			threadItem,
			workspace: updatedWorkspace,
		});
	});
});
