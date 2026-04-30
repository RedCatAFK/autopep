import { TRPCError } from "@trpc/server";
import { and, asc, desc, eq, gt, isNull } from "drizzle-orm";
import * as z from "zod";

import { env } from "@/env";
import { publicTaskKindSchema } from "@/server/agent/contracts";
import {
	createMessageRunWithLaunch,
	createProjectRunWithLaunch,
} from "@/server/agent/project-run-creator";
import { signRunStreamToken } from "@/server/agent/run-stream-token";
import { answerWorkspaceQuestion } from "@/server/agent/workspace-answer";
import { createTRPCRouter, protectedProcedure } from "@/server/api/trpc";
import { r2ArtifactStore } from "@/server/artifacts/r2";
import type { db as appDb } from "@/server/db";
import {
	agentEvents,
	agentRuns,
	artifacts,
	contextReferences,
	type proteinCandidates,
	recipes,
	recipeVersions,
	type threadItems as threadItemsTable,
	workspaces,
} from "@/server/db/schema";
import { inferWorkspaceNameWithAi } from "@/server/workspaces/auto-name";
import {
	createWorkspaceWithThread,
	getWorkspacePayload as getRepositoryWorkspacePayload,
	getRunEventsAfter,
	listWorkspacesForOwner,
} from "@/server/workspaces/repository";

type Db = typeof appDb;

const workspaceIdInput = z.object({
	workspaceId: z.string().uuid(),
});

const compatibleWorkspaceIdInput = z
	.object({
		projectId: z.string().uuid().optional(),
		workspaceId: z.string().uuid().optional(),
	})
	.refine((input) => input.workspaceId ?? input.projectId, {
		message: "workspaceId is required.",
	});

const runEventsInput = z.object({
	afterSequence: z.number().int().min(0).default(0),
	runId: z.string().uuid(),
});

const createContextReferenceInput = z.object({
	artifactId: z.string().uuid().nullable(),
	candidateId: z.string().uuid().nullable(),
	kind: z.enum([
		"protein_selection",
		"artifact",
		"candidate",
		"literature",
		"note",
	]),
	label: z.string().min(1).max(160),
	selector: z.record(z.unknown()).default({}),
	workspaceId: z.string().uuid(),
});

const createProjectRunInput = z.object({
	goal: z.string().min(3),
	name: z.string().min(1).max(120).optional(),
	topK: z.number().int().min(1).max(10).default(5),
});

const recipeInput = z.object({
	bodyMarkdown: z.string().min(1).max(20_000),
	description: z.string().max(1000).nullable().optional(),
	enabledByDefault: z.boolean().default(false),
	name: z.string().min(1).max(120),
	workspaceId: z.string().uuid(),
});

const answerQuestionInput = z.object({
	projectId: z.string().uuid().optional(),
	question: z.string().min(1).max(1000),
	workspaceId: z.string().uuid().optional(),
});

const MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024;

const createAttachmentInput = z.object({
	byteSize: z.number().int().min(1).max(MAX_ATTACHMENT_BYTES),
	contentType: z.string().min(1).max(120),
	fileName: z.string().min(1).max(255),
	workspaceId: z.string().uuid(),
});

const attachmentIdInput = z.object({
	artifactId: z.string().uuid(),
});

const contextReferenceIdInput = z.object({
	contextReferenceId: z.string().uuid(),
});

const sanitizeAttachmentFileName = (name: string) => {
	const cleaned = name
		.trim()
		.toLowerCase()
		.replace(/[^a-z0-9._-]+/g, "-")
		.replace(/^-+|-+$/g, "");
	return cleaned.length > 0 ? cleaned : "file";
};

const sendMessageInput = z.object({
	attachmentRefs: z.array(z.string().uuid()).default([]),
	contextRefs: z.array(z.string().uuid()).default([]),
	prompt: z.string().min(1).max(12000),
	projectId: z.string().uuid().optional(),
	recipeRefs: z.array(z.string().uuid()).default([]),
	taskKind: publicTaskKindSchema.default("chat"),
	workspaceId: z.string().uuid().optional(),
});

