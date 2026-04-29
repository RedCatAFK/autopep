import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { getTableName } from "drizzle-orm";
import { describe, expect, it } from "vitest";

import {
	agentEvents,
	agentRuns,
	artifacts,
	candidateScores,
	contextReferences,
	messages,
	modelInferences,
	recipes,
	recipeVersions,
	runRecipes,
	threads,
	workspaces,
} from "./schema";

describe("Autopep schema", () => {
	it("uses the new workspace-centered table names", () => {
		expect(getTableName(workspaces)).toBe("autopep_workspace");
		expect(getTableName(threads)).toBe("autopep_thread");
		expect(getTableName(messages)).toBe("autopep_message");
		expect(getTableName(agentRuns)).toBe("autopep_agent_run");
		expect(getTableName(agentEvents)).toBe("autopep_agent_event");
		expect(getTableName(artifacts)).toBe("autopep_artifact");
		expect(getTableName(modelInferences)).toBe("autopep_model_inference");
		expect(getTableName(candidateScores)).toBe("autopep_candidate_score");
		expect(getTableName(contextReferences)).toBe("autopep_context_reference");
		expect(getTableName(recipes)).toBe("autopep_recipe");
		expect(getTableName(recipeVersions)).toBe("autopep_recipe_version");
		expect(getTableName(runRecipes)).toBe("autopep_run_recipe");
	});

	it("generates lineage foreign keys and preserves Better Auth tables", () => {
		const migrationSql = readFileSync(
			resolve(process.cwd(), "drizzle/0003_smooth_sasquatch.sql"),
			"utf8",
		);

		expect(migrationSql).toContain(
			"Intentionally destructive Autopep-only migration",
		);

		for (const constraintName of [
			"autopep_workspace_active_thread_id_autopep_thread_id_fk",
			"autopep_message_run_id_autopep_agent_run_id_fk",
			"autopep_agent_run_parent_run_id_autopep_agent_run_id_fk",
			"autopep_agent_run_root_run_id_autopep_agent_run_id_fk",
			"autopep_artifact_source_artifact_id_autopep_artifact_id_fk",
			"autopep_protein_candidate_parent_candidate_id_autopep_protein_candidate_id_fk",
			"autopep_protein_candidate_parent_inference_id_autopep_model_inference_id_fk",
			"autopep_model_inference_parent_inference_id_autopep_model_inference_id_fk",
		]) {
			expect(migrationSql).toContain(`CONSTRAINT "${constraintName}"`);
		}

		expect(migrationSql).not.toMatch(
			/DROP TABLE IF EXISTS "(user|session|account|verification)"/,
		);
	});
});
