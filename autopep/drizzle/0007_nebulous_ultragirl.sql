CREATE TABLE "autopep_thread_item" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"thread_id" uuid NOT NULL,
	"run_id" uuid,
	"sequence" bigint NOT NULL,
	"item_type" text NOT NULL,
	"role" text,
	"content_json" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"attachment_refs_json" jsonb,
	"context_refs_json" jsonb,
	"recipe_refs_json" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "autopep_thread_item_thread_seq_unique" UNIQUE("thread_id","sequence")
);
--> statement-breakpoint
DROP TABLE "autopep_message" CASCADE;--> statement-breakpoint
ALTER TABLE "autopep_thread_item" ADD CONSTRAINT "autopep_thread_item_thread_id_autopep_thread_id_fk" FOREIGN KEY ("thread_id") REFERENCES "public"."autopep_thread"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "autopep_thread_item" ADD CONSTRAINT "autopep_thread_item_run_id_autopep_agent_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."autopep_agent_run"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "autopep_thread_item_thread_seq_idx" ON "autopep_thread_item" USING btree ("thread_id","sequence");--> statement-breakpoint
CREATE INDEX "autopep_thread_item_run_idx" ON "autopep_thread_item" USING btree ("run_id");