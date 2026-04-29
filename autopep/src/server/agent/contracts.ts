import { z } from "zod";

export const agentEventTypeSchema = z.enum([
	"codex_agent_started",
	"codex_agent_finished",
	"codex_agent_fallback",
	"normalizing_target",
	"searching_structures",
	"searching_literature",
	"searching_biorxiv",
	"ranking_candidates",
	"downloading_cif",
	"preparing_cif",
	"uploading_artifact",
	"ready_for_proteina",
	"source_failed",
	"run_start_skipped",
	"run_failed",
]);

export const artifactTypeSchema = z.enum([
	"source_cif",
	"prepared_cif",
	"fasta",
	"raw_search_json",
	"report",
	"other",
]);

export const targetEntitySchema = z.object({
	name: z.string(),
	aliases: z.array(z.string()).default([]),
	organism: z.string().nullable().default(null),
	uniprotId: z.string().nullable().default(null),
	role: z.string().nullable().default(null),
	rationale: z.string().nullable().default(null),
});

export const rankedCandidateSchema = z.object({
	rcsbId: z.string(),
	assemblyId: z.string().nullable().default(null),
	title: z.string(),
	method: z.string().nullable().default(null),
	resolutionAngstrom: z.number().nullable().default(null),
	organism: z.string().nullable().default(null),
	chainIds: z.array(z.string()).default([]),
	ligandIds: z.array(z.string()).default([]),
	citation: z.record(z.unknown()).default({}),
	relevanceScore: z.number().min(0).max(1),
	confidence: z.number().min(0).max(1).default(0),
	selectionRationale: z.string(),
	proteinaReady: z.boolean().default(false),
});

export type AgentEventType = z.infer<typeof agentEventTypeSchema>;
export type ArtifactType = z.infer<typeof artifactTypeSchema>;
export type TargetEntity = z.infer<typeof targetEntitySchema>;
export type RankedCandidate = z.infer<typeof rankedCandidateSchema>;
