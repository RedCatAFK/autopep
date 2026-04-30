import { describe, expect, it, vi } from "vitest";

import {
	createMessageRunWithLaunch,
	createProjectRunWithLaunch,
} from "@/server/agent/project-run-creator";
import { createCallerFactory } from "@/server/api/trpc";
import { r2ArtifactStore } from "@/server/artifacts/r2";
import {
	agentEvents,
	agentRuns,
	artifacts,
	workspaces,
} from "@/server/db/schema";
import { getWorkspacePayload, workspaceRouter } from "./workspace";

vi.mock("@/server/agent/project-run-creator", () => ({
	createMessageRunWithLaunch: vi.fn(),
	createProjectRunWithLaunch: vi.fn(),
}));

vi.mock("@/server/artifacts/r2", () => ({
	r2ArtifactStore: {
		deleteObject: vi.fn(),
		getReadUrl: vi.fn().mockResolvedValue("https://signed.example/read-url"),
		getUploadUrl: vi
			.fn()
			.mockResolvedValue("https://signed.example/upload-url"),
		objectExists: vi.fn().mockResolvedValue(true),
		readObjectText: vi.fn(),
		upload: vi.fn(),
	},
}));

const expressionReferences = (
	expression: unknown,
	expected: unknown,
	seen = new Set<unknown>(),
): boolean => {
	if (expression === expected) {
		return true;
	}
	if (!expression || typeof expression !== "object") {
		return false;
	}
	if (seen.has(expression)) {
		return false;
	}
	seen.add(expression);

	const { queryChunks, value } = expression as {
		queryChunks?: unknown[];
		value?: unknown;
	};

	if (queryChunks) {
		for (const chunk of queryChunks) {
			if (expressionReferences(chunk, expected, seen)) {
				return true;
			}
		}
	}

	if (value && expressionReferences(value, expected, seen)) {
		return true;
	}

	if (Array.isArray(expression)) {
		for (const value of expression) {
			if (expressionReferences(value, expected, seen)) {
				return true;
			}
		}
	}

	if (Array.isArray(value)) {
		for (const item of value) {
			if (expressionReferences(item, expected, seen)) {
				return true;
			}
		}
	}

	if (value === expected) {
		return true;
	}

	return false;
};

const expressionContainsText = (
	expression: unknown,
	expected: string,
	seen = new Set<unknown>(),
): boolean => {
	if (!expression || typeof expression !== "object") {
		return false;
	}
	if (seen.has(expression)) {
		return false;
	}
	seen.add(expression);

	const { queryChunks, value } = expression as {
		queryChunks?: unknown[];
		value?: unknown;
	};

	if (Array.isArray(value) && value.some((item) => item === expected)) {
		return true;
	}

	if (queryChunks) {
		for (const chunk of queryChunks) {
			if (expressionContainsText(chunk, expected, seen)) {
				return true;
			}
		}
	}

	if (Array.isArray(expression)) {
		for (const value of expression) {
			if (expressionContainsText(value, expected, seen)) {
				return true;
			}
		}
	}

	if (value && typeof value === "object") {
		if (expressionContainsText(value, expected, seen)) {
			return true;
		}
	}

	return false;
};

const emptyFindMany = () => vi.fn().mockResolvedValue([]);

const insertReturning = (row: unknown) => {
	const returning = vi.fn().mockResolvedValue([row]);
	const values = vi.fn(() => ({ returning }));
	return { returning, values };
};

const deleteCapturing = () => {
	const where = vi.fn().mockResolvedValue(undefined);
	return { where };
};

const updateReturning = (row: unknown) => {
	const returning = vi.fn().mockResolvedValue([row]);
	const where = vi.fn((condition: unknown) => {
		void condition;
		return { returning };
	});
	const set = vi.fn(() => ({ where }));
	return { returning, set, where };
};

const createWorkspaceCaller = (db: unknown) =>
	createCallerFactory(workspaceRouter)({
		db,
		headers: new Headers(),
		session: { user: { id: "user-1" } },
	} as never);