const shouldRouteChatPromptAsResearch = (prompt: string) =>
	/\b(literature|papers?|pubmed|pmc|biorxiv|preprints?|studies)\b/iu.test(
		prompt,
	);

const getRecord = (value: unknown): Record<string, unknown> =>
	value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};

const getString = (value: unknown): string | null =>
	typeof value === "string" ? value : null;

const getNumber = (value: unknown): number | null =>
	typeof value === "number" ? value : null;

const getBoolean = (value: unknown): boolean =>
	typeof value === "boolean" ? value : false;

const resolveWorkspaceId = (input: {
	projectId?: string;
	workspaceId?: string;
}) => {
	const workspaceId = input.workspaceId ?? input.projectId;
	if (!workspaceId) {
		throw new TRPCError({
			code: "BAD_REQUEST",
			message: "workspaceId is required.",
		});
	}
	return workspaceId;
};

const inferTargetName = (prompt: string) => {
	const normalized = prompt.toLowerCase();
	if (normalized.includes("3cl") || normalized.includes("protease")) {
		return "SARS-CoV-2 3CL protease";
	}
	if (normalized.includes("spike") || normalized.includes("rbd")) {
		return "SARS-CoV-2 spike receptor binding domain";
	}

	return prompt;
};

const artifactKindToLegacyType = (
	kind: string,
	metadataJson: Record<string, unknown>,
) => {
	const legacyType = getString(metadataJson.legacyType);
	if (legacyType) {
		return legacyType;
	}

	if (kind === "cif" || kind === "mmcif") {
		return "source_cif";
	}

	return kind;
};

const mapWorkspaceToProject = (
	workspace: typeof workspaces.$inferSelect,
	activeRun: typeof agentRuns.$inferSelect | null,
) => ({
	...workspace,
	goal: workspace.description ?? activeRun?.prompt ?? "",
});

const mapEvent = (event: typeof agentEvents.$inferSelect) => ({
	...event,
	createdAt: event.createdAt.toISOString(),
	detail: event.summary,
	payloadJson: event.displayJson,
});

const mapThreadMessageItem = (
	item: typeof threadItemsTable.$inferSelect,
) => {
	const contentJson = item.contentJson as
		| { text?: string; type?: string }
		| null;
	const content = contentJson?.text ?? "";
	return {
		attachmentRefsJson: item.attachmentRefsJson ?? [],
		content,
		contextRefsJson: item.contextRefsJson ?? [],
		createdAt: item.createdAt.toISOString(),
		id: item.id,
		recipeRefsJson: item.recipeRefsJson ?? [],
		role: item.role,
		runId: item.runId,
		threadId: item.threadId,
	};
};

const mapRunSummary = (run: typeof agentRuns.$inferSelect) => ({
	id: run.id,
	startedAt: run.startedAt ? run.startedAt.toISOString() : null,
	status: run.status,
});

const mapCandidate = (candidate: typeof proteinCandidates.$inferSelect) => {
	const scoreJson = getRecord(candidate.scoreJson);
	const metadataJson = getRecord(candidate.metadataJson);

	return {
		...candidate,
		citationJson: getRecord(scoreJson.citation),
		confidence: getNumber(scoreJson.confidence) ?? 0,
		ligandIdsJson: Array.isArray(scoreJson.ligands) ? scoreJson.ligands : [],
		method: getString(scoreJson.method),
		organism: getString(metadataJson.organism),
		proteinaReady: getBoolean(metadataJson.proteinaReady),
		rcsbId:
			getString(metadataJson.rcsbId) ?? candidate.structureId ?? candidate.id,
		relevanceScore: getNumber(scoreJson.relevance) ?? 0,
		resolutionAngstrom: getNumber(scoreJson.resolution),
		selectionRationale: candidate.whySelected ?? "",
	};
};

const mapArtifact = async (artifact: typeof artifacts.$inferSelect) => {
	const metadataJson = getRecord(artifact.metadataJson);

	return {
		...artifact,
		byteSize: artifact.sizeBytes,
		candidateId: getString(metadataJson.candidateId),
		fileName: artifact.name,
		objectKey: artifact.storageKey,
		signedUrl: await r2ArtifactStore.getReadUrl({
			key: artifact.storageKey,
		}),
		sourceUrl: getString(metadataJson.sourceUrl),
		type: artifactKindToLegacyType(artifact.kind, metadataJson),
	};
};

