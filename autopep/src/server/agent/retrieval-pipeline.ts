import { eq } from "drizzle-orm";

import { env } from "@/env";
import { buildArtifactKey } from "@/server/artifacts/keys";
import { r2ArtifactStore } from "@/server/artifacts/r2";
import type { db as appDb } from "@/server/db";
import {
	agentRuns,
	artifacts,
	proteinCandidates,
	targetEntities,
} from "@/server/db/schema";
import { appendRunEvent } from "./events";
import { type PubMedRef, searchPubMed } from "./pubmed-client";
import {
	downloadRcsbCif,
	getRcsbCifUrl,
	searchRcsbEntries,
} from "./rcsb-client";

type FetchImpl = typeof fetch;

type RunCifRetrievalPipelineInput = {
	db: typeof appDb;
	runId: string;
	fetchImpl?: FetchImpl;
};

type NormalizedTarget = {
	name: string;
	aliases: string[];
	organism: string | null;
	uniprotId: string | null;
	role: string;
	rationale: string;
};

const defaultTopK = 5;
const cifContentType = "chemical/x-cif";

const stripPromptPrefix = (prompt: string) =>
	prompt
		.replace(
			/^\s*(generate|design|find|create|make|build)\s+(a\s+|an\s+)?(binder|peptide|protein|candidate|structure)?\s*(for|against|to|targeting)?\s*/iu,
			"",
		)
		.trim();

const normalizeTarget = (prompt: string): NormalizedTarget => {
	const normalizedPrompt = prompt.toLowerCase();

	if (/\b(3cl|3clpro|main protease|mpro|protease)\b/u.test(normalizedPrompt)) {
		return {
			aliases: ["3CLpro", "main protease", "Mpro"],
			name: "SARS-CoV-2 3CL protease",
			organism: "SARS-CoV-2",
			rationale:
				"Prompt matched common names for the SARS-CoV-2 main protease target.",
			role: "target",
			uniprotId: null,
		};
	}

	if (/\b(spike|rbd|receptor binding domain)\b/u.test(normalizedPrompt)) {
		return {
			aliases: ["RBD", "spike receptor binding domain"],
			name: "SARS-CoV-2 spike receptor binding domain",
			organism: "SARS-CoV-2",
			rationale: "Prompt matched spike/RBD target terminology.",
			role: "target",
			uniprotId: null,
		};
	}

	return {
		aliases: [],
		name: stripPromptPrefix(prompt) || prompt.trim(),
		organism: null,
		rationale: "Target name normalized from the user prompt.",
		role: "target",
		uniprotId: null,
	};
};

const clamp01 = (value: number) => Math.max(0, Math.min(1, value));

const markRunFailed = async ({
	db,
	error,
	runId,
}: {
	db: typeof appDb;
	error: unknown;
	runId: string;
}) => {
	const errorSummary = error instanceof Error ? error.message : String(error);

	await db
		.update(agentRuns)
		.set({
			errorSummary,
			finishedAt: new Date(),
			status: "failed",
		})
		.where(eq(agentRuns.id, runId));

	try {
		await appendRunEvent({
			db,
			detail: errorSummary,
			runId,
			title: "CIF retrieval failed",
			type: "run_failed",
		});
	} catch {
		// The run status is the source of truth if event insertion also fails.
	}

	throw error;
};