describe("workspace router procedures", () => {
	it("exposes workspace-centered procedures alongside compatibility aliases", () => {
		expect(Object.keys(workspaceRouter._def.procedures)).toEqual(
			expect.arrayContaining([
				"archiveWorkspace",
				"archiveRecipe",
				"confirmAttachment",
				"createAttachment",
				"createContextReference",
				"createProjectRun",
				"createRecipe",
				"createWorkspace",
				"deleteAttachment",
				"getLatestWorkspace",
				"getRunEvents",
				"getWorkspace",
				"listRecipes",
				"listWorkspaces",
				"mintRunStreamToken",
				"renameWorkspace",
				"sendMessage",
				"updateRecipe",
			]),
		);
	});

	it("lists workspaces for the authenticated owner", async () => {
		const workspace = {
			id: "22222222-2222-4222-8222-222222222222",
			ownerId: "user-1",
		};
		const findMany = vi.fn().mockResolvedValue([workspace]);
		const caller = createWorkspaceCaller({
			query: {
				workspaces: { findMany },
			},
		});

		await expect(caller.listWorkspaces()).resolves.toEqual([workspace]);

		const where = findMany.mock.calls[0]?.[0].where;
		expect(expressionReferences(where, workspaces.ownerId)).toBe(true);
		expect(expressionReferences(where, workspaces.archivedAt)).toBe(true);
		expect(expressionContainsText(where, " is null")).toBe(true);
	});

	it("creates a workspace through the repository helper", async () => {
		const workspace = {
			description: "3CL protease objective",
			id: "22222222-2222-4222-8222-222222222222",
			name: "3CL protease",
			ownerId: "user-1",
		};
		const thread = {
			id: "33333333-3333-4333-8333-333333333333",
			title: "Main thread",
			workspaceId: workspace.id,
		};
		const updatedWorkspace = { ...workspace, activeThreadId: thread.id };
		const workspaceInsert = insertReturning(workspace);
		const threadInsert = insertReturning(thread);
		const workspaceUpdate = updateReturning(updatedWorkspace);
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(workspaceInsert)
				.mockReturnValueOnce(threadInsert),
			update: vi.fn().mockReturnValueOnce({ set: workspaceUpdate.set }),
		};
		const caller = createWorkspaceCaller(db);

		await expect(
			caller.createWorkspace({
				description: workspace.description,
				name: workspace.name,
			}),
		).resolves.toEqual({ thread, workspace: updatedWorkspace });

		expect(workspaceInsert.values).toHaveBeenCalledWith({
			description: workspace.description,
			name: workspace.name,
			ownerId: "user-1",
		});
		expect(threadInsert.values).toHaveBeenCalledWith({
			title: "Main thread",
			workspaceId: workspace.id,
		});
	});

	it("renames an owned non-archived workspace", async () => {
		const renamed = {
			id: "22222222-2222-4222-8222-222222222222",
			name: "Renamed workspace",
			ownerId: "user-1",
		};
		const workspaceUpdate = updateReturning(renamed);
		const db = {
			update: vi.fn().mockReturnValueOnce({ set: workspaceUpdate.set }),
		};
		const caller = createWorkspaceCaller(db);

		await expect(
			caller.renameWorkspace({
				name: renamed.name,
				workspaceId: renamed.id,
			}),
		).resolves.toEqual(renamed);

		expect(workspaceUpdate.set).toHaveBeenCalledWith({ name: renamed.name });
		const where = workspaceUpdate.where.mock.calls[0]?.[0];
		expect(expressionReferences(where, workspaces.id)).toBe(true);
		expect(expressionReferences(where, workspaces.ownerId)).toBe(true);
		expect(expressionReferences(where, workspaces.archivedAt)).toBe(true);
	});

	it("rejects renaming a workspace not owned by the caller", async () => {
		const returning = vi.fn().mockResolvedValue([]);
		const where = vi.fn(() => ({ returning }));
		const set = vi.fn(() => ({ where }));
		const db = {
			update: vi.fn().mockReturnValueOnce({ set }),
		};
		const caller = createWorkspaceCaller(db);

		await expect(
			caller.renameWorkspace({
				name: "Renamed workspace",
				workspaceId: "22222222-2222-4222-8222-222222222222",
			}),
		).rejects.toMatchObject({ code: "NOT_FOUND" });
	});

	it("archives an owned workspace", async () => {
		const archived = {
			archivedAt: new Date("2026-04-29T00:00:00.000Z"),
			id: "22222222-2222-4222-8222-222222222222",
			name: "Archived workspace",
			ownerId: "user-1",
		};
		const workspaceUpdate = updateReturning(archived);
		const db = {
			update: vi.fn().mockReturnValueOnce({ set: workspaceUpdate.set }),
		};
		const caller = createWorkspaceCaller(db);

		await expect(
			caller.archiveWorkspace({
				workspaceId: archived.id,
			}),
		).resolves.toEqual(archived);

		expect(workspaceUpdate.set).toHaveBeenCalledWith({
			archivedAt: expect.any(Date),
		});
		const where = workspaceUpdate.where.mock.calls[0]?.[0];
		expect(expressionReferences(where, workspaces.id)).toBe(true);
		expect(expressionReferences(where, workspaces.ownerId)).toBe(true);
	});

	it("sends a workspace message through the message run creator", async () => {
		const created = {
			message: { id: "44444444-4444-4444-8444-444444444444" },
			run: { id: "11111111-1111-4111-8111-111111111111" },
			thread: { id: "33333333-3333-4333-8333-333333333333" },
			workspace: { id: "22222222-2222-4222-8222-222222222222" },
		};
		vi.mocked(createMessageRunWithLaunch).mockResolvedValueOnce(
			created as never,
		);
		const db = {};
		const caller = createWorkspaceCaller(db);

		await expect(
			caller.sendMessage({
				contextRefs: ["55555555-5555-4555-8555-555555555555"],
				prompt: "Prepare the selected 3CL protease structure",
				workspaceId: "22222222-2222-4222-8222-222222222222",
			}),
		).resolves.toEqual(created);

		expect(createMessageRunWithLaunch).toHaveBeenCalledWith({
			db,
			input: {
				attachmentRefs: [],
				contextRefs: ["55555555-5555-4555-8555-555555555555"],
				prompt: "Prepare the selected 3CL protease structure",
				recipeRefs: [],
				taskKind: "chat",
				workspaceId: "22222222-2222-4222-8222-222222222222",
			},
			ownerId: "user-1",
		});
	});

	it("creates a protein selection context reference in an owned workspace", async () => {
		const workspace = {
			id: "22222222-2222-4222-8222-222222222222",
			ownerId: "user-1",
		};
		const reference = {
			artifactId: "11111111-1111-4111-8111-111111111111",
			candidateId: "33333333-3333-4333-8333-333333333333",
			createdById: "user-1",
			id: "55555555-5555-4555-8555-555555555555",
			kind: "protein_selection",
			label: "6M0J chain A residues 41-145",
			selectorJson: {
				authAsymId: "A",
				residueRanges: [{ end: 145, start: 41 }],
			},
			workspaceId: workspace.id,
		};
		const referenceInsert = insertReturning(reference);
		const workspaceFindFirst = vi.fn().mockResolvedValue(workspace);
		const caller = createWorkspaceCaller({
			insert: vi.fn().mockReturnValueOnce(referenceInsert),
			query: {
				workspaces: { findFirst: workspaceFindFirst },
			},
		});

		await expect(
			caller.createContextReference({
				artifactId: reference.artifactId,
				candidateId: reference.candidateId,
				kind: "protein_selection",
				label: reference.label,
				selector: reference.selectorJson,
				workspaceId: workspace.id,
			}),
		).resolves.toEqual(reference);

		expect(referenceInsert.values).toHaveBeenCalledWith({
			artifactId: reference.artifactId,
			candidateId: reference.candidateId,
			createdById: "user-1",
			kind: "protein_selection",
			label: reference.label,
			selectorJson: reference.selectorJson,
			workspaceId: workspace.id,
		});
		const where = workspaceFindFirst.mock.calls[0]?.[0].where;
		expect(expressionReferences(where, workspaces.id)).toBe(true);
		expect(expressionReferences(where, workspaces.ownerId)).toBe(true);
	});

	it("creates a recipe and first version for an owned workspace", async () => {
		const workspace = {
			id: "22222222-2222-4222-8222-222222222222",
			ownerId: "user-1",
		};
		const recipe = {
			bodyMarkdown: "Search comparable structures first.",
			description: null,
			enabledByDefault: true,
			id: "66666666-6666-4666-8666-666666666666",
			name: "Literature-first generation",
			ownerId: "user-1",
			workspaceId: workspace.id,
		};
		const version = {
			bodyMarkdown: recipe.bodyMarkdown,
			createdById: "user-1",
			id: "77777777-7777-4777-8777-777777777777",
			recipeId: recipe.id,
			version: 1,
		};
		const recipeInsert = insertReturning(recipe);
		const versionInsert = insertReturning(version);
		const caller = createWorkspaceCaller({
			insert: vi
				.fn()
				.mockReturnValueOnce(recipeInsert)
				.mockReturnValueOnce(versionInsert),
			query: {
				workspaces: { findFirst: vi.fn().mockResolvedValue(workspace) },
			},
		});

		await expect(
			caller.createRecipe({
				bodyMarkdown: recipe.bodyMarkdown,
				enabledByDefault: true,
				name: recipe.name,
				workspaceId: workspace.id,
			}),
		).resolves.toEqual({ recipe, version });

		expect(recipeInsert.values).toHaveBeenCalledWith({
			bodyMarkdown: recipe.bodyMarkdown,
			description: null,
			enabledByDefault: true,
			name: recipe.name,
			ownerId: "user-1",
			workspaceId: workspace.id,
		});
		expect(versionInsert.values).toHaveBeenCalledWith({
			bodyMarkdown: recipe.bodyMarkdown,
			createdById: "user-1",
			recipeId: recipe.id,
			version: 1,
		});
	});

	it("creates the workspace + thread + run when sendMessage has no workspaceId", async () => {
		const created = {
			message: { id: "44444444-4444-4444-8444-444444444444" },
			run: { id: "11111111-1111-4111-8111-111111111111" },
			thread: { id: "33333333-3333-4333-8333-333333333333" },
			workspace: { id: "22222222-2222-4222-8222-222222222222" },
		};
		vi.mocked(createMessageRunWithLaunch).mockResolvedValueOnce(
			created as never,
		);
		const db = {};
		const caller = createWorkspaceCaller(db);

		await expect(
			caller.sendMessage({
				prompt: "Investigate SARS-CoV-2 spike binders",
			}),
		).resolves.toEqual(created);

		expect(createMessageRunWithLaunch).toHaveBeenCalledWith({
			db,
			input: expect.objectContaining({
				prompt: "Investigate SARS-CoV-2 spike binders",
				workspaceId: undefined,
			}),
			ownerId: "user-1",
		});
		const callArgs = vi.mocked(createMessageRunWithLaunch).mock.calls.at(-1);
		const inputArg = callArgs?.[0]?.input as
			| (Record<string, unknown> | undefined)
			| undefined;
		expect(inputArg?.projectId).toBeUndefined();
		expect(inputArg?.workspaceId).toBeUndefined();
	});

	it("maps legacy projectId to workspaceId when sending a message", async () => {
		const created = {
			message: { id: "44444444-4444-4444-8444-444444444444" },
			run: { id: "11111111-1111-4111-8111-111111111111" },
			thread: { id: "33333333-3333-4333-8333-333333333333" },
			workspace: { id: "22222222-2222-4222-8222-222222222222" },
		};
		vi.mocked(createMessageRunWithLaunch).mockResolvedValueOnce(
			created as never,
		);
		const db = {};
		const caller = createWorkspaceCaller(db);

		await caller.sendMessage({
			projectId: "22222222-2222-4222-8222-222222222222",
			prompt: "Continue this workspace",
		});

		expect(createMessageRunWithLaunch).toHaveBeenCalledWith({
			db,
			input: expect.objectContaining({
				projectId: "22222222-2222-4222-8222-222222222222",
				workspaceId: "22222222-2222-4222-8222-222222222222",
			}),
			ownerId: "user-1",
		});
	});

	it("rejects smoke task kinds through the public sendMessage route", async () => {
		vi.mocked(createMessageRunWithLaunch).mockClear();
		const caller = createWorkspaceCaller({});

		await expect(
			caller.sendMessage({
				prompt: "ping",
				taskKind: "smoke_chat" as never,
				workspaceId: "22222222-2222-4222-8222-222222222222",
			}),
		).rejects.toThrow();

		expect(createMessageRunWithLaunch).not.toHaveBeenCalled();
	});

	it("does not fall back to another workspace when a requested answer workspace is missing", async () => {
		const findFirst = vi.fn().mockResolvedValue(null);
		const caller = createWorkspaceCaller({
			query: {
				workspaces: { findFirst },
			},
		});

		await expect(
			caller.answerQuestion({
				projectId: "22222222-2222-4222-8222-222222222222",
				question: "What is the status?",
			}),
		).resolves.toEqual({
			answer:
				"No retrieval run has been started yet. Start with a target goal and I can summarize structures, literature evidence, and CIF readiness once the worker writes results.",
		});

		expect(findFirst).toHaveBeenCalledOnce();
	});

	it("loads a workspace payload through the getWorkspace procedure", async () => {
		const workspace = {
			activeThreadId: "33333333-3333-4333-8333-333333333333",
			description: "Original objective",
			id: "22222222-2222-4222-8222-222222222222",
			name: "3CL protease",
			ownerId: "user-1",
		};
		const thread = {
			id: workspace.activeThreadId,
			title: "Main thread",
			workspaceId: workspace.id,
		};
		const db = {
			query: {
				agentEvents: { findMany: emptyFindMany() },
				agentRuns: { findMany: emptyFindMany() },
				artifacts: { findMany: emptyFindMany() },
				candidateScores: { findMany: emptyFindMany() },
				contextReferences: { findMany: emptyFindMany() },
				messages: { findMany: emptyFindMany() },
				proteinCandidates: { findMany: emptyFindMany() },
				recipes: { findMany: emptyFindMany() },
				threads: { findMany: vi.fn().mockResolvedValue([thread]) },
				workspaces: { findFirst: vi.fn().mockResolvedValue(workspace) },
			},
		};
		const caller = createWorkspaceCaller(db);

		const payload = await caller.getWorkspace({ workspaceId: workspace.id });

		expect(payload?.workspace).toEqual(workspace);
		expect(payload?.project.goal).toBe("Original objective");
		const where = db.query.workspaces.findFirst.mock.calls[0]?.[0].where;
		expect(expressionReferences(where, workspaces.id)).toBe(true);
		expect(expressionReferences(where, workspaces.ownerId)).toBe(true);
	});

	it("returns iso createdAt timestamps and a runs summary on the workspace payload", async () => {
		const workspace = {
			activeThreadId: "33333333-3333-4333-8333-333333333333",
			description: "Workspace with traffic",
			id: "22222222-2222-4222-8222-222222222222",
			name: "Active workspace",
			ownerId: "user-1",
		};
		const thread = {
			id: workspace.activeThreadId,
			title: "Main thread",
			workspaceId: workspace.id,
		};
		const run = {
			createdAt: new Date("2026-04-29T11:55:00.000Z"),
			finishedAt: null,
			id: "11111111-1111-4111-8111-111111111111",
			prompt: "Investigate the active goal",
			startedAt: new Date("2026-04-29T12:00:00.000Z"),
			status: "running",
			threadId: thread.id,
			workspaceId: workspace.id,
		};
		const olderRun = {
			createdAt: new Date("2026-04-28T11:55:00.000Z"),
			finishedAt: new Date("2026-04-28T12:30:00.000Z"),
			id: "11111111-1111-4111-8111-111111111112",
			prompt: "Earlier exploration",
			startedAt: new Date("2026-04-28T12:00:00.000Z"),
			status: "completed",
			threadId: thread.id,
			workspaceId: workspace.id,
		};
		const message = {
			content: "Hello",
			createdAt: new Date("2026-04-29T12:01:00.000Z"),
			id: "44444444-4444-4444-8444-444444444444",
			role: "user",
			threadId: thread.id,
		};
		const event = {
			createdAt: new Date("2026-04-29T12:02:00.000Z"),
			displayJson: { step: "launch" },
			id: "99999999-9999-4999-8999-999999999999",
			runId: run.id,
			sequence: 1,
			summary: "Started",
			title: "Run started",
			type: "run_started",
		};
		const db = {
			query: {
				agentEvents: { findMany: vi.fn().mockResolvedValue([event]) },
				agentRuns: { findMany: vi.fn().mockResolvedValue([run, olderRun]) },
				artifacts: { findMany: emptyFindMany() },
				candidateScores: { findMany: emptyFindMany() },
				contextReferences: { findMany: emptyFindMany() },
				messages: { findMany: vi.fn().mockResolvedValue([message]) },
				proteinCandidates: { findMany: emptyFindMany() },
				recipes: { findMany: emptyFindMany() },
				threads: { findMany: vi.fn().mockResolvedValue([thread]) },
				workspaces: { findFirst: vi.fn().mockResolvedValue(workspace) },
			},
		};
		const caller = createWorkspaceCaller(db);

		const payload = await caller.getWorkspace({ workspaceId: workspace.id });

		expect(typeof payload?.messages[0]?.createdAt).toBe("string");
		expect(payload?.messages[0]?.createdAt).toBe(message.createdAt.toISOString());
		expect(typeof payload?.events[0]?.createdAt).toBe("string");
		expect(payload?.events[0]?.createdAt).toBe(event.createdAt.toISOString());

		expect(payload?.runs.length).toBeGreaterThanOrEqual(1);
		const firstRun = payload?.runs[0];
		expect(firstRun?.id).toMatch(
			/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
		);
		expect([
			"queued",
			"running",
			"paused",
			"completed",
			"failed",
			"cancelled",
		]).toContain(firstRun?.status);
		expect(
			firstRun?.startedAt === null || typeof firstRun?.startedAt === "string",
		).toBe(true);
		expect(firstRun?.startedAt).toBe(run.startedAt.toISOString());
		expect(payload?.runs[1]?.startedAt).toBe(olderRun.startedAt.toISOString());
	});

	it("loads the latest workspace payload for the authenticated owner", async () => {
		const workspace = {
			activeThreadId: "33333333-3333-4333-8333-333333333333",
			description: "Latest objective",
			id: "22222222-2222-4222-8222-222222222222",
			name: "Latest workspace",
			ownerId: "user-1",
		};
		const thread = {
			id: workspace.activeThreadId,
			title: "Main thread",
			workspaceId: workspace.id,
		};
		const workspaceFindFirst = vi
			.fn()
			.mockResolvedValueOnce(workspace)
			.mockResolvedValueOnce(workspace);
		const db = {
			query: {
				agentEvents: { findMany: emptyFindMany() },
				agentRuns: { findMany: emptyFindMany() },
				artifacts: { findMany: emptyFindMany() },
				candidateScores: { findMany: emptyFindMany() },
				contextReferences: { findMany: emptyFindMany() },
				messages: { findMany: emptyFindMany() },
				proteinCandidates: { findMany: emptyFindMany() },
				recipes: { findMany: emptyFindMany() },
				threads: { findMany: vi.fn().mockResolvedValue([thread]) },
				workspaces: { findFirst: workspaceFindFirst },
			},
		};
		const caller = createWorkspaceCaller(db);

		const payload = await caller.getLatestWorkspace();

		expect(payload?.workspace).toEqual(workspace);
		expect(workspaceFindFirst).toHaveBeenCalledTimes(2);
		const latestWhere = workspaceFindFirst.mock.calls[0]?.[0].where;
		expect(expressionReferences(latestWhere, workspaces.ownerId)).toBe(true);
		expect(expressionReferences(latestWhere, workspaces.archivedAt)).toBe(true);
	});

	it("keeps the legacy project run mutation as an adapter", async () => {
		const created = {
			project: { id: "22222222-2222-4222-8222-222222222222" },
			run: { id: "11111111-1111-4111-8111-111111111111" },
		};
		vi.mocked(createProjectRunWithLaunch).mockResolvedValueOnce(
			created as never,
		);
		const db = {};
		const caller = createWorkspaceCaller(db);

		await expect(
			caller.createProjectRun({
				goal: "Design a protein binder for SARS-CoV-2 spike RBD",
				name: "Spike RBD binder",
				topK: 5,
			}),
		).resolves.toEqual(created);

		expect(createProjectRunWithLaunch).toHaveBeenCalledWith({
			db,
			input: {
				goal: "Design a protein binder for SARS-CoV-2 spike RBD",
				name: "Spike RBD binder",
				topK: 5,
			},
			ownerId: "user-1",
		});
	});

	it("loads run events only after confirming workspace ownership", async () => {
		const event = {
			createdAt: new Date("2026-04-29T12:00:00.000Z"),
			displayJson: { step: "launch" },
			id: "99999999-9999-4999-8999-999999999999",
			runId: "11111111-1111-4111-8111-111111111111",
			sequence: 2,
			summary: "Started",
			title: "Run started",
			type: "run_started",
		};
		const limit = vi.fn().mockResolvedValue([{ id: event.runId }]);
		const where = vi.fn((condition: unknown) => {
			void condition;
			return { limit };
		});
		const innerJoin = vi.fn(() => ({ where }));
		const from = vi.fn(() => ({ innerJoin }));
		const db = {
			query: {
				agentEvents: { findMany: vi.fn().mockResolvedValue([event]) },
			},
			select: vi.fn(() => ({ from })),
		};
		const caller = createWorkspaceCaller(db);

		await expect(
			caller.getRunEvents({
				afterSequence: 1,
				runId: event.runId,
			}),
		).resolves.toEqual([
			{
				...event,
				createdAt: event.createdAt.toISOString(),
				detail: "Started",
				payloadJson: { step: "launch" },
			},
		]);

		const ownerScopedWhere = where.mock.calls[0]?.[0];
		expect(expressionReferences(ownerScopedWhere, agentRuns.id)).toBe(true);
		expect(expressionReferences(ownerScopedWhere, workspaces.ownerId)).toBe(
			true,
		);
		expect(db.query.agentEvents.findMany).toHaveBeenCalledOnce();
	});

	it("does not read event rows when the run is outside the owner scope", async () => {
		const limit = vi.fn().mockResolvedValue([]);
		const where = vi.fn(() => ({ limit }));
		const innerJoin = vi.fn(() => ({ where }));
		const from = vi.fn(() => ({ innerJoin }));
		const db = {
			query: {
				agentEvents: { findMany: vi.fn() },
			},
			select: vi.fn(() => ({ from })),
		};
		const caller = createWorkspaceCaller(db);

		await expect(
			caller.getRunEvents({
				afterSequence: 0,
				runId: "11111111-1111-4111-8111-111111111111",
			}),
		).resolves.toEqual([]);

		expect(db.query.agentEvents.findMany).not.toHaveBeenCalled();
	});

	it("returns events with sequence > sinceSequence", async () => {
		const runId = "11111111-1111-4111-8111-111111111111";
		const workspaceId = "22222222-2222-4222-8222-222222222222";
		const run = {
			id: runId,
			status: "running" as const,
			workspaceId,
		};
		const workspace = {
			id: workspaceId,
			ownerId: "user-1",
		};
		const allEvents = [1, 2, 3, 4, 5].map((sequence) => ({
			createdAt: new Date(`2026-04-29T12:0${sequence}:00.000Z`),
			displayJson: { step: `step-${sequence}` },
			id: `99999999-9999-4999-8999-99999999999${sequence}`,
			payloadJson: {},
			rawJson: { raw: sequence },
			runId,
			sequence,
			summary: `Summary ${sequence}`,
			title: `Title ${sequence}`,
			type: "step",
		}));
		const filteredEvents = allEvents.filter((event) => event.sequence > 3);

		const orderBy = vi.fn().mockResolvedValue(filteredEvents);
		const where = vi.fn((_condition: unknown) => ({ orderBy }));
		const from = vi.fn(() => ({ where }));
		const runFindFirst = vi.fn().mockResolvedValue(run);
		const workspaceFindFirst = vi.fn().mockResolvedValue(workspace);
		const db = {
			query: {
				agentRuns: { findFirst: runFindFirst },
				workspaces: { findFirst: workspaceFindFirst },
			},
			select: vi.fn(() => ({ from })),
		};
		const caller = createWorkspaceCaller(db);

		const result = await caller.streamEvents({
			runId,
			sinceSequence: 3,
		});

		expect(result.runStatus).toBe("running");
		expect(result.events.map((event) => event.sequence)).toEqual([4, 5]);
		expect(result.events[0]).toEqual(
			expect.objectContaining({
				createdAt: filteredEvents[0]?.createdAt.toISOString(),
				displayJson: { step: "step-4" },
				rawJson: { raw: 4 },
				sequence: 4,
				summary: "Summary 4",
				title: "Title 4",
				type: "step",
			}),
		);

		const runWhere = runFindFirst.mock.calls[0]?.[0].where;
		expect(expressionReferences(runWhere, agentRuns.id)).toBe(true);
		const workspaceWhere = workspaceFindFirst.mock.calls[0]?.[0].where;
		expect(expressionReferences(workspaceWhere, workspaces.id)).toBe(true);
		expect(expressionReferences(workspaceWhere, workspaces.ownerId)).toBe(
			true,
		);
		const eventsWhere = where.mock.calls[0]?.[0];
		expect(expressionReferences(eventsWhere, agentEvents.runId)).toBe(true);
		expect(expressionReferences(eventsWhere, agentEvents.sequence)).toBe(true);
	});

	it("rejects streamEvents when the run is owned by another user", async () => {
		const runId = "11111111-1111-4111-8111-111111111111";
		const run = {
			id: runId,
			status: "running" as const,
			workspaceId: "22222222-2222-4222-8222-222222222222",
		};
		const runFindFirst = vi.fn().mockResolvedValue(run);
		const workspaceFindFirst = vi.fn().mockResolvedValue(null);
		const select = vi.fn();
		const db = {
			query: {
				agentRuns: { findFirst: runFindFirst },
				workspaces: { findFirst: workspaceFindFirst },
			},
			select,
		};
		const caller = createWorkspaceCaller(db);

		await expect(
			caller.streamEvents({ runId, sinceSequence: 0 }),
		).rejects.toMatchObject({ code: "NOT_FOUND" });

		expect(select).not.toHaveBeenCalled();
	});

	it("mints a run-stream URL with a signed JWT for the run's owner", async () => {
		const runId = "11111111-1111-4111-8111-111111111111";
		const workspaceId = "22222222-2222-4222-8222-222222222222";
		const run = {
			id: runId,
			status: "running" as const,
			workspaceId,
		};
		const workspace = { id: workspaceId, ownerId: "user-1" };
		const runFindFirst = vi.fn().mockResolvedValue(run);
		const workspaceFindFirst = vi.fn().mockResolvedValue(workspace);
		const db = {
			query: {
				agentRuns: { findFirst: runFindFirst },
				workspaces: { findFirst: workspaceFindFirst },
			},
		};
		const caller = createWorkspaceCaller(db);

		const result = await caller.mintRunStreamToken({ runId });

		expect(result.url).toMatch(/^https:\/\/example\.invalid\/run-stream\?/);
		const url = new URL(result.url);
		expect(url.searchParams.get("runId")).toBe(runId);
		const token = url.searchParams.get("token");
		expect(token).toBeTruthy();
		expect(token?.split(".").length).toBe(3);

		const runWhere = runFindFirst.mock.calls[0]?.[0].where;
		expect(expressionReferences(runWhere, agentRuns.id)).toBe(true);
		const workspaceWhere = workspaceFindFirst.mock.calls[0]?.[0].where;
		expect(expressionReferences(workspaceWhere, workspaces.id)).toBe(true);
		expect(expressionReferences(workspaceWhere, workspaces.ownerId)).toBe(true);
	});

	it("rejects mintRunStreamToken when the run does not exist", async () => {
		const runFindFirst = vi.fn().mockResolvedValue(null);
		const workspaceFindFirst = vi.fn();
		const db = {
			query: {
				agentRuns: { findFirst: runFindFirst },
				workspaces: { findFirst: workspaceFindFirst },
			},
		};
		const caller = createWorkspaceCaller(db);

		await expect(
			caller.mintRunStreamToken({
				runId: "11111111-1111-4111-8111-111111111111",
			}),
		).rejects.toMatchObject({ code: "NOT_FOUND" });

		expect(workspaceFindFirst).not.toHaveBeenCalled();
	});

	it("rejects mintRunStreamToken when the run is owned by another user", async () => {
		const runId = "11111111-1111-4111-8111-111111111111";
		const run = {
			id: runId,
			status: "running" as const,
			workspaceId: "22222222-2222-4222-8222-222222222222",
		};
		const runFindFirst = vi.fn().mockResolvedValue(run);
		const workspaceFindFirst = vi.fn().mockResolvedValue(null);
		const db = {
			query: {
				agentRuns: { findFirst: runFindFirst },
				workspaces: { findFirst: workspaceFindFirst },
			},
		};
		const caller = createWorkspaceCaller(db);

		await expect(
			caller.mintRunStreamToken({ runId }),
		).rejects.toMatchObject({ code: "NOT_FOUND" });
	});

	it("createAttachment inserts a pending artifact and returns a presigned upload URL", async () => {
		vi.mocked(r2ArtifactStore.getUploadUrl).mockClear();
		vi.mocked(r2ArtifactStore.getUploadUrl).mockResolvedValueOnce(
			"https://signed.example/put-url",
		);
		const workspace = {
			id: "22222222-2222-4222-8222-222222222222",
			ownerId: "user-1",
		};
		const artifactRow = {
			contentType: "application/pdf",
			id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
			kind: "attachment" as const,
			name: "Spec sheet.PDF",
			sizeBytes: 12345,
			storageKey: "irrelevant",
			workspaceId: workspace.id,
		};
		const artifactInsert = insertReturning(artifactRow);
		const workspaceFindFirst = vi.fn().mockResolvedValue(workspace);
		const caller = createWorkspaceCaller({
			insert: vi.fn().mockReturnValueOnce(artifactInsert),
			query: {
				workspaces: { findFirst: workspaceFindFirst },
			},
		});

		const result = await caller.createAttachment({
			byteSize: 12345,
			contentType: "application/pdf",
			fileName: "Spec sheet.PDF",
			workspaceId: workspace.id,
		});

		expect(result.uploadUrl).toBe("https://signed.example/put-url");
		expect(result.artifactId).toBe(artifactRow.id);
		expect(result.storageKey).toMatch(
			/^projects\/22222222-2222-4222-8222-222222222222\/attachments\/[0-9a-f-]+\/spec-sheet\.pdf$/,
		);

		const insertedValues = (
			artifactInsert.values.mock.calls as unknown as Array<
				[Record<string, unknown>]
			>
		)[0]?.[0];
		expect(insertedValues).toMatchObject({
			contentType: "application/pdf",
			kind: "attachment",
			name: "Spec sheet.PDF",
			sizeBytes: 12345,
			storageProvider: "r2",
			workspaceId: workspace.id,
		});
		expect(insertedValues?.metadataJson).toMatchObject({
			originalFileName: "Spec sheet.PDF",
			uploadStatus: "pending",
		});

		expect(r2ArtifactStore.getUploadUrl).toHaveBeenCalledWith(
			expect.objectContaining({
				contentType: "application/pdf",
				expiresInSeconds: 15 * 60,
			}),
		);

		const where = workspaceFindFirst.mock.calls[0]?.[0].where;
		expect(expressionReferences(where, workspaces.id)).toBe(true);
		expect(expressionReferences(where, workspaces.ownerId)).toBe(true);
		expect(expressionReferences(where, workspaces.archivedAt)).toBe(true);
	});

	it("createAttachment rejects byteSize over 25 MB via input validation", async () => {
		const caller = createWorkspaceCaller({});

		await expect(
			caller.createAttachment({
				byteSize: 25 * 1024 * 1024 + 1,
				contentType: "application/pdf",
				fileName: "huge.pdf",
				workspaceId: "22222222-2222-4222-8222-222222222222",
			}),
		).rejects.toThrow();
	});

	it("confirmAttachment rejects when caller does not own the workspace", async () => {
		vi.mocked(r2ArtifactStore.objectExists).mockClear();
		const artifactRow = {
			id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
			kind: "attachment" as const,
			name: "Spec.pdf",
			storageKey:
				"projects/22222222-2222-4222-8222-222222222222/attachments/aaa/spec.pdf",
			workspaceId: "22222222-2222-4222-8222-222222222222",
		};
		const artifactFindFirst = vi.fn().mockResolvedValue(artifactRow);
		const workspaceFindFirst = vi.fn().mockResolvedValue(null);
		const insert = vi.fn();
		const caller = createWorkspaceCaller({
			insert,
			query: {
				artifacts: { findFirst: artifactFindFirst },
				workspaces: { findFirst: workspaceFindFirst },
			},
		});

		await expect(
			caller.confirmAttachment({ artifactId: artifactRow.id }),
		).rejects.toMatchObject({ code: "NOT_FOUND" });

		expect(insert).not.toHaveBeenCalled();
		expect(r2ArtifactStore.objectExists).not.toHaveBeenCalled();
	});

	it("confirmAttachment inserts an artifact context reference after a successful HEAD check", async () => {
		vi.mocked(r2ArtifactStore.objectExists).mockClear();
		vi.mocked(r2ArtifactStore.objectExists).mockResolvedValueOnce(true);
		const workspace = {
			id: "22222222-2222-4222-8222-222222222222",
			ownerId: "user-1",
		};
		const artifactRow = {
			id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
			kind: "attachment" as const,
			name: "Spec.pdf",
			storageKey:
				"projects/22222222-2222-4222-8222-222222222222/attachments/aaa/spec.pdf",
			workspaceId: workspace.id,
		};
		const reference = {
			artifactId: artifactRow.id,
			id: "55555555-5555-4555-8555-555555555555",
		};
		const referenceInsert = insertReturning(reference);
		const artifactFindFirst = vi.fn().mockResolvedValue(artifactRow);
		const workspaceFindFirst = vi.fn().mockResolvedValue(workspace);
		const caller = createWorkspaceCaller({
			insert: vi.fn().mockReturnValueOnce(referenceInsert),
			query: {
				artifacts: { findFirst: artifactFindFirst },
				workspaces: { findFirst: workspaceFindFirst },
			},
		});

		await expect(
			caller.confirmAttachment({ artifactId: artifactRow.id }),
		).resolves.toEqual({
			contextReferenceId: reference.id,
			ok: true,
		});

		expect(r2ArtifactStore.objectExists).toHaveBeenCalledWith({
			key: artifactRow.storageKey,
		});
		expect(referenceInsert.values).toHaveBeenCalledWith({
			artifactId: artifactRow.id,
			candidateId: null,
			createdById: "user-1",
			kind: "artifact",
			label: artifactRow.name,
			selectorJson: {},
			workspaceId: artifactRow.workspaceId,
		});
	});

	it("deleteAttachment rejects when artifact is not an attachment", async () => {
		vi.mocked(r2ArtifactStore.deleteObject).mockClear();
		const artifactRow = {
			id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
			kind: "cif" as const,
			name: "structure.cif",
			storageKey: "projects/22222222-2222-4222-8222-222222222222/cif",
			workspaceId: "22222222-2222-4222-8222-222222222222",
		};
		const artifactFindFirst = vi.fn().mockResolvedValue(artifactRow);
		const workspaceFindFirst = vi.fn();
		const deleteFn = vi.fn();
		const caller = createWorkspaceCaller({
			delete: deleteFn,
			query: {
				artifacts: { findFirst: artifactFindFirst },
				workspaces: { findFirst: workspaceFindFirst },
			},
		});

		await expect(
			caller.deleteAttachment({ artifactId: artifactRow.id }),
		).rejects.toMatchObject({ code: "NOT_FOUND" });

		expect(workspaceFindFirst).not.toHaveBeenCalled();
		expect(r2ArtifactStore.deleteObject).not.toHaveBeenCalled();
		expect(deleteFn).not.toHaveBeenCalled();
	});

	it("deleteAttachment removes the R2 object and the artifact row when authorized", async () => {
		vi.mocked(r2ArtifactStore.deleteObject).mockClear();
		vi.mocked(r2ArtifactStore.deleteObject).mockResolvedValueOnce(undefined);
		const workspace = {
			id: "22222222-2222-4222-8222-222222222222",
			ownerId: "user-1",
		};
		const artifactRow = {
			id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
			kind: "attachment" as const,
			name: "Spec.pdf",
			storageKey:
				"projects/22222222-2222-4222-8222-222222222222/attachments/aaa/spec.pdf",
			workspaceId: workspace.id,
		};
		const artifactFindFirst = vi.fn().mockResolvedValue(artifactRow);
		const workspaceFindFirst = vi.fn().mockResolvedValue(workspace);
		const deleteCall = deleteCapturing();
		const deleteFn = vi.fn(() => deleteCall);
		const caller = createWorkspaceCaller({
			delete: deleteFn,
			query: {
				artifacts: { findFirst: artifactFindFirst },
				workspaces: { findFirst: workspaceFindFirst },
			},
		});

		await expect(
			caller.deleteAttachment({ artifactId: artifactRow.id }),
		).resolves.toEqual({ ok: true });

		expect(r2ArtifactStore.deleteObject).toHaveBeenCalledWith({
			key: artifactRow.storageKey,
		});
		expect(deleteFn).toHaveBeenCalledWith(artifacts);
		const deleteWhere = deleteCall.where.mock.calls[0]?.[0];
		expect(expressionReferences(deleteWhere, artifacts.id)).toBe(true);
	});
});

