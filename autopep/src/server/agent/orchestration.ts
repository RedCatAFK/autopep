import { and, eq, sql } from "drizzle-orm";

import { db } from "@/server/db";
import {
	autopepAgentEvents,
	autopepAgentRuns,
	autopepArtifacts,
	autopepLiteratureHits,
	autopepProjectWorkspaces,
	autopepProjects,
	autopepProteinCandidates,
} from "@/server/db/schema";

export const LIFE_SCIENCE_RESEARCH_PLUGIN_REF =
	"github:openai/plugins/plugins/life-science-research@main";

export const DISCOVERY_AGENT_MODEL = "gpt-5.5";
export const DISCOVERY_AGENT_HARNESS = "codex";
export const DISCOVERY_MODAL_APP_NAME = "autopep-discovery-agent";
export const DISCOVERY_MODAL_VOLUME_NAME = "autopep-project-workspaces";
export const DISCOVERY_WORKSPACE_MOUNT = "/workspace/autopep";
export const PROJECT_WORKSPACE_PREFIX = "/projects";

export const DISCOVERY_PHASES = [
	"intake",
	"entity_normalization",
	"pdb_search",
	"literature_search",
	"ranking",
	"pdb_download",
	"artifact_sync",
	"ready_for_complexa",
	"failed",
] as const;

export type DiscoveryPhase = (typeof DISCOVERY_PHASES)[number];

export function modalWorkspaceVolumeName() {
	return DISCOVERY_MODAL_VOLUME_NAME;
}

export function projectWorkspaceRoot(projectId: string) {
	return `${PROJECT_WORKSPACE_PREFIX}/${projectId}`;
}

export async function createAutopepProject(input: {
	createdById: string;
	name: string;
	objective: string;
	targetDescription?: string;
}) {
	return db.transaction(async (tx) => {
		const [project] = await tx
			.insert(autopepProjects)
			.values({
				createdById: input.createdById,
				name: input.name,
				objective: input.objective,
				targetDescription: input.targetDescription,
			})
			.returning();

		if (!project) {
			throw new Error("Failed to create Autopep project.");
		}

		const [workspace] = await tx
			.insert(autopepProjectWorkspaces)
			.values({
				projectId: project.id,
				modalAppName: DISCOVERY_MODAL_APP_NAME,
				modalVolumeName: modalWorkspaceVolumeName(),
				volumeRoot: projectWorkspaceRoot(project.id),
			})
			.returning();

		if (!workspace) {
			throw new Error("Failed to create Autopep project workspace.");
		}

		return { project, workspace };
	});
}

export async function createDiscoveryRun(input: {
	projectId: string;
	objective: string;
	topK?: number;
	metadata?: Record<string, unknown>;
}) {
	const [run] = await db
		.insert(autopepAgentRuns)
		.values({
			projectId: input.projectId,
			objective: input.objective,
			status: "queued",
			phase: "intake",
			model: DISCOVERY_AGENT_MODEL,
			harnessName: DISCOVERY_AGENT_HARNESS,
			lifeSciencePluginRef: LIFE_SCIENCE_RESEARCH_PLUGIN_REF,
			topK: input.topK ?? 5,
			metadata: input.metadata ?? {},
		})
		.returning();

	if (!run) {
		throw new Error("Failed to create discovery run.");
	}

	await appendRunEvent({
		runId: run.id,
		phase: "intake",
		type: "run.created",
		message: "Discovery run queued.",
		payload: {
			model: DISCOVERY_AGENT_MODEL,
			plugin: LIFE_SCIENCE_RESEARCH_PLUGIN_REF,
			topK: run.topK,
		},
	});

	return run;
}

export async function startDiscoveryRun(input: {
	runId: string;
	modalSandboxId?: string;
	modalSandboxName?: string;
}) {
	const [run] = await db
		.update(autopepAgentRuns)
		.set({
			modalSandboxId: input.modalSandboxId,
			modalSandboxName: input.modalSandboxName,
			status: "running",
			startedAt: new Date(),
		})
		.where(eq(autopepAgentRuns.id, input.runId))
		.returning();

	if (!run) {
		throw new Error("Discovery run not found.");
	}

	await appendRunEvent({
		runId: input.runId,
		phase: run.phase,
		type: "run.started",
		message: "Codex discovery harness started.",
		payload: {
			modalSandboxId: input.modalSandboxId,
			modalSandboxName: input.modalSandboxName,
		},
	});

	return run;
}

export async function setRunPhase(input: {
	runId: string;
	phase: DiscoveryPhase;
	message?: string;
	payload?: Record<string, unknown>;
}) {
	const [run] = await db
		.update(autopepAgentRuns)
		.set({ phase: input.phase })
		.where(eq(autopepAgentRuns.id, input.runId))
		.returning();

	if (!run) {
		throw new Error("Discovery run not found.");
	}

	await appendRunEvent({
		runId: input.runId,
		phase: input.phase,
		type: "run.phase_changed",
		message: input.message ?? `Discovery phase changed to ${input.phase}.`,
		payload: input.payload,
	});

	return run;
}

export async function finishDiscoveryRun(input: {
	runId: string;
	status: "succeeded" | "failed" | "canceled";
	errorMessage?: string;
	modalFilesystemSnapshotImageId?: string;
}) {
	const phase = input.status === "succeeded" ? "ready_for_complexa" : "failed";
	const [run] = await db
		.update(autopepAgentRuns)
		.set({
			completedAt: new Date(),
			errorMessage: input.errorMessage,
			modalFilesystemSnapshotImageId: input.modalFilesystemSnapshotImageId,
			phase,
			status: input.status,
		})
		.where(eq(autopepAgentRuns.id, input.runId))
		.returning();

	if (!run) {
		throw new Error("Discovery run not found.");
	}

	await appendRunEvent({
		runId: input.runId,
		phase,
		level: input.status === "failed" ? "error" : "info",
		type: `run.${input.status}`,
		message:
			input.status === "succeeded"
				? "Top protein PDB artifacts are ready for Proteina-Complexa."
				: (input.errorMessage ?? `Discovery run ${input.status}.`),
		payload: {
			modalFilesystemSnapshotImageId: input.modalFilesystemSnapshotImageId,
		},
	});

	return run;
}

