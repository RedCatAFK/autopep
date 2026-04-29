-- Intentionally destructive Autopep-only migration for the pre-user MVP refactor.
-- Autopep domain data is dropped and recreated by this migration.
-- Better Auth tables ("user", "session", "account", "verification") are intentionally preserved.
DROP TABLE IF EXISTS "autopep_run_recipe" CASCADE;--> statement-breakpoint
DROP TABLE IF EXISTS "autopep_recipe_version" CASCADE;--> statement-breakpoint
DROP TABLE IF EXISTS "autopep_recipe" CASCADE;--> statement-breakpoint
DROP TABLE IF EXISTS "autopep_context_reference" CASCADE;--> statement-breakpoint
DROP TABLE IF EXISTS "autopep_candidate_score" CASCADE;--> statement-breakpoint
DROP TABLE IF EXISTS "autopep_model_inference" CASCADE;--> statement-breakpoint
DROP TABLE IF EXISTS "autopep_message" CASCADE;--> statement-breakpoint
DROP TABLE IF EXISTS "autopep_agent_event" CASCADE;--> statement-breakpoint
DROP TABLE IF EXISTS "autopep_artifact" CASCADE;--> statement-breakpoint
DROP TABLE IF EXISTS "autopep_protein_candidate" CASCADE;--> statement-breakpoint
DROP TABLE IF EXISTS "autopep_agent_run" CASCADE;--> statement-breakpoint
DROP TABLE IF EXISTS "autopep_thread" CASCADE;--> statement-breakpoint
DROP TABLE IF EXISTS "autopep_workspace" CASCADE;--> statement-breakpoint
DROP TABLE IF EXISTS "autopep_target_entity" CASCADE;--> statement-breakpoint
DROP TABLE IF EXISTS "autopep_project" CASCADE;--> statement-breakpoint
DROP TYPE IF EXISTS "public"."artifact_type";--> statement-breakpoint
DROP TYPE IF EXISTS "public"."artifact_kind";--> statement-breakpoint
DROP TYPE IF EXISTS "public"."agent_task_kind";--> statement-breakpoint
DROP TYPE IF EXISTS "public"."agent_run_status";--> statement-breakpoint
CREATE TYPE "public"."agent_run_status" AS ENUM('queued', 'running', 'paused', 'completed', 'failed', 'cancelled');--> statement-breakpoint
CREATE TYPE "public"."agent_task_kind" AS ENUM('chat', 'research', 'structure_search', 'prepare_structure', 'mutate_structure', 'branch_design');--> statement-breakpoint
CREATE TYPE "public"."artifact_kind" AS ENUM('cif', 'mmcif', 'pdb', 'fasta', 'sequence', 'pdb_metadata', 'literature_snapshot', 'biopython_script', 'proteina_result', 'chai_result', 'mutated_structure', 'score_report', 'log', 'image', 'other');--> statement-breakpoint
CREATE TABLE "autopep_workspace" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"owner_id" text NOT NULL,
	"name" text NOT NULL,
	"description" text,
	"active_thread_id" uuid,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"archived_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "autopep_thread" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"workspace_id" uuid NOT NULL,
	"title" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "autopep_agent_run" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"workspace_id" uuid NOT NULL,
	"thread_id" uuid NOT NULL,
	"parent_run_id" uuid,
	"root_run_id" uuid,
	"created_by_id" text NOT NULL,
	"status" "agent_run_status" DEFAULT 'queued' NOT NULL,
	"task_kind" "agent_task_kind" DEFAULT 'chat' NOT NULL,
	"prompt" text NOT NULL,
	"model" text DEFAULT 'gpt-5.4' NOT NULL,
	"agent_name" text DEFAULT 'Autopep' NOT NULL,
	"modal_call_id" text,
	"sandbox_session_state_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"sdk_state_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"last_response_id" text,
	"started_at" timestamp with time zone,
	"finished_at" timestamp with time zone,
	"error_summary" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "autopep_message" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"thread_id" uuid NOT NULL,
	"run_id" uuid,
	"role" text NOT NULL,
	"content" text NOT NULL,
	"context_refs_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"recipe_refs_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"attachment_refs_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "autopep_agent_event" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"run_id" uuid NOT NULL,
	"sequence" integer NOT NULL,
	"type" text NOT NULL,
	"title" text NOT NULL,
	"summary" text,
	"display_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"raw_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "autopep_agent_event_run_sequence_unique" UNIQUE("run_id","sequence")
);
--> statement-breakpoint
CREATE TABLE "autopep_artifact" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"workspace_id" uuid NOT NULL,
	"run_id" uuid,
	"source_artifact_id" uuid,
	"kind" "artifact_kind" NOT NULL,
	"name" text NOT NULL,
	"storage_provider" text DEFAULT 'r2' NOT NULL,
	"storage_key" text NOT NULL,
	"content_type" text NOT NULL,
	"size_bytes" integer NOT NULL,
	"sha256" text,
	"metadata_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "autopep_protein_candidate" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"workspace_id" uuid NOT NULL,
	"run_id" uuid NOT NULL,
	"parent_candidate_id" uuid,
	"rank" integer NOT NULL,
	"source" text NOT NULL,
	"structure_id" text,
	"chain_ids_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"sequence" text,
	"title" text NOT NULL,
	"score_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"why_selected" text,
	"artifact_id" uuid,
	"fold_artifact_id" uuid,
	"parent_inference_id" uuid,
	"metadata_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "autopep_model_inference" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"workspace_id" uuid NOT NULL,
	"run_id" uuid NOT NULL,
	"parent_inference_id" uuid,
	"provider" text DEFAULT 'modal' NOT NULL,
	"model_name" text NOT NULL,
	"status" "agent_run_status" DEFAULT 'queued' NOT NULL,
	"endpoint_url_snapshot" text,
	"request_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"response_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"external_request_id" text,
	"started_at" timestamp with time zone,
	"finished_at" timestamp with time zone,
	"error_summary" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "autopep_candidate_score" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"workspace_id" uuid NOT NULL,
	"run_id" uuid NOT NULL,
	"candidate_id" uuid NOT NULL,
	"model_inference_id" uuid,
	"scorer" text NOT NULL,
	"status" text NOT NULL,
	"label" text,
	"value" real,
	"unit" text,
	"values_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"warnings_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"errors_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "autopep_context_reference" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"workspace_id" uuid NOT NULL,
	"artifact_id" uuid,
	"candidate_id" uuid,
	"kind" text NOT NULL,
	"label" text NOT NULL,
	"selector_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_by_id" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "autopep_recipe" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"owner_id" text NOT NULL,
	"workspace_id" uuid,
	"name" text NOT NULL,
	"description" text,
	"body_markdown" text NOT NULL,
	"is_global" boolean DEFAULT false NOT NULL,
	"enabled_by_default" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"archived_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "autopep_recipe_version" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"recipe_id" uuid NOT NULL,
	"version" integer NOT NULL,
	"body_markdown" text NOT NULL,
	"created_by_id" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "autopep_recipe_version_unique" UNIQUE("recipe_id","version")
);
--> statement-breakpoint
CREATE TABLE "autopep_run_recipe" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"run_id" uuid NOT NULL,
	"recipe_id" uuid NOT NULL,
	"recipe_version_id" uuid NOT NULL,
	"name_snapshot" text NOT NULL,
	"body_snapshot" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "autopep_workspace" ADD CONSTRAINT "autopep_workspace_owner_id_user_id_fk" FOREIGN KEY ("owner_id") REFERENCES "public"."user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_workspace" ADD CONSTRAINT "autopep_workspace_active_thread_id_autopep_thread_id_fk" FOREIGN KEY ("active_thread_id") REFERENCES "public"."autopep_thread"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_thread" ADD CONSTRAINT "autopep_thread_workspace_id_autopep_workspace_id_fk" FOREIGN KEY ("workspace_id") REFERENCES "public"."autopep_workspace"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_agent_run" ADD CONSTRAINT "autopep_agent_run_workspace_id_autopep_workspace_id_fk" FOREIGN KEY ("workspace_id") REFERENCES "public"."autopep_workspace"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_agent_run" ADD CONSTRAINT "autopep_agent_run_thread_id_autopep_thread_id_fk" FOREIGN KEY ("thread_id") REFERENCES "public"."autopep_thread"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_agent_run" ADD CONSTRAINT "autopep_agent_run_parent_run_id_autopep_agent_run_id_fk" FOREIGN KEY ("parent_run_id") REFERENCES "public"."autopep_agent_run"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_agent_run" ADD CONSTRAINT "autopep_agent_run_root_run_id_autopep_agent_run_id_fk" FOREIGN KEY ("root_run_id") REFERENCES "public"."autopep_agent_run"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_agent_run" ADD CONSTRAINT "autopep_agent_run_created_by_id_user_id_fk" FOREIGN KEY ("created_by_id") REFERENCES "public"."user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_message" ADD CONSTRAINT "autopep_message_thread_id_autopep_thread_id_fk" FOREIGN KEY ("thread_id") REFERENCES "public"."autopep_thread"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_message" ADD CONSTRAINT "autopep_message_run_id_autopep_agent_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."autopep_agent_run"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_agent_event" ADD CONSTRAINT "autopep_agent_event_run_id_autopep_agent_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."autopep_agent_run"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_artifact" ADD CONSTRAINT "autopep_artifact_workspace_id_autopep_workspace_id_fk" FOREIGN KEY ("workspace_id") REFERENCES "public"."autopep_workspace"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_artifact" ADD CONSTRAINT "autopep_artifact_run_id_autopep_agent_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."autopep_agent_run"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_artifact" ADD CONSTRAINT "autopep_artifact_source_artifact_id_autopep_artifact_id_fk" FOREIGN KEY ("source_artifact_id") REFERENCES "public"."autopep_artifact"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_protein_candidate" ADD CONSTRAINT "autopep_protein_candidate_workspace_id_autopep_workspace_id_fk" FOREIGN KEY ("workspace_id") REFERENCES "public"."autopep_workspace"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_protein_candidate" ADD CONSTRAINT "autopep_protein_candidate_run_id_autopep_agent_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."autopep_agent_run"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_protein_candidate" ADD CONSTRAINT "autopep_protein_candidate_parent_candidate_id_autopep_protein_candidate_id_fk" FOREIGN KEY ("parent_candidate_id") REFERENCES "public"."autopep_protein_candidate"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_protein_candidate" ADD CONSTRAINT "autopep_protein_candidate_artifact_id_autopep_artifact_id_fk" FOREIGN KEY ("artifact_id") REFERENCES "public"."autopep_artifact"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_protein_candidate" ADD CONSTRAINT "autopep_protein_candidate_fold_artifact_id_autopep_artifact_id_fk" FOREIGN KEY ("fold_artifact_id") REFERENCES "public"."autopep_artifact"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_protein_candidate" ADD CONSTRAINT "autopep_protein_candidate_parent_inference_id_autopep_model_inference_id_fk" FOREIGN KEY ("parent_inference_id") REFERENCES "public"."autopep_model_inference"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_model_inference" ADD CONSTRAINT "autopep_model_inference_workspace_id_autopep_workspace_id_fk" FOREIGN KEY ("workspace_id") REFERENCES "public"."autopep_workspace"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_model_inference" ADD CONSTRAINT "autopep_model_inference_run_id_autopep_agent_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."autopep_agent_run"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_model_inference" ADD CONSTRAINT "autopep_model_inference_parent_inference_id_autopep_model_inference_id_fk" FOREIGN KEY ("parent_inference_id") REFERENCES "public"."autopep_model_inference"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_candidate_score" ADD CONSTRAINT "autopep_candidate_score_workspace_id_autopep_workspace_id_fk" FOREIGN KEY ("workspace_id") REFERENCES "public"."autopep_workspace"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_candidate_score" ADD CONSTRAINT "autopep_candidate_score_run_id_autopep_agent_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."autopep_agent_run"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_candidate_score" ADD CONSTRAINT "autopep_candidate_score_candidate_id_autopep_protein_candidate_id_fk" FOREIGN KEY ("candidate_id") REFERENCES "public"."autopep_protein_candidate"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_candidate_score" ADD CONSTRAINT "autopep_candidate_score_model_inference_id_autopep_model_inference_id_fk" FOREIGN KEY ("model_inference_id") REFERENCES "public"."autopep_model_inference"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_context_reference" ADD CONSTRAINT "autopep_context_reference_workspace_id_autopep_workspace_id_fk" FOREIGN KEY ("workspace_id") REFERENCES "public"."autopep_workspace"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_context_reference" ADD CONSTRAINT "autopep_context_reference_artifact_id_autopep_artifact_id_fk" FOREIGN KEY ("artifact_id") REFERENCES "public"."autopep_artifact"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_context_reference" ADD CONSTRAINT "autopep_context_reference_candidate_id_autopep_protein_candidate_id_fk" FOREIGN KEY ("candidate_id") REFERENCES "public"."autopep_protein_candidate"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_context_reference" ADD CONSTRAINT "autopep_context_reference_created_by_id_user_id_fk" FOREIGN KEY ("created_by_id") REFERENCES "public"."user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_recipe" ADD CONSTRAINT "autopep_recipe_owner_id_user_id_fk" FOREIGN KEY ("owner_id") REFERENCES "public"."user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_recipe" ADD CONSTRAINT "autopep_recipe_workspace_id_autopep_workspace_id_fk" FOREIGN KEY ("workspace_id") REFERENCES "public"."autopep_workspace"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_recipe_version" ADD CONSTRAINT "autopep_recipe_version_recipe_id_autopep_recipe_id_fk" FOREIGN KEY ("recipe_id") REFERENCES "public"."autopep_recipe"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_recipe_version" ADD CONSTRAINT "autopep_recipe_version_created_by_id_user_id_fk" FOREIGN KEY ("created_by_id") REFERENCES "public"."user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_run_recipe" ADD CONSTRAINT "autopep_run_recipe_run_id_autopep_agent_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."autopep_agent_run"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_run_recipe" ADD CONSTRAINT "autopep_run_recipe_recipe_id_autopep_recipe_id_fk" FOREIGN KEY ("recipe_id") REFERENCES "public"."autopep_recipe"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_run_recipe" ADD CONSTRAINT "autopep_run_recipe_recipe_version_id_autopep_recipe_version_id_fk" FOREIGN KEY ("recipe_version_id") REFERENCES "public"."autopep_recipe_version"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "autopep_workspace_owner_idx" ON "autopep_workspace" USING btree ("owner_id");--> statement-breakpoint
