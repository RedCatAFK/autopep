import * as z from "zod";

export const runStatusSchema = z.enum([
	"queued",
	"running",
	"paused",
	"completed",
	"failed",
	"cancelled",
]);

export const publicTaskKindSchema = z.enum([
	"chat",
	"research",
	"structure_search",
	"prepare_structure",
	"mutate_structure",
	"branch_design",
]);

export const taskKindSchema = z.enum([
	"chat",
	"research",
	"structure_search",
	"prepare_structure",
	"mutate_structure",
	"branch_design",
	"smoke_chat",
	"smoke_tool",
	"smoke_sandbox",
]);

export const agentEventTypeSchema = z.enum([
	"run_started",
	"assistant_message_started",
	"assistant_token_delta",
	"assistant_message_completed",
	"reasoning_step",
	"tool_call_started",
	"tool_call_delta",
	"tool_call_completed",
	"tool_call_failed",
	"sandbox_command_started",
	"sandbox_stdout_delta",
	"sandbox_stderr_delta",
	"sandbox_command_completed",
	"artifact_created",
	"candidate_ranked",
	"approval_requested",
	"agent_changed",
	"run_paused",
	"run_failed",
	"run_cancelled",
	"run_completed",
]);

export const artifactKindSchema = z.enum([
	"cif",
	"mmcif",
	"pdb",
	"fasta",
	"sequence",
	"pdb_metadata",
	"literature_snapshot",
	"biopython_script",
	"proteina_result",
	"chai_result",
	"mutated_structure",
	"score_report",
	"log",
	"image",
	"attachment",
	"other",
]);

export const endpointModelNameSchema = z.enum([
	"proteina_complexa",
	"chai_1",
	"protein_interaction_scoring",
	"future_scorer",
]);

export const scoreLabelSchema = z.enum([
	"likely_binder",
	"possible_binder",
	"unlikely_binder",
	"insufficient_data",
]);

export const scoreStatusSchema = z.enum([
	"ok",
	"partial",
	"failed",
	"unavailable",
]);

export const scoreScorerSchema = z.enum([
	"dscript",
	"prodigy",
	"protein_interaction_aggregate",
	"future_scorer",
]);

export const contextReferenceSchema = z.object({
	artifactId: z.string().uuid().nullable(),
	candidateId: z.string().uuid().nullable(),
	kind: z.enum([
		"protein_selection",
		"artifact",
		"candidate",
		"literature",
		"note",
	]),
	label: z.string().min(1),
	selector: z.record(z.unknown()).default({}),
});

export const candidateScoreSchema = z.object({
	candidateId: z.string().uuid(),
	label: scoreLabelSchema.nullable(),
	scorer: scoreScorerSchema,
	status: scoreStatusSchema,
	unit: z.string().nullable(),
	value: z.number().nullable(),
	values: z.record(z.unknown()).default({}),
});

export type AgentEventType = z.infer<typeof agentEventTypeSchema>;
export type ArtifactKind = z.infer<typeof artifactKindSchema>;
export type CandidateScore = z.infer<typeof candidateScoreSchema>;
export type ContextReference = z.infer<typeof contextReferenceSchema>;
export type EndpointModelName = z.infer<typeof endpointModelNameSchema>;
export type PublicTaskKind = z.infer<typeof publicTaskKindSchema>;
export type RunStatus = z.infer<typeof runStatusSchema>;
export type TaskKind = z.infer<typeof taskKindSchema>;