describe("workspace router getWorkspacePayload compatibility helper", () => {
	it("excludes archived workspaces when loading by id", async () => {
		const findFirst = vi.fn().mockResolvedValue(null);
		const db = {
			query: {
				workspaces: { findFirst },
			},
		};

		await getWorkspacePayload(
			db as never,
			"22222222-2222-4222-8222-222222222222",
			"user-1",
		);

		expect(findFirst).toHaveBeenCalledOnce();
		expect(
			expressionReferences(
				findFirst.mock.calls[0]?.[0].where,
				workspaces.archivedAt,
			),
		).toBe(true);
		expect(
			expressionContainsText(findFirst.mock.calls[0]?.[0].where, " is null"),
		).toBe(true);
	});

	it("selects runs from the active thread instead of the newest workspace run", async () => {
		const workspace = {
			activeThreadId: "33333333-3333-4333-8333-333333333333",
			description: "Design binders for SARS-CoV-2 spike RBD",
			id: "22222222-2222-4222-8222-222222222222",
			ownerId: "user-1",
		};
		const activeThread = {
			id: workspace.activeThreadId,
			workspaceId: workspace.id,
		};
		const newestOtherThread = {
			id: "44444444-4444-4444-8444-444444444444",
			workspaceId: workspace.id,
		};
		const activeRun = {
			id: "55555555-5555-4555-8555-555555555555",
			prompt: "Design a protein binder for SARS-CoV-2 spike RBD",
			threadId: activeThread.id,
			workspaceId: workspace.id,
		};
		const agentRunsFindMany = vi.fn().mockResolvedValue([activeRun]);
		const candidateScoresFindMany = emptyFindMany();
		const db = {
			query: {
				agentEvents: { findMany: emptyFindMany() },
				agentRuns: { findMany: agentRunsFindMany },
				artifacts: { findMany: emptyFindMany() },
				candidateScores: { findMany: candidateScoresFindMany },
				contextReferences: { findMany: emptyFindMany() },
				messages: { findMany: emptyFindMany() },
				proteinCandidates: { findMany: emptyFindMany() },
				recipes: { findMany: emptyFindMany() },
				threads: {
					findMany: vi
						.fn()
						.mockResolvedValue([newestOtherThread, activeThread]),
				},
				workspaces: { findFirst: vi.fn().mockResolvedValue(workspace) },
			},
		};

		const payload = await getWorkspacePayload(
			db as never,
			workspace.id,
			workspace.ownerId,
		);

		expect(payload?.activeRun).toEqual(activeRun);
		expect(agentRunsFindMany).toHaveBeenCalledWith(
			expect.objectContaining({ limit: 20 }),
		);
		const runsWhere = agentRunsFindMany.mock.calls[0]?.[0].where;
		expect(expressionReferences(runsWhere, agentRuns.threadId)).toBe(true);
		expect(expressionReferences(runsWhere, activeThread.id)).toBe(true);
		expect(candidateScoresFindMany).toHaveBeenCalledOnce();
	});
});