CREATE INDEX "autopep_thread_workspace_idx" ON "autopep_thread" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "autopep_agent_run_workspace_idx" ON "autopep_agent_run" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "autopep_agent_run_thread_idx" ON "autopep_agent_run" USING btree ("thread_id");--> statement-breakpoint
CREATE INDEX "autopep_agent_run_status_idx" ON "autopep_agent_run" USING btree ("status");--> statement-breakpoint
CREATE INDEX "autopep_message_thread_idx" ON "autopep_message" USING btree ("thread_id");--> statement-breakpoint
CREATE INDEX "autopep_agent_event_run_idx" ON "autopep_agent_event" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "autopep_artifact_workspace_idx" ON "autopep_artifact" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "autopep_artifact_run_idx" ON "autopep_artifact" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "autopep_artifact_source_idx" ON "autopep_artifact" USING btree ("source_artifact_id");--> statement-breakpoint
CREATE INDEX "autopep_candidate_workspace_idx" ON "autopep_protein_candidate" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "autopep_candidate_run_idx" ON "autopep_protein_candidate" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "autopep_candidate_parent_idx" ON "autopep_protein_candidate" USING btree ("parent_candidate_id");--> statement-breakpoint
CREATE INDEX "autopep_model_inference_workspace_idx" ON "autopep_model_inference" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "autopep_model_inference_run_idx" ON "autopep_model_inference" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "autopep_candidate_score_candidate_idx" ON "autopep_candidate_score" USING btree ("candidate_id");--> statement-breakpoint
CREATE INDEX "autopep_candidate_score_run_idx" ON "autopep_candidate_score" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "autopep_context_reference_workspace_idx" ON "autopep_context_reference" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "autopep_recipe_workspace_idx" ON "autopep_recipe" USING btree ("workspace_id");--> statement-breakpoint
CREATE INDEX "autopep_run_recipe_run_idx" ON "autopep_run_recipe" USING btree ("run_id");
