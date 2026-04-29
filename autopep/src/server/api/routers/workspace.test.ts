import { describe, expect, it, vi } from "vitest";

import {
	createMessageRunWithLaunch,
	createProjectRunWithLaunch,
} from "@/server/agent/project-run-creator";
import { createCallerFactory } from "@/server/api/trpc";
import { agentRuns, workspaces } from "@/server/db/schema";
import { getWorkspacePayload, workspaceRouter } from "./workspace";

vi.mock("@/server/agent/project-run-creator", () => ({
	createMessageRunWithLaunch: vi.fn(),
	createProjectRunWithLaunch: vi.fn(),
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
				"createProjectRun",
				"createWorkspace",
				"getLatestWorkspace",
				"getRunEvents",
				"getWorkspace",
				"listWorkspaces",
				"renameWorkspace",
				"sendMessage",
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