export async function appendRunEvent(input: {
	runId: string;
	type: string;
	message: string;
	level?: "debug" | "info" | "warn" | "error";
	phase?: DiscoveryPhase;
	payload?: Record<string, unknown>;
}) {
	return db.transaction(async (tx) => {
		const [sequenceRow] = await tx
			.select({
				nextSequence:
					sql<number>`coalesce(max(${autopepAgentEvents.sequence}), 0) + 1`,
			})
			.from(autopepAgentEvents)
			.where(eq(autopepAgentEvents.runId, input.runId));

		const [event] = await tx
			.insert(autopepAgentEvents)
			.values({
				runId: input.runId,
				sequence: sequenceRow?.nextSequence ?? 1,
				phase: input.phase,
				level: input.level ?? "info",
				type: input.type,
				message: input.message,
				payload: input.payload ?? {},
			})
			.returning();

		if (!event) {
			throw new Error("Failed to append discovery event.");
		}

		return event;
	});
}

export async function recordProteinCandidate(input: {
	projectId: string;
	runId: string;
	rank: number;
	title: string;
	selectionRationale: string;
	pdbId?: string;
	chainIds?: string[];
	sourceDatabase?: string;
	sourceUrl?: string;
	organism?: string;
	experimentalMethod?: string;
	resolutionAngstrom?: number;
	relevanceScore?: number;
	metadata?: Record<string, unknown>;
}) {
	const [candidate] = await db
		.insert(autopepProteinCandidates)
		.values({
			projectId: input.projectId,
			runId: input.runId,
			rank: input.rank,
			title: input.title,
			selectionRationale: input.selectionRationale,
			pdbId: input.pdbId,
			chainIds: input.chainIds ?? [],
			sourceDatabase: input.sourceDatabase,
			sourceUrl: input.sourceUrl,
			organism: input.organism,
			experimentalMethod: input.experimentalMethod,
			resolutionAngstrom: input.resolutionAngstrom,
			relevanceScore: input.relevanceScore,
			metadata: input.metadata ?? {},
		})
		.returning();

	if (!candidate) {
		throw new Error("Failed to record protein candidate.");
	}

	await appendRunEvent({
		runId: input.runId,
		phase: "ranking",
		type: "protein_candidate.recorded",
		message: `Ranked protein candidate ${input.rank}: ${input.title}`,
		payload: {
			candidateId: candidate.id,
			pdbId: input.pdbId,
			relevanceScore: input.relevanceScore,
		},
	});

	return candidate;
}

export async function recordPdbArtifact(input: {
	projectId: string;
	runId: string;
	proteinCandidateId: string;
	displayName: string;
	contentText: string;
	contentSha256: string;
	modalVolumeName: string;
	modalPath: string;
	sizeBytes: number;
	metadata?: Record<string, unknown>;
}) {
	const [artifact] = await db
		.insert(autopepArtifacts)
		.values({
			projectId: input.projectId,
			runId: input.runId,
			proteinCandidateId: input.proteinCandidateId,
			type: "pdb",
			storageKind: "neon",
			displayName: input.displayName,
			mimeType: "chemical/x-pdb",
			contentText: input.contentText,
			contentSha256: input.contentSha256,
			modalVolumeName: input.modalVolumeName,
			modalPath: input.modalPath,
			sizeBytes: input.sizeBytes,
			metadata: input.metadata ?? {},
		})
		.returning();

	if (!artifact) {
		throw new Error("Failed to record PDB artifact.");
	}

	await appendRunEvent({
		runId: input.runId,
		phase: "artifact_sync",
		type: "artifact.pdb_synced",
		message: `Synced PDB artifact ${input.displayName}.`,
		payload: {
			artifactId: artifact.id,
			modalPath: input.modalPath,
			sizeBytes: input.sizeBytes,
		},
	});

	return artifact;
}

export async function recordLiteratureHit(input: {
	projectId: string;
	runId: string;
	source: "pubmed" | "pmc" | "biorxiv" | "medrxiv" | "other";
	title: string;
	abstract?: string;
	doi?: string;
	pmid?: string;
	pmcid?: string;
	url?: string;
	publishedAt?: Date;
	relevanceScore?: number;
	summary?: string;
	metadata?: Record<string, unknown>;
}) {
	const [hit] = await db
		.insert(autopepLiteratureHits)
		.values({
			projectId: input.projectId,
			runId: input.runId,
			source: input.source,
			title: input.title,
			abstract: input.abstract,
			doi: input.doi,
			pmid: input.pmid,
			pmcid: input.pmcid,
			url: input.url,
			publishedAt: input.publishedAt,
			relevanceScore: input.relevanceScore,
			summary: input.summary,
			metadata: input.metadata ?? {},
		})
		.returning();

	if (!hit) {
		throw new Error("Failed to record literature hit.");
	}

	return hit;
}

export async function assertProjectOwner(input: {
	projectId: string;
	userId: string;
}) {
	const project = await db.query.autopepProjects.findFirst({
		where: and(
			eq(autopepProjects.id, input.projectId),
			eq(autopepProjects.createdById, input.userId),
		),
	});

	if (!project) {
		throw new Error("Autopep project not found.");
	}

	return project;
}