const shouldExposeArtifact = (
	artifact: typeof artifacts.$inferSelect,
	confirmedAttachmentIds: ReadonlySet<string>,
) => {
	if (artifact.kind !== "attachment") {
		return true;
	}

	const metadataJson = getRecord(artifact.metadataJson);
	return (
		getString(metadataJson.uploadStatus) === "ready" ||
		confirmedAttachmentIds.has(artifact.id)
	);
};

const getLatestWorkspaceForOwner = async (db: Db, ownerId: string) =>
	db.query.workspaces.findFirst({
		where: and(eq(workspaces.ownerId, ownerId), isNull(workspaces.archivedAt)),
		orderBy: [desc(workspaces.updatedAt)],
	});

const getWorkspaceCompatibilityPayload = async ({
	db,
	ownerId,
	workspaceId,
}: {
	db: Db;
	ownerId: string;
	workspaceId: string;
}) => {
	const payload = await getRepositoryWorkspacePayload({
		db,
		ownerId,
		workspaceId,
	});

	if (!payload) {
		return null;
	}

	const project = mapWorkspaceToProject(payload.workspace, payload.activeRun);
	const targetEntities = payload.activeRun
		? [
				{
					name: inferTargetName(payload.activeRun.prompt),
					organism: payload.activeRun.prompt
						.toLowerCase()
						.includes("sars-cov-2")
						? "SARS-CoV-2"
						: null,
				},
			]
		: [];

	const runSummaries = [...payload.runs]
		.sort((a, b) => {
			const aTime = a.startedAt?.getTime() ?? 0;
			const bTime = b.startedAt?.getTime() ?? 0;
			return bTime - aTime;
		})
		.map(mapRunSummary);
	const confirmedAttachmentIds = new Set(
		payload.contextReferences.flatMap((reference) =>
			reference.kind === "artifact" && reference.artifactId
				? [reference.artifactId]
				: [],
		),
	);
	const visibleArtifacts = payload.artifacts.filter((artifact) =>
		shouldExposeArtifact(artifact, confirmedAttachmentIds),
	);

	return {
		...payload,
		artifacts: await Promise.all(visibleArtifacts.map(mapArtifact)),
		candidateScores: payload.candidateScores,
		candidates: payload.candidates.map(mapCandidate),
		events: payload.events.map(mapEvent),
		messages: payload.messages.map(mapThreadMessageItem),
		project,
		runs: runSummaries,
		targetEntities,
	};
};

export const getWorkspacePayload = (
	db: Db,
	projectId: string,
	ownerId: string,
) =>
	getWorkspaceCompatibilityPayload({
		db,
		ownerId,
		workspaceId: projectId,
	});

