import { describe, expect, it, vi } from "vitest";

import { agentRuns, workspaces } from "@/server/db/schema";
import { createWorkspaceWithThread, getWorkspacePayload } from "./repository";

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

const insertReturning = (row: unknown) => {
	const returning = vi.fn().mockResolvedValue([row]);
	const values = vi.fn(() => ({ returning }));
	return { returning, values };
};

describe("createWorkspaceWithThread", () => {
	it("creates a workspace, creates the main thread, activates it, and returns both", async () => {
		const workspace = {
			description: "Design binders for SARS-CoV-2 spike RBD",
			id: "22222222-2222-4222-8222-222222222222",
			name: "Spike RBD binders",
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
		const workspaceInsert = insertReturning(workspace);
		const threadInsert = insertReturning(thread);
		const updateReturning = vi.fn().mockResolvedValue([updatedWorkspace]);
		const where = vi.fn(() => ({ returning: updateReturning }));
		const set = vi.fn(() => ({ where }));
		const db = {
			insert: vi
				.fn()
				.mockReturnValueOnce(workspaceInsert)
				.mockReturnValueOnce(threadInsert),
			update: vi.fn(() => ({ set })),
		};

		const result = await createWorkspaceWithThread({
			db: db as never,
			description: workspace.description,
			name: workspace.name,
			ownerId: workspace.ownerId,
		});

		expect(workspaceInsert.values).toHaveBeenCalledWith({
			description: workspace.description,
			name: workspace.name,
			ownerId: workspace.ownerId,
		});
		expect(threadInsert.values).toHaveBeenCalledWith({
			title: "Main thread",
			workspaceId: workspace.id,
		});
		expect(set).toHaveBeenCalledWith({ activeThreadId: thread.id });
		expect(result).toEqual({
			thread,
			workspace: updatedWorkspace,
		});
	});
});

describe("getWorkspacePayload", () => {
	const emptyFindMany = () => vi.fn().mockResolvedValue([]);

	it("looks up direct workspace payloads with archived workspaces excluded", async () => {
		const findFirst = vi.fn().mockResolvedValue(null);
		const db = {
			query: {
				workspaces: { findFirst },
				threads: { findMany: emptyFindMany() },
			},
		};

		await getWorkspacePayload({
			db: db as never,
			ownerId: "user-1",
			workspaceId: "22222222-2222-4222-8222-222222222222",
		});

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
		expect(db.query.threads.findMany).not.toHaveBeenCalled();
	});

	it("selects runs from the active thread instead of the newest workspace run", async () => {
		const workspace = {
			activeThreadId: "33333333-3333-4333-8333-333333333333",
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
			threadId: activeThread.id,
			workspaceId: workspace.id,
		};
		const agentRunsFindMany = vi.fn().mockResolvedValue([activeRun]);
		const db = {
			query: {
				agentEvents: { findMany: emptyFindMany() },
				agentRuns: { findMany: agentRunsFindMany },
				artifacts: { findMany: emptyFindMany() },
				candidateScores: { findMany: emptyFindMany() },
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

		const payload = await getWorkspacePayload({
			db: db as never,
			ownerId: workspace.ownerId,
			workspaceId: workspace.id,
		});

		expect(payload?.activeRun).toEqual(activeRun);
		expect(agentRunsFindMany).toHaveBeenCalledWith(
			expect.objectContaining({ limit: 20 }),
		);
		const runsWhere = agentRunsFindMany.mock.calls[0]?.[0].where;
		expect(expressionReferences(runsWhere, agentRuns.threadId)).toBe(true);
		expect(expressionReferences(runsWhere, activeThread.id)).toBe(true);
	});
});
