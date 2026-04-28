CREATE TYPE "public"."agent_run_status" AS ENUM('queued', 'running', 'succeeded', 'failed', 'canceled');--> statement-breakpoint
CREATE TYPE "public"."artifact_type" AS ENUM('source_cif', 'prepared_cif', 'fasta', 'raw_search_json', 'report', 'other');--> statement-breakpoint
CREATE TABLE "autopep_agent_event" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"run_id" uuid NOT NULL,
	"sequence" integer NOT NULL,
	"type" text NOT NULL,
	"title" text NOT NULL,
	"detail" text,
	"payload_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "autopep_agent_event_run_id_sequence_unique" UNIQUE("run_id","sequence")
);
--> statement-breakpoint
CREATE TABLE "autopep_agent_run" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"project_id" uuid NOT NULL,
	"created_by_id" text NOT NULL,
	"prompt" text NOT NULL,
	"status" "agent_run_status" DEFAULT 'queued' NOT NULL,
	"top_k" integer DEFAULT 5 NOT NULL,
	"claimed_by" text,
	"claimed_at" timestamp with time zone,
	"started_at" timestamp with time zone,
	"finished_at" timestamp with time zone,
	"error_summary" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "autopep_agent_run_id_project_id_unique" UNIQUE("id","project_id")
);
--> statement-breakpoint
CREATE TABLE "autopep_artifact" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"project_id" uuid NOT NULL,
	"run_id" uuid NOT NULL,
	"candidate_id" uuid,
	"type" "artifact_type" NOT NULL,
	"file_name" text NOT NULL,
	"mime_type" text NOT NULL,
	"size_bytes" integer NOT NULL,
	"checksum" text,
	"r2_bucket" text NOT NULL,
	"r2_key" text NOT NULL,
	"viewer" text DEFAULT 'molstar' NOT NULL,
	"viewer_hints_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "autopep_project" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"owner_id" text NOT NULL,
	"name" text NOT NULL,
	"goal" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "autopep_protein_candidate" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"run_id" uuid NOT NULL,
	"target_entity_id" uuid,
	"rank" integer NOT NULL,
	"score" real NOT NULL,
	"rcsb_entry_id" text NOT NULL,
	"title" text NOT NULL,
	"organism" text,
	"experimental_method" text,
	"resolution" real,
	"chains_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"literature_refs_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"why_selected" text NOT NULL,
	"proteina_ready" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "autopep_protein_candidate_run_id_rank_unique" UNIQUE("run_id","rank"),
	CONSTRAINT "autopep_protein_candidate_id_run_id_unique" UNIQUE("id","run_id")
);
--> statement-breakpoint
CREATE TABLE "autopep_target_entity" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"run_id" uuid NOT NULL,
	"label" text NOT NULL,
	"aliases_json" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"organism" text,
	"source_ids_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"confidence" real DEFAULT 0 NOT NULL,
	"notes" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "autopep_target_entity_id_run_id_unique" UNIQUE("id","run_id")
);
--> statement-breakpoint
ALTER TABLE "autopep_agent_event" ADD CONSTRAINT "autopep_agent_event_run_id_autopep_agent_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."autopep_agent_run"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_agent_run" ADD CONSTRAINT "autopep_agent_run_project_id_autopep_project_id_fk" FOREIGN KEY ("project_id") REFERENCES "public"."autopep_project"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_agent_run" ADD CONSTRAINT "autopep_agent_run_created_by_id_user_id_fk" FOREIGN KEY ("created_by_id") REFERENCES "public"."user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_artifact" ADD CONSTRAINT "autopep_artifact_project_id_autopep_project_id_fk" FOREIGN KEY ("project_id") REFERENCES "public"."autopep_project"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_artifact" ADD CONSTRAINT "autopep_artifact_run_id_autopep_agent_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."autopep_agent_run"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_artifact" ADD CONSTRAINT "autopep_artifact_candidate_id_autopep_protein_candidate_id_fk" FOREIGN KEY ("candidate_id") REFERENCES "public"."autopep_protein_candidate"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_artifact" ADD CONSTRAINT "autopep_artifact_run_project_fk" FOREIGN KEY ("run_id","project_id") REFERENCES "public"."autopep_agent_run"("id","project_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_artifact" ADD CONSTRAINT "autopep_artifact_candidate_run_fk" FOREIGN KEY ("candidate_id","run_id") REFERENCES "public"."autopep_protein_candidate"("id","run_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_project" ADD CONSTRAINT "autopep_project_owner_id_user_id_fk" FOREIGN KEY ("owner_id") REFERENCES "public"."user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_protein_candidate" ADD CONSTRAINT "autopep_protein_candidate_run_id_autopep_agent_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."autopep_agent_run"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_protein_candidate" ADD CONSTRAINT "autopep_protein_candidate_target_entity_id_autopep_target_entity_id_fk" FOREIGN KEY ("target_entity_id") REFERENCES "public"."autopep_target_entity"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_protein_candidate" ADD CONSTRAINT "autopep_protein_candidate_target_entity_run_fk" FOREIGN KEY ("target_entity_id","run_id") REFERENCES "public"."autopep_target_entity"("id","run_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_target_entity" ADD CONSTRAINT "autopep_target_entity_run_id_autopep_agent_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."autopep_agent_run"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "autopep_agent_event_run_id_idx" ON "autopep_agent_event" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "autopep_agent_run_project_id_idx" ON "autopep_agent_run" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "autopep_agent_run_status_idx" ON "autopep_agent_run" USING btree ("status");--> statement-breakpoint
CREATE INDEX "autopep_artifact_project_id_idx" ON "autopep_artifact" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "autopep_artifact_run_id_idx" ON "autopep_artifact" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "autopep_artifact_candidate_id_idx" ON "autopep_artifact" USING btree ("candidate_id");--> statement-breakpoint
CREATE INDEX "autopep_project_owner_idx" ON "autopep_project" USING btree ("owner_id");--> statement-breakpoint
CREATE INDEX "autopep_protein_candidate_run_id_idx" ON "autopep_protein_candidate" USING btree ("run_id");--> statement-breakpoint
CREATE INDEX "autopep_target_entity_run_id_idx" ON "autopep_target_entity" USING btree ("run_id");