export const workspaceRouter = createTRPCRouter({
	listWorkspaces: protectedProcedure.query(async ({ ctx }) =>
		listWorkspacesForOwner(ctx.db, ctx.session.user.id),
	),

	createWorkspace: protectedProcedure
		.input(
			z.object({
				description: z.string().max(1000).nullable().optional(),
				name: z.string().min(1).max(120),
			}),
		)
		.mutation(async ({ ctx, input }) =>
			createWorkspaceWithThread({
				db: ctx.db,
				description: input.description ?? null,
				name: input.name,
				ownerId: ctx.session.user.id,
			}),
		),

	renameWorkspace: protectedProcedure
		.input(workspaceIdInput.extend({ name: z.string().min(1).max(120) }))
		.mutation(async ({ ctx, input }) => {
			const [workspace] = await ctx.db
				.update(workspaces)
				.set({ name: input.name })
				.where(
					and(
						eq(workspaces.id, input.workspaceId),
						eq(workspaces.ownerId, ctx.session.user.id),
						isNull(workspaces.archivedAt),
					),
				)
				.returning();

			if (!workspace) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Workspace not found.",
				});
			}

			return workspace;
		}),

	archiveWorkspace: protectedProcedure
		.input(workspaceIdInput)
		.mutation(async ({ ctx, input }) => {
			const [workspace] = await ctx.db
				.update(workspaces)
				.set({ archivedAt: new Date() })
				.where(
					and(
						eq(workspaces.id, input.workspaceId),
						eq(workspaces.ownerId, ctx.session.user.id),
					),
				)
				.returning();

			if (!workspace) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Workspace not found.",
				});
			}

			return workspace;
		}),

	createAttachment: protectedProcedure
		.input(createAttachmentInput)
		.mutation(async ({ ctx, input }) => {
			const workspace = await ctx.db.query.workspaces.findFirst({
				where: and(
					eq(workspaces.id, input.workspaceId),
					eq(workspaces.ownerId, ctx.session.user.id),
					isNull(workspaces.archivedAt),
				),
			});
			if (!workspace) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Workspace not found.",
				});
			}

			const attachmentId = crypto.randomUUID();
			const sanitized = sanitizeAttachmentFileName(input.fileName);
			const storageKey = `projects/${workspace.id}/attachments/${attachmentId}/${sanitized}`;

			const [artifact] = await ctx.db
				.insert(artifacts)
				.values({
					id: attachmentId,
					contentType: input.contentType,
					kind: "attachment",
					metadataJson: {
						originalFileName: input.fileName,
						uploadStatus: "pending",
					},
					name: input.fileName,
					runId: null,
					sizeBytes: input.byteSize,
					sourceArtifactId: null,
					storageKey,
					storageProvider: "r2",
					workspaceId: input.workspaceId,
				})
				.returning();

			if (!artifact) {
				throw new TRPCError({
					code: "INTERNAL_SERVER_ERROR",
					message: "Failed to create attachment artifact.",
				});
			}

			const uploadUrl = await r2ArtifactStore.getUploadUrl({
				contentType: input.contentType,
				expiresInSeconds: 15 * 60,
				key: storageKey,
			});

			return {
				artifactId: artifact.id,
				storageKey,
				uploadUrl,
			};
		}),

	confirmAttachment: protectedProcedure
		.input(attachmentIdInput)
		.mutation(async ({ ctx, input }) => {
			const artifact = await ctx.db.query.artifacts.findFirst({
				where: eq(artifacts.id, input.artifactId),
			});
			if (!artifact || artifact.kind !== "attachment") {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Attachment not found.",
				});
			}

			const workspace = await ctx.db.query.workspaces.findFirst({
				where: and(
					eq(workspaces.id, artifact.workspaceId),
					eq(workspaces.ownerId, ctx.session.user.id),
				),
			});
			if (!workspace) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Attachment not found.",
				});
			}

			const exists = await r2ArtifactStore.objectExists({
				key: artifact.storageKey,
			});
			if (!exists) {
				throw new TRPCError({
					code: "PRECONDITION_FAILED",
					message: "Attachment object has not been uploaded.",
				});
			}

			await ctx.db
				.update(artifacts)
				.set({
					metadataJson: {
						...getRecord(artifact.metadataJson),
						confirmedAt: new Date().toISOString(),
						uploadStatus: "ready",
					},
				})
				.where(eq(artifacts.id, artifact.id));

			const [reference] = await ctx.db
				.insert(contextReferences)
				.values({
					artifactId: artifact.id,
					candidateId: null,
					createdById: ctx.session.user.id,
					kind: "artifact",
					label: artifact.name,
					selectorJson: {},
					workspaceId: artifact.workspaceId,
				})
				.returning();

			if (!reference) {
				throw new TRPCError({
					code: "INTERNAL_SERVER_ERROR",
					message: "Failed to register attachment reference.",
				});
			}

			return { contextReferenceId: reference.id, ok: true as const };
		}),

	deleteAttachment: protectedProcedure
		.input(attachmentIdInput)
		.mutation(async ({ ctx, input }) => {
			const artifact = await ctx.db.query.artifacts.findFirst({
				where: eq(artifacts.id, input.artifactId),
			});
			if (!artifact || artifact.kind !== "attachment") {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Attachment not found.",
				});
			}

			const workspace = await ctx.db.query.workspaces.findFirst({
				where: and(
					eq(workspaces.id, artifact.workspaceId),
					eq(workspaces.ownerId, ctx.session.user.id),
				),
			});
			if (!workspace) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Attachment not found.",
				});
			}

			await r2ArtifactStore.deleteObject({ key: artifact.storageKey });
			await ctx.db.delete(artifacts).where(eq(artifacts.id, artifact.id));

			return { ok: true as const };
		}),

	createContextReference: protectedProcedure
		.input(createContextReferenceInput)
		.mutation(async ({ ctx, input }) => {
			const workspace = await ctx.db.query.workspaces.findFirst({
				where: and(
					eq(workspaces.id, input.workspaceId),
					eq(workspaces.ownerId, ctx.session.user.id),
					isNull(workspaces.archivedAt),
				),
			});

			if (!workspace) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Workspace not found.",
				});
			}

			const [reference] = await ctx.db
				.insert(contextReferences)
				.values({
					artifactId: input.artifactId,
					candidateId: input.candidateId,
					createdById: ctx.session.user.id,
					kind: input.kind,
					label: input.label,
					selectorJson: input.selector,
					workspaceId: input.workspaceId,
				})
				.returning();

			if (!reference) {
				throw new TRPCError({
					code: "INTERNAL_SERVER_ERROR",
					message: "Failed to create context reference.",
				});
			}

			return reference;
		}),

	deleteContextReference: protectedProcedure
		.input(contextReferenceIdInput)
		.mutation(async ({ ctx, input }) => {
			const reference = await ctx.db.query.contextReferences.findFirst({
				where: eq(contextReferences.id, input.contextReferenceId),
			});

			if (!reference) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Context reference not found.",
				});
			}

			const workspace = await ctx.db.query.workspaces.findFirst({
				where: and(
					eq(workspaces.id, reference.workspaceId),
					eq(workspaces.ownerId, ctx.session.user.id),
					isNull(workspaces.archivedAt),
				),
			});

			if (!workspace) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Context reference not found.",
				});
			}

			await ctx.db
				.delete(contextReferences)
				.where(eq(contextReferences.id, reference.id));

			return { ok: true as const };
		}),

	listRecipes: protectedProcedure
		.input(workspaceIdInput)
		.query(async ({ ctx, input }) => {
			const workspace = await ctx.db.query.workspaces.findFirst({
				where: and(
					eq(workspaces.id, input.workspaceId),
					eq(workspaces.ownerId, ctx.session.user.id),
					isNull(workspaces.archivedAt),
				),
			});
			if (!workspace) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Workspace not found.",
				});
			}

			return ctx.db.query.recipes.findMany({
				where: and(
					eq(recipes.workspaceId, input.workspaceId),
					eq(recipes.ownerId, ctx.session.user.id),
					isNull(recipes.archivedAt),
				),
				orderBy: [asc(recipes.name)],
			});
		}),

	createRecipe: protectedProcedure
		.input(recipeInput)
		.mutation(async ({ ctx, input }) => {
			const workspace = await ctx.db.query.workspaces.findFirst({
				where: and(
					eq(workspaces.id, input.workspaceId),
					eq(workspaces.ownerId, ctx.session.user.id),
					isNull(workspaces.archivedAt),
				),
			});
			if (!workspace) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Workspace not found.",
				});
			}

			const [recipe] = await ctx.db
				.insert(recipes)
				.values({
					bodyMarkdown: input.bodyMarkdown,
					description: input.description ?? null,
					enabledByDefault: input.enabledByDefault,
					name: input.name,
					ownerId: ctx.session.user.id,
					workspaceId: input.workspaceId,
				})
				.returning();
			if (!recipe) {
				throw new TRPCError({
					code: "INTERNAL_SERVER_ERROR",
					message: "Failed to create recipe.",
				});
			}

			const [version] = await ctx.db
				.insert(recipeVersions)
				.values({
					bodyMarkdown: input.bodyMarkdown,
					createdById: ctx.session.user.id,
					recipeId: recipe.id,
					version: 1,
				})
				.returning();

			return { recipe, version };
		}),

	updateRecipe: protectedProcedure
		.input(recipeInput.extend({ recipeId: z.string().uuid() }))
		.mutation(async ({ ctx, input }) => {
			const [recipe] = await ctx.db
				.update(recipes)
				.set({
					bodyMarkdown: input.bodyMarkdown,
					description: input.description ?? null,
					enabledByDefault: input.enabledByDefault,
					name: input.name,
				})
				.where(
					and(
						eq(recipes.id, input.recipeId),
						eq(recipes.ownerId, ctx.session.user.id),
						eq(recipes.workspaceId, input.workspaceId),
						isNull(recipes.archivedAt),
					),
				)
				.returning();
			if (!recipe) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Recipe not found.",
				});
			}

			const latest = await ctx.db.query.recipeVersions.findFirst({
				where: eq(recipeVersions.recipeId, recipe.id),
				orderBy: [desc(recipeVersions.version)],
			});
			const [version] = await ctx.db
				.insert(recipeVersions)
				.values({
					bodyMarkdown: input.bodyMarkdown,
					createdById: ctx.session.user.id,
					recipeId: recipe.id,
					version: (latest?.version ?? 0) + 1,
				})
				.returning();

			return { recipe, version };
		}),

	archiveRecipe: protectedProcedure
		.input(z.object({ recipeId: z.string().uuid() }))
		.mutation(async ({ ctx, input }) => {
			const [recipe] = await ctx.db
				.update(recipes)
				.set({ archivedAt: new Date() })
				.where(
					and(
						eq(recipes.id, input.recipeId),
						eq(recipes.ownerId, ctx.session.user.id),
					),
				)
				.returning();
			if (!recipe) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Recipe not found.",
				});
			}

			return recipe;
		}),

	getWorkspace: protectedProcedure
		.input(compatibleWorkspaceIdInput)
		.query(async ({ ctx, input }) =>
			getWorkspaceCompatibilityPayload({
				db: ctx.db,
				ownerId: ctx.session.user.id,
				workspaceId: resolveWorkspaceId(input),
			}),
		),

	getLatestWorkspace: protectedProcedure.query(async ({ ctx }) => {
		const workspace = await getLatestWorkspaceForOwner(
			ctx.db,
			ctx.session.user.id,
		);

		if (!workspace) {
			return null;
		}

		return getWorkspaceCompatibilityPayload({
			db: ctx.db,
			ownerId: ctx.session.user.id,
			workspaceId: workspace.id,
		});
	}),

	sendMessage: protectedProcedure
		.input(sendMessageInput)
		.mutation(async ({ ctx, input }) => {
			const wasFreshlyCreated = !(input.workspaceId ?? input.projectId);
			const taskKind =
				input.taskKind === "chat" &&
				shouldRouteChatPromptAsResearch(input.prompt)
					? "research"
					: input.taskKind;
			const result = await createMessageRunWithLaunch({
				db: ctx.db,
				input: {
					...input,
					taskKind,
					workspaceId: input.workspaceId ?? input.projectId,
				},
				ownerId: ctx.session.user.id,
			});

			if (wasFreshlyCreated) {
				const newWorkspaceId = result.workspace.id;
				void inferWorkspaceNameWithAi({ prompt: input.prompt }).then(
					async (name) => {
						try {
							await ctx.db
								.update(workspaces)
								.set({ name, autoNamedAt: new Date() })
								.where(eq(workspaces.id, newWorkspaceId));
						} catch {
							// Best-effort; don't fail the request.
						}
					},
				);
			}

			return result;
		}),

	getRunEvents: protectedProcedure
		.input(runEventsInput)
		.query(async ({ ctx, input }) => {
			const run = await ctx.db
				.select({ id: agentRuns.id })
				.from(agentRuns)
				.innerJoin(workspaces, eq(agentRuns.workspaceId, workspaces.id))
				.where(
					and(
						eq(agentRuns.id, input.runId),
						eq(workspaces.ownerId, ctx.session.user.id),
					),
				)
				.limit(1);

			if (!run[0]) {
				return [];
			}

			const events = await getRunEventsAfter({
				afterSequence: input.afterSequence,
				db: ctx.db,
				runId: input.runId,
			});

			return events.map(mapEvent);
		}),

	streamEvents: protectedProcedure
		.input(
			z.object({
				runId: z.string().uuid(),
				sinceSequence: z.number().int().min(0).default(0),
			}),
		)
		.query(async ({ ctx, input }) => {
			const run = await ctx.db.query.agentRuns.findFirst({
				where: eq(agentRuns.id, input.runId),
			});
			if (!run) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Run not found.",
				});
			}

			const workspace = await ctx.db.query.workspaces.findFirst({
				where: and(
					eq(workspaces.id, run.workspaceId),
					eq(workspaces.ownerId, ctx.session.user.id),
				),
			});
			if (!workspace) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Run not found.",
				});
			}

			const events = await ctx.db
				.select()
				.from(agentEvents)
				.where(
					and(
						eq(agentEvents.runId, input.runId),
						gt(agentEvents.sequence, input.sinceSequence),
					),
				)
				.orderBy(asc(agentEvents.sequence));

			return {
				events: events.map((event) => ({
					createdAt: event.createdAt.toISOString(),
					detail: event.summary ?? null,
					displayJson: event.displayJson ?? {},
					id: event.id,
					payloadJson: event.displayJson ?? {},
					rawJson: event.rawJson ?? {},
					sequence: event.sequence,
					summary: event.summary ?? null,
					title: event.title,
					type: event.type,
				})),
				runStatus: run.status,
			};
		}),

	mintRunStreamToken: protectedProcedure
		.input(z.object({ runId: z.string().uuid() }))
		.query(async ({ ctx, input }) => {
			const run = await ctx.db.query.agentRuns.findFirst({
				where: eq(agentRuns.id, input.runId),
			});
			if (!run) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Run not found.",
				});
			}
			const workspace = await ctx.db.query.workspaces.findFirst({
				where: and(
					eq(workspaces.id, run.workspaceId),
					eq(workspaces.ownerId, ctx.session.user.id),
				),
			});
			if (!workspace) {
				throw new TRPCError({
					code: "NOT_FOUND",
					message: "Run not found.",
				});
			}

			const secret = env.AUTOPEP_MODAL_WEBHOOK_SECRET;
			if (!secret) {
				throw new TRPCError({
					code: "INTERNAL_SERVER_ERROR",
					message: "Run stream secret not configured.",
				});
			}
			const baseUrl = env.AUTOPEP_MODAL_RUN_STREAM_URL;
			if (!baseUrl) {
				throw new TRPCError({
					code: "INTERNAL_SERVER_ERROR",
					message: "Run stream URL not configured.",
				});
			}

			const token = signRunStreamToken({
				payload: { runId: input.runId, userId: ctx.session.user.id },
				secret,
				expiresInSeconds: 60 * 60,
			});

			return {
				url: `${baseUrl}?runId=${input.runId}&token=${token}`,
			};
		}),

	answerQuestion: protectedProcedure
		.input(answerQuestionInput)
		.mutation(async ({ ctx, input }) => {
			const ownerId = ctx.session.user.id;
			const requestedWorkspaceId = input.workspaceId ?? input.projectId;
			const workspace = requestedWorkspaceId
				? await getWorkspaceCompatibilityPayload({
						db: ctx.db,
						ownerId,
						workspaceId: requestedWorkspaceId,
					})
				: null;
			const latestWorkspace = requestedWorkspaceId
				? null
				: await getLatestWorkspaceForOwner(ctx.db, ownerId);
			const workspacePayload =
				workspace ??
				(latestWorkspace
					? await getWorkspaceCompatibilityPayload({
							db: ctx.db,
							ownerId,
							workspaceId: latestWorkspace.id,
						})
					: null);

			return {
				answer: answerWorkspaceQuestion({
					question: input.question,
					workspace: workspacePayload,
				}),
			};
		}),

	createProjectRun: protectedProcedure
		.input(createProjectRunInput)
		.mutation(async ({ ctx, input }) =>
			createProjectRunWithLaunch({
				db: ctx.db,
				input,
				ownerId: ctx.session.user.id,
			}),
		),
});
