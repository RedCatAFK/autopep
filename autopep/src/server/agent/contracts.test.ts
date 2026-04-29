import { describe, expect, it } from "vitest";

import {
	agentEventTypeSchema,
	artifactKindSchema,
	candidateScoreSchema,
	endpointModelNameSchema,
	publicTaskKindSchema,
	runStatusSchema,
	scoreLabelSchema,
	taskKindSchema,
} from "./contracts";

describe("Autopep runtime contracts", () => {
	it("accepts the run statuses used by the MVP event ledger", () => {
		expect(runStatusSchema.options).toEqual([
			"queued",
			"running",
			"paused",
			"completed",
			"failed",
			"cancelled",
		]);
	});

	it("accepts task kinds for production and smoke agent runs", () => {
		for (const taskKind of [
			"chat",
			"branch_design",
			"smoke_chat",
			"smoke_tool",
			"smoke_sandbox",
		]) {
			expect(taskKindSchema.parse(taskKind)).toBe(taskKind);
		}
	});

	it("excludes smoke task kinds from the public-facing schema", () => {
		for (const taskKind of [
			"chat",
			"research",
			"structure_search",
			"prepare_structure",
			"mutate_structure",
			"branch_design",
		]) {
			expect(publicTaskKindSchema.parse(taskKind)).toBe(taskKind);
		}
		for (const taskKind of ["smoke_chat", "smoke_tool", "smoke_sandbox"]) {
			expect(() => publicTaskKindSchema.parse(taskKind)).toThrow();
		}
	});

	it("accepts event types for chat, tools, sandbox output, candidates, and scores", () => {
		for (const type of [
			"assistant_token_delta",
			"tool_call_started",
			"sandbox_stdout_delta",
			"artifact_created",
			"candidate_ranked",
			"run_completed",
		]) {
			expect(agentEventTypeSchema.parse(type)).toBe(type);
		}
	});

	it("accepts model inference names for all deployed Modal endpoints", () => {
		expect(endpointModelNameSchema.parse("proteina_complexa")).toBe(
			"proteina_complexa",
		);
		expect(endpointModelNameSchema.parse("chai_1")).toBe("chai_1");
		expect(endpointModelNameSchema.parse("protein_interaction_scoring")).toBe(
			"protein_interaction_scoring",
		);
	});

	it("validates candidate score rows for D-SCRIPT, PRODIGY, and aggregate labels", () => {
		expect(
			candidateScoreSchema.parse({
				candidateId: "11111111-1111-4111-8111-111111111111",
				label: "likely_binder",
				scorer: "dscript",
				status: "ok",
				unit: "probability",
				value: 0.84,
				values: { threshold: 0.5 },
			}),
		).toMatchObject({
			scorer: "dscript",
			unit: "probability",
			value: 0.84,
		});
		expect(
			candidateScoreSchema.parse({
				candidateId: "22222222-2222-4222-8222-222222222222",
				label: "possible_binder",
				scorer: "prodigy",
				status: "ok",
				unit: "kcal/mol",
				value: -9.6,
				values: { kdMolar: 0.00000009 },
			}),
		).toMatchObject({
			scorer: "prodigy",
			unit: "kcal/mol",
			value: -9.6,
		});
		expect(
			candidateScoreSchema.parse({
				candidateId: "11111111-1111-4111-8111-111111111111",
				label: "possible_binder",
				scorer: "protein_interaction_aggregate",
				status: "ok",
				unit: null,
				value: null,
				values: { notes: ["D-SCRIPT-only result"] },
			}),
		).toMatchObject({
			label: "possible_binder",
			scorer: "protein_interaction_aggregate",
		});
		expect(scoreLabelSchema.parse("insufficient_data")).toBe(
			"insufficient_data",
		);
	});

	it("keeps structure artifacts broad enough for source, generated, folded, and scored outputs", () => {
		for (const kind of [
			"mmcif",
			"pdb",
			"proteina_result",
			"chai_result",
			"score_report",
		]) {
			expect(artifactKindSchema.parse(kind)).toBe(kind);
		}
	});
});
