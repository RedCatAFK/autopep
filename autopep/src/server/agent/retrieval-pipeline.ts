import { eq } from "drizzle-orm";

import { env } from "@/env";
import { buildArtifactKey } from "@/server/artifacts/keys";
import { r2ArtifactStore } from "@/server/artifacts/r2";
import type { db as appDb } from "@/server/db";
import { agentRuns, artifacts, proteinCandidates } from "@/server/db/schema";
import { type BioRxivRef, searchBioRxivPreprints } from "./biorxiv-client";
import { appendRunEvent } from "./events";
import { type PubMedRef, searchPubMed } from "./pubmed-client";
import {
	downloadRcsbCif,
	getRcsbCifUrl,
	getRcsbEntryMetadata,
	type RcsbEntryMetadata,
	searchRcsbEntries,
} from "./rcsb-client";
import { resolveRequestedTopK } from "./top-k";

type FetchImpl = typeof fetch;

type RunCifRetrievalPipelineInput = {
	db: typeof appDb;
	runId: string;
	fetchImpl?: FetchImpl;
	topK?: number;
};

type NormalizedTarget = {
	name: string;
	aliases: string[];
	organism: string | null;
	uniprotId: string | null;
	role: string;
	rationale: string;
};

export type RankedRcsbCandidate = {
	assemblyId: string;
	chainIdsJson: string[];
	citationJson: { biorxiv: BioRxivRef[]; pubmed: PubMedRef[] };
	confidence: number;
	ligandIdsJson: string[];
	method: string | null;
	organism: string | null;
	proteinaReady: boolean;
	rank: number;
	rcsbId: string;
	relevanceScore: number;
	resolutionAngstrom: number | null;
	selectionRationale: string;
	title: string;
};

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

const tokenizeForRanking = (value: string) =>
	value
		.toLowerCase()
		.split(/[^a-z0-9]+/u)
		.filter((token) => token.length >= 3);

const scoreTitleMatch = (targetName: string, title: string | null) => {
	if (!title) {
		return 0;
	}

	const targetTokens = new Set(tokenizeForRanking(targetName));
	if (targetTokens.size === 0) {
		return 0;
	}

	const titleTokens = new Set(tokenizeForRanking(title));
	const matches = [...targetTokens].filter((token) => titleTokens.has(token));
	return matches.length / targetTokens.size;
};

const scoreMethod = (method: string | null) => {
	if (!method) {
		return 0;
	}

	const normalized = method.toLowerCase();
	if (normalized.includes("x-ray") || normalized.includes("electron")) {
		return 0.08;
	}
	if (normalized.includes("nmr")) {
		return 0.04;
	}

	return 0.02;
};

const scoreResolution = (resolutionAngstrom: number | null) => {
	if (resolutionAngstrom === null) {
		return 0;
	}

	if (resolutionAngstrom <= 2) {
		return 0.12;
	}
	if (resolutionAngstrom <= 3) {
		return 0.08;
	}
	if (resolutionAngstrom <= 4) {
		return 0.04;
	}

	return 0.01;
};