export const runCifRetrievalPipeline = async ({
	db,
	runId,
	fetchImpl = fetch,
}: RunCifRetrievalPipelineInput) => {
	const run = await db.query.agentRuns.findFirst({
		where: eq(agentRuns.id, runId),
	});

	if (!run) {
		throw new Error(`Agent run ${runId} was not found.`);
	}

	try {
		await db
			.update(agentRuns)
			.set({
				startedAt: run.startedAt ?? new Date(),
				status: "running",
			})
			.where(eq(agentRuns.id, runId));

		await appendRunEvent({
			db,
			runId,
			title: "Normalizing target",
			type: "normalizing_target",
		});

		const target = normalizeTarget(run.prompt);
		const [targetEntity] = await db
			.insert(targetEntities)
			.values({
				aliasesJson: target.aliases,
				name: target.name,
				organism: target.organism,
				rationale: target.rationale,
				role: target.role,
				runId,
				uniprotId: target.uniprotId,
			})
			.returning();

		if (!targetEntity) {
			throw new Error("Failed to insert target entity.");
		}

		await appendRunEvent({
			db,
			detail: target.name,
			payload: { target },
			runId,
			title: "Searching RCSB structures",
			type: "searching_structures",
		});

		const topK = run.topK || defaultTopK;
		const rcsbIds = await searchRcsbEntries({
			fetchImpl,
			query: target.name,
			rows: topK,
		});

		if (rcsbIds.length === 0) {
			throw new Error(`No RCSB CIF structures found for ${target.name}.`);
		}

		await appendRunEvent({
			db,
			detail: `Found ${rcsbIds.length} candidate structures.`,
			payload: { rcsbIds },
			runId,
			title: "Searching PubMed literature",
			type: "searching_literature",
		});

		let pubmedRefs: PubMedRef[] = [];
		try {
			pubmedRefs = await searchPubMed({
				fetchImpl,
				query: `${target.name} structure`,
				retmax: Math.min(topK, 10),
			});
		} catch (error) {
			await appendRunEvent({
				db,
				detail: error instanceof Error ? error.message : String(error),
				runId,
				title: "PubMed search failed",
				type: "source_failed",
			});
		}

		await appendRunEvent({
			db,
			runId,
			title: "Ranking candidates",
			type: "ranking_candidates",
		});

		const insertedCandidates = await db
			.insert(proteinCandidates)
			.values(
				rcsbIds.map((rcsbId, index) => {
					const relevanceScore = clamp01(1 - index * 0.08);

					return {
						assemblyId: "1",
						chainIdsJson: [],
						citationJson: { pubmed: pubmedRefs },
						confidence: clamp01(relevanceScore - 0.1),
						ligandIdsJson: [],
						method: null,
						organism: target.organism,
						proteinaReady: index === 0,
						rank: index + 1,
						rcsbId,
						relevanceScore,
						resolutionAngstrom: null,
						runId,
						selectionRationale:
							index === 0
								? "Top RCSB full-text match selected for source CIF retrieval."
								: "RCSB full-text match retained as an alternate candidate.",
						targetEntityId: targetEntity.id,
						title: `${rcsbId} structure for ${target.name}`,
					};
				}),
			)
			.returning();

		const topCandidate = insertedCandidates[0];
		if (!topCandidate) {
			throw new Error("Failed to insert protein candidates.");
		}

		await appendRunEvent({
			db,
			detail: topCandidate.rcsbId,
			runId,
			title: "Downloading source CIF",
			type: "downloading_cif",
		});

		const cifText = await downloadRcsbCif({
			entryId: topCandidate.rcsbId,
			fetchImpl,
		});
		const cifBytes = new TextEncoder().encode(cifText);
		const fileName = `${topCandidate.rcsbId.toLowerCase()}-source.cif`;
		const objectKey = buildArtifactKey({
			candidateId: topCandidate.id,
			fileName,
			projectId: run.projectId,
			runId,
			type: "source_cif",
		});

		await appendRunEvent({
			db,
			detail: objectKey,
			runId,
			title: "Uploading CIF artifact",
			type: "uploading_artifact",
		});

		await r2ArtifactStore.upload({
			body: cifBytes,
			contentType: cifContentType,
			key: objectKey,
		});

		await db.insert(artifacts).values({
			bucket: env.R2_BUCKET,
			byteSize: cifBytes.byteLength,
			candidateId: topCandidate.id,
			contentType: cifContentType,
			fileName,
			metadataJson: {
				format: "mmcif",
				rcsbId: topCandidate.rcsbId,
			},
			objectKey,
			projectId: run.projectId,
			runId,
			sourceUrl: getRcsbCifUrl(topCandidate.rcsbId),
			type: "source_cif",
			viewerHint: "molstar",
		});

		await appendRunEvent({
			db,
			detail: `${topCandidate.rcsbId} source CIF is ready.`,
			payload: {
				candidateId: topCandidate.id,
				objectKey,
				rcsbId: topCandidate.rcsbId,
			},
			runId,
			title: "Ready for Proteina",
			type: "ready_for_proteina",
		});

		await db
			.update(agentRuns)
			.set({
				finishedAt: new Date(),
				status: "succeeded",
			})
			.where(eq(agentRuns.id, runId));

		return {
			candidateId: topCandidate.id,
			objectKey,
			rcsbId: topCandidate.rcsbId,
			runId,
		};
	} catch (error) {
		return markRunFailed({ db, error, runId });
	}
};
