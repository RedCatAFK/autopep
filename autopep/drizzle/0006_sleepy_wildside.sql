ALTER TYPE "public"."artifact_kind" ADD VALUE 'attachment' BEFORE 'other';--> statement-breakpoint
ALTER TABLE "autopep_message" ADD COLUMN "metadata" jsonb DEFAULT '{}'::jsonb NOT NULL;--> statement-breakpoint
ALTER TABLE "autopep_workspace" ADD COLUMN "auto_named_at" timestamp with time zone;