export const rankRcsbCandidates = ({
	metadataById,
	biorxivRefs,
	pubmedRefs,
	rcsbIds,
	target,
}: {
	metadataById: Map<string, RcsbEntryMetadata>;
	biorxivRefs: BioRxivRef[];
	pubmedRefs: PubMedRef[];
	rcsbIds: string[];
	target: NormalizedTarget;
}): RankedRcsbCandidate[] => {
	const ranked = rcsbIds.map((rcsbId, index) => {
		const normalizedId = rcsbId.trim().toUpperCase();
		const metadata = metadataById.get(normalizedId);
		const title =
			metadata?.title ?? `${normalizedId} structure for ${target.name}`;
		const searchOrderScore = clamp01(1 - index * 0.08);
		const titleScore = scoreTitleMatch(target.name, metadata?.title ?? title);
		const relevanceScore = clamp01(
			searchOrderScore * 0.62 +
				titleScore * 0.18 +
				scoreMethod(metadata?.method ?? null) +
				scoreResolution(metadata?.resolutionAngstrom ?? null),
		);
		const rationaleParts = [
			`RCSB full-text rank ${index + 1}`,
			metadata?.method ? `method: ${metadata.method}` : "method unavailable",
			metadata?.resolutionAngstrom
				? `resolution: ${metadata.resolutionAngstrom.toFixed(2)} A`
				: "resolution unavailable",
			pubmedRefs.length > 0
				? `${pubmedRefs.length} PubMed reference${pubmedRefs.length === 1 ? "" : "s"} considered`
				: "literature support unavailable",
			biorxivRefs.length > 0
				? `${biorxivRefs.length} bioRxiv preprint${biorxivRefs.length === 1 ? "" : "s"} considered`
				: "bioRxiv preprint support unavailable",
		];

		return {
			assemblyId: "1",
			chainIdsJson: [],
			citationJson: { biorxiv: biorxivRefs, pubmed: pubmedRefs },
			confidence: clamp01(relevanceScore - 0.08),
			ligandIdsJson: [],
			method: metadata?.method ?? null,
			organism: target.organism,
			proteinaReady: false,
			rank: 0,
			rcsbId: normalizedId,
			relevanceScore,
			resolutionAngstrom: metadata?.resolutionAngstrom ?? null,
			selectionRationale: rationaleParts.join("; "),
			title,
		};
	});

	return ranked
		.sort((left, right) => right.relevanceScore - left.relevanceScore)
		.map((candidate, index) => ({
			...candidate,
			rank: index + 1,
		}));
};

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
	topK: requestedTopK,
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

		await appendRunEvent({
			db,
			detail: target.name,
			payload: { target },
			runId,
			title: "Searching RCSB structures",
			type: "searching_structures",
		});

		const topK = requestedTopK ?? resolveRequestedTopK(run.sdkStateJson);
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

		const metadataResults = await Promise.allSettled(
			rcsbIds.map((rcsbId) =>
				getRcsbEntryMetadata({
					entryId: rcsbId,
					fetchImpl,
				}),
			),
		);
		const metadataById = new Map<string, RcsbEntryMetadata>();
		const metadataFailures: string[] = [];

		for (const [index, result] of metadataResults.entries()) {
			const rcsbId = rcsbIds[index];
			if (!rcsbId) {
				continue;
			}

			if (result.status === "fulfilled") {
				metadataById.set(result.value.rcsbId, result.value);
			} else {
				metadataFailures.push(
					`${rcsbId}: ${
						result.reason instanceof Error
							? result.reason.message
							: String(result.reason)
					}`,
				);
			}
		}

		if (metadataFailures.length > 0) {
			await appendRunEvent({
				db,
				detail: metadataFailures.join("; "),
				payload: { failures: metadataFailures },
				runId,
				title: "RCSB metadata partially unavailable",
				type: "source_failed",
			});
		}

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

		let biorxivRefs: BioRxivRef[] = [];
		await appendRunEvent({
			db,
			detail: `${target.name} structure`,
			runId,
			title: "Searching bioRxiv preprints",
			type: "searching_biorxiv",
		});
		try {
			biorxivRefs = await searchBioRxivPreprints({
				fetchImpl,
				limit: Math.min(topK, 10),
				query: `${target.name} structure`,
			});
			await appendRunEvent({
				db,
				detail:
					biorxivRefs.length > 0
						? `Found ${biorxivRefs.length} bioRxiv preprint reference${biorxivRefs.length === 1 ? "" : "s"}.`
						: "No matching bioRxiv preprints were returned.",
				payload: { biorxiv: biorxivRefs },
				runId,
				title: "bioRxiv search complete",
				type: "searching_literature",
			});
		} catch (error) {
			await appendRunEvent({
				db,
				detail: error instanceof Error ? error.message : String(error),
				runId,
				title: "bioRxiv search failed",
				type: "source_failed",
			});
		}

		await appendRunEvent({
			db,
			runId,
			title: "Ranking candidates",
			type: "ranking_candidates",
		});

		const rankedCandidates = rankRcsbCandidates({
			biorxivRefs,
			metadataById,
			pubmedRefs,
			rcsbIds,
			target,
		});

		const insertedCandidates = await db
			.insert(proteinCandidates)
			.values(
				rankedCandidates.map((candidate) => ({
					chainIdsJson: candidate.chainIdsJson,
					metadataJson: {
						assemblyId: candidate.assemblyId,
						organism: candidate.organism,
						proteinaReady: candidate.proteinaReady,
						rcsbId: candidate.rcsbId,
						target,
					},
					rank: candidate.rank,
					runId,
					scoreJson: {
						citation: candidate.citationJson,
						confidence: candidate.confidence,
						ligands: candidate.ligandIdsJson,
						method: candidate.method,
						relevance: candidate.relevanceScore,
						resolution: candidate.resolutionAngstrom,
					},
					source: "rcsb_pdb" as const,
					structureId: candidate.rcsbId,
					title: candidate.title,
					whySelected: candidate.selectionRationale,
					workspaceId: run.workspaceId,
				})),
			)
			.returning();

		const topCandidate =
			insertedCandidates.find((candidate) => candidate.rank === 1) ??
			insertedCandidates[0];
		const topRankedCandidate =
			rankedCandidates.find(
				(candidate) => candidate.rank === topCandidate?.rank,
			) ?? rankedCandidates[0];
		if (!topCandidate) {
			throw new Error("Failed to insert protein candidates.");
		}
		if (!topRankedCandidate) {
			throw new Error("Failed to select top ranked candidate.");
		}

		await appendRunEvent({
			db,
			detail: topRankedCandidate.rcsbId,
			runId,
			title: "Downloading source CIF",
			type: "downloading_cif",
		});

		const cifText = await downloadRcsbCif({
			entryId: topRankedCandidate.rcsbId,
			fetchImpl,
		});
		const cifBytes = new TextEncoder().encode(cifText);
		const fileName = `${topRankedCandidate.rcsbId.toLowerCase()}-source.cif`;
		const objectKey = buildArtifactKey({
			candidateId: topCandidate.id,
			fileName,
			projectId: run.workspaceId,
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

		const [artifact] = await db
			.insert(artifacts)
			.values({
				contentType: cifContentType,
				kind: "mmcif",
				metadataJson: {
					bucket: env.R2_BUCKET,
					candidateId: topCandidate.id,
					format: "mmcif",
					legacyType: "source_cif",
					rcsbId: topRankedCandidate.rcsbId,
					sourceUrl: getRcsbCifUrl(topRankedCandidate.rcsbId),
					viewerHint: "molstar",
				},
				name: fileName,
				runId,
				sizeBytes: cifBytes.byteLength,
				storageKey: objectKey,
				storageProvider: "r2",
				workspaceId: run.workspaceId,
			})
			.returning({ id: artifacts.id });

		if (!artifact) {
			throw new Error("Failed to persist CIF artifact metadata.");
		}

		const [readyCandidate] = await db
			.update(proteinCandidates)
			.set({
				artifactId: artifact.id,
				metadataJson: {
					...topCandidate.metadataJson,
					artifactId: artifact.id,
					proteinaReady: true,
				},
			})
			.where(eq(proteinCandidates.id, topCandidate.id))
			.returning({ id: proteinCandidates.id });

		if (!readyCandidate) {
			throw new Error("Failed to mark candidate ready for Proteina.");
		}

		await appendRunEvent({
			db,
			detail: `${topRankedCandidate.rcsbId} source CIF is ready.`,
			payload: {
				artifactId: artifact.id,
				candidateId: topCandidate.id,
				objectKey,
				rcsbId: topRankedCandidate.rcsbId,
			},
			runId,
			title: "Ready for Proteina",
			type: "ready_for_proteina",
		});

		await db
			.update(agentRuns)
			.set({
				finishedAt: new Date(),
				status: "completed",
			})
			.where(eq(agentRuns.id, runId));

		return {
			candidateId: topCandidate.id,
			objectKey,
			rcsbId: topRankedCandidate.rcsbId,
			runId,
		};
	} catch (error) {
		return markRunFailed({ db, error, runId });
	}
};
