import { randomUUID } from "node:crypto";
import { setTimeout as sleep } from "node:timers/promises";

import { HeadObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { and, asc, desc, eq } from "drizzle-orm";

import { env } from "@/env";
import { demoRecipeBody, demoRecipeName } from "@/server/agent/demo-recipe";
import { createMessageRunWithLaunch } from "@/server/agent/project-run-creator";
import { db } from "@/server/db";
import {
	agentEvents,
	agentRuns,
	artifacts,
	candidateScores,
	modelInferences,
	proteinCandidates,
	recipeVersions,
	recipes,
	threads,
	user,
	workspaces,
} from "@/server/db/schema";

const smokeTaskKinds = [
	"smoke_chat",
	"smoke_tool",
	"smoke_sandbox",
	"branch_design",
] as const;
type SmokeTaskKind = (typeof smokeTaskKinds)[number];
type ArtifactRow = typeof artifacts.$inferSelect;

const usage =
	"Usage: bun run scripts/smoke-roundtrip.ts <smoke_chat|smoke_tool|smoke_sandbox|branch_design>";

const isSmokeTaskKind = (value: string): value is SmokeTaskKind =>
	(smokeTaskKinds as readonly string[]).includes(value);

const requiredEventTypes = (taskKind: SmokeTaskKind) => {
	const required = [
		"run_started",
		"assistant_message_completed",
		"run_completed",
	];
	if (taskKind === "smoke_tool") {
		required.push("tool_call_completed");
	}
	if (taskKind === "smoke_sandbox") {
		required.push("sandbox_command_completed", "sandbox_stdout_delta");
	}
	if (taskKind === "branch_design") {
		required.push(
			"tool_call_started",
			"tool_call_completed",
			"artifact_created",
			"candidate_ranked",
		);
	}
	return required;
};

const ensureUser = async (ownerId?: string) => {
	const id = ownerId ?? `autopep-smoke-${randomUUID()}`;
	const existing = await db.query.user.findFirst({ where: eq(user.id, id) });
	if (existing) {
		return existing.id;
	}

	const now = new Date();
	await db.insert(user).values({
		createdAt: now,
		email: `${id.replace(/[^a-zA-Z0-9_-]/g, "-")}@smoke.autopep.invalid`,
		emailVerified: true,
		id,
		name: "Autopep Smoke",
		updatedAt: now,
	});
	return id;
};

const ensureWorkspace = async ({
	ownerId,
	workspaceId,
}: {
	ownerId: string;
	workspaceId?: string;
}) => {
	if (workspaceId) {
		const workspace = await db.query.workspaces.findFirst({
			where: eq(workspaces.id, workspaceId),
		});
		if (!workspace) {
			throw new Error(`Smoke workspace not found: ${workspaceId}`);
		}
		if (workspace.ownerId !== ownerId) {
			throw new Error("Smoke workspace is not owned by the smoke owner.");
		}
		return workspace;
	}

	const [workspace] = await db
		.insert(workspaces)
		.values({
			description: "Autopep integration smoke workspace",
			name: "Autopep smoke",
			ownerId,
		})
		.returning();

	if (!workspace) {
		throw new Error("Failed to create smoke workspace.");
	}
	return workspace;
};

const ensureThread = async ({
	threadId,
	workspace,
}: {
	threadId?: string;
	workspace: typeof workspaces.$inferSelect;
}) => {
	if (threadId) {
		const thread = await db.query.threads.findFirst({
			where: and(eq(threads.id, threadId), eq(threads.workspaceId, workspace.id)),
		});
		if (!thread) {
			throw new Error(`Smoke thread not found in workspace: ${threadId}`);
		}
		return thread;
	}

	if (workspace.activeThreadId) {
		const activeThread = await db.query.threads.findFirst({
			where: and(
				eq(threads.id, workspace.activeThreadId),
				eq(threads.workspaceId, workspace.id),
			),
		});
		if (activeThread) {
			return activeThread;
		}
	}

	const latestThread = await db.query.threads.findFirst({
		orderBy: [desc(threads.updatedAt)],
		where: eq(threads.workspaceId, workspace.id),
	});
	if (latestThread) {
		return latestThread;
	}

	const [thread] = await db
		.insert(threads)
		.values({
			title: "Smoke thread",
			workspaceId: workspace.id,
		})
		.returning();
	if (!thread) {
		throw new Error("Failed to create smoke thread.");
	}

	await db
		.update(workspaces)
		.set({ activeThreadId: thread.id })
		.where(eq(workspaces.id, workspace.id));
	return thread;
};

const ensureDemoRecipe = async ({
	ownerId,
	workspaceId,
}: {
	ownerId: string;
	workspaceId: string;
}) => {
	const existing = await db.query.recipes.findFirst({
		where: and(
			eq(recipes.ownerId, ownerId),
			eq(recipes.workspaceId, workspaceId),
			eq(recipes.name, demoRecipeName),
		),
	});
	if (existing) {
		const latest = await db.query.recipeVersions.findFirst({
			orderBy: [desc(recipeVersions.version)],
			where: eq(recipeVersions.recipeId, existing.id),
		});
		if (latest?.bodyMarkdown === demoRecipeBody) {
			return existing.id;
		}
		const [version] = await db
			.insert(recipeVersions)
			.values({
				bodyMarkdown: demoRecipeBody,
				createdById: ownerId,
				recipeId: existing.id,
				version: (latest?.version ?? 0) + 1,
			})
			.returning();
		if (!version) {
			throw new Error("Failed to create demo recipe version.");
		}
		return existing.id;
	}

	const [recipe] = await db
		.insert(recipes)
		.values({
			bodyMarkdown: demoRecipeBody,
			description: "Default recipe for the backend 3CL-protease demo gate.",
			enabledByDefault: true,
			name: demoRecipeName,
			ownerId,
			workspaceId,
		})
		.returning();
	if (!recipe) {
		throw new Error("Failed to create demo recipe.");
	}
	const [version] = await db
		.insert(recipeVersions)
		.values({
			bodyMarkdown: demoRecipeBody,
			createdById: ownerId,
			recipeId: recipe.id,
			version: 1,
		})
		.returning();
	if (!version) {
		throw new Error("Failed to create demo recipe version.");
	}
	return recipe.id;
};

const pollRun = async (runId: string, taskKind: SmokeTaskKind) => {
	const deadline =
		Date.now() + (taskKind === "branch_design" ? 900_000 : 180_000);
	while (Date.now() < deadline) {
		const run = await db.query.agentRuns.findFirst({
			where: eq(agentRuns.id, runId),
		});
		if (!run) {
			throw new Error(`Smoke run disappeared: ${runId}`);
		}
		if (run.status === "completed" || run.status === "failed") {
			return run;
		}
		await sleep(2_000);
	}
	throw new Error(`Timed out waiting for smoke run: ${runId}`);
};

const assertEvents = async ({
	runId,
	taskKind,
}: {
	runId: string;
	taskKind: SmokeTaskKind;
}) => {
	const events = await db.query.agentEvents.findMany({
		orderBy: [asc(agentEvents.sequence)],
		where: eq(agentEvents.runId, runId),
	});
	if (events.length === 0) {
		throw new Error("Smoke run did not record any events.");
	}

	for (const [index, event] of events.entries()) {
		const expectedSequence = index + 1;
		if (event.sequence !== expectedSequence) {
			throw new Error(
				`Smoke event sequence gap: expected ${expectedSequence}, got ${event.sequence}`,
			);
		}
	}

	const eventTypes = new Set(events.map((event) => event.type));
	for (const required of requiredEventTypes(taskKind)) {
		if (!eventTypes.has(required)) {
			throw new Error(`Smoke event missing required type: ${required}`);
		}
	}

	if (taskKind === "smoke_sandbox") {
		const stdout = events
			.filter((event) => event.type === "sandbox_stdout_delta")
			.map((event) => JSON.stringify(event.displayJson ?? {}))
			.join("\n");
		if (!stdout.includes("sandbox-ok")) {
			throw new Error("Smoke sandbox stdout did not contain sandbox-ok.");
		}
	}

	return events;
};

const assertBranchDesignPersistence = async (runId: string) => {
	const [
		artifactRows,
		candidateRows,
		inferenceRows,
		scoreRows,
	] = await Promise.all([
		db.query.artifacts.findMany({ where: eq(artifacts.runId, runId) }),
		db.query.proteinCandidates.findMany({
			where: eq(proteinCandidates.runId, runId),
		}),
		db.query.modelInferences.findMany({
			where: eq(modelInferences.runId, runId),
		}),
		db.query.candidateScores.findMany({
			where: eq(candidateScores.runId, runId),
		}),
	]);

	const artifactKinds = new Set(artifactRows.map((artifact) => artifact.kind));
	for (const required of [
		"literature_snapshot",
		"pdb_metadata",
		"pdb",
		"proteina_result",
		"chai_result",
	] as const) {
		if (!artifactKinds.has(required)) {
			throw new Error(`Demo run missing artifact kind: ${required}`);
		}
	}

	const inferenceModels = new Set(
		inferenceRows.map((inference) => inference.modelName),
	);
	for (const required of [
		"proteina_complexa",
		"chai_1",
		"protein_interaction_scoring",
	] as const) {
		if (!inferenceModels.has(required)) {
			throw new Error(`Demo run missing inference model: ${required}`);
		}
	}

	const validLabels = new Set([
		"likely_binder",
		"possible_binder",
		"unlikely_binder",
		"insufficient_data",
	]);

	const scorers = new Set(scoreRows.map((score) => score.scorer));
	for (const required of [
		"dscript",
		"prodigy",
		"protein_interaction_aggregate",
	] as const) {
		if (!scorers.has(required)) {
			throw new Error(`Demo run missing scorer: ${required}`);
		}
		const matching = scoreRows.filter((score) => score.scorer === required);
		// Per-row sanity: status must not be 'unavailable' (the scorer must have
		// actually run) and per-scorer rules below.
		for (const score of matching) {
			if (score.status === "unavailable") {
				throw new Error(
					`Demo run scorer ${required} is unavailable (status=unavailable, candidate=${score.candidateId}). Modal endpoint likely not configured.`,
				);
			}
		}

		if (required === "protein_interaction_aggregate") {
			// The aggregate scorer summarizes the per-scorer results, so we hold
			// it to the strictest bar: status must be ok|partial and label must be
			// a valid enum value.
			for (const score of matching) {
				if (score.status === "failed") {
					throw new Error(
						`Demo aggregate scorer failed (candidate=${score.candidateId}).`,
					);
				}
				if (!score.label || !validLabels.has(score.label)) {
					throw new Error(
						`Demo aggregate scorer produced invalid label '${score.label ?? "null"}' (candidate=${score.candidateId}).`,
					);
				}
			}
		} else {
			// D-SCRIPT / PRODIGY may report 'partial' when one input is missing
			// but should not be flat-out failed.
			for (const score of matching) {
				if (score.status === "failed") {
					throw new Error(
						`Demo scorer ${required} failed (candidate=${score.candidateId}).`,
					);
				}
			}
		}
	}

	if (candidateRows.length < 1) {
		throw new Error("Demo run did not persist any protein candidates.");
	}
	if (!candidateRows.some((candidate) => candidate.foldArtifactId)) {
		throw new Error("Demo run did not link any protein candidate to a Chai fold artifact.");
	}

	await assertR2ArtifactsExist({
		artifactRows,
		requiredKinds: [
			"literature_snapshot",
			"pdb_metadata",
			"pdb",
			"proteina_result",
			"chai_result",
		],
	});

	return {
		artifactCount: artifactRows.length,
		candidateCount: candidateRows.length,
		inferenceCount: inferenceRows.length,
		r2ObjectCount: artifactRows.length,
		scoreCount: scoreRows.length,
	};
};

const assertR2ArtifactsExist = async ({
	artifactRows,
	requiredKinds,
}: {
	artifactRows: ArtifactRow[];
	requiredKinds: readonly string[];
}) => {
	const r2Client = new S3Client({
		credentials: {
			accessKeyId: env.R2_ACCESS_KEY_ID,
			secretAccessKey: env.R2_SECRET_ACCESS_KEY,
		},
		endpoint: `https://${env.R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
		region: "auto",
	});

	const artifactsToCheck = artifactRows.filter((artifact) =>
		requiredKinds.includes(artifact.kind),
	);
	for (const artifact of artifactsToCheck) {
		if (artifact.storageProvider !== "r2") {
			throw new Error(
				`Demo artifact ${artifact.id} uses ${artifact.storageProvider}, expected r2.`,
			);
		}

		const head = await r2Client.send(
			new HeadObjectCommand({
				Bucket: env.R2_BUCKET,
				Key: artifact.storageKey,
			}),
		);

		if (head.ContentLength !== artifact.sizeBytes) {
			throw new Error(
				`Demo artifact ${artifact.id} (${artifact.kind}, key=${artifact.storageKey}) ` +
					`size mismatch: R2 ContentLength=${head.ContentLength ?? "null"}, ` +
					`db sizeBytes=${artifact.sizeBytes}.`,
			);
		}
	}
};

const main = async () => {
	const taskKind = process.argv[2];
	if (!taskKind || !isSmokeTaskKind(taskKind)) {
		throw new Error(usage);
	}

	const ownerId = await ensureUser(process.env.AUTOPEP_SMOKE_OWNER_ID);
	const workspace = await ensureWorkspace({
		ownerId,
		workspaceId: process.env.AUTOPEP_SMOKE_WORKSPACE_ID,
	});
	const thread = await ensureThread({
		threadId: process.env.AUTOPEP_SMOKE_THREAD_ID,
		workspace,
	});

	console.log("Smoke IDs for env reuse:");
	console.log(`AUTOPEP_SMOKE_OWNER_ID=${ownerId}`);
	console.log(`AUTOPEP_SMOKE_WORKSPACE_ID=${workspace.id}`);
	console.log(`AUTOPEP_SMOKE_THREAD_ID=${thread.id}`);

	const recipeId =
		taskKind === "branch_design"
			? await ensureDemoRecipe({ ownerId, workspaceId: workspace.id })
			: null;

	const created = await createMessageRunWithLaunch({
		db,
		input: {
			prompt:
				taskKind === "branch_design"
					? "Generate a protein that binds to 3CL-protease"
					: "ping",
			recipeRefs: recipeId ? [recipeId] : [],
			taskKind,
			threadId: thread.id,
			workspaceId: workspace.id,
		},
		ownerId,
	});

	console.log(`Smoke run launched: ${created.run.id}`);
	const run = await pollRun(created.run.id, taskKind);
	if (run.status !== "completed") {
		throw new Error(`Smoke run failed: ${run.errorSummary ?? "unknown error"}`);
	}
	if (!run.finishedAt) {
		throw new Error("Smoke run completed without finishedAt.");
	}

	const events = await assertEvents({ runId: run.id, taskKind });
	if (taskKind === "branch_design") {
		const persisted = await assertBranchDesignPersistence(run.id);
		console.log(`Demo persistence: ${JSON.stringify(persisted)}`);
	}
	console.log(
		`Smoke ${taskKind} completed with ${events.length} contiguous events.`,
	);
	if (run.lastResponseId) {
		console.log(`Last response ID: ${run.lastResponseId}`);
	}
};

main()
	.then(() => {
		process.exit(0);
	})
	.catch((error: unknown) => {
		const message = error instanceof Error ? error.message : String(error);
		console.error(message);
		process.exit(1);
	});
