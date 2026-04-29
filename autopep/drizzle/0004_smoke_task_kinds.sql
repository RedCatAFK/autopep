ALTER TYPE "public"."agent_task_kind" ADD VALUE IF NOT EXISTS 'smoke_chat';--> statement-breakpoint
ALTER TYPE "public"."agent_task_kind" ADD VALUE IF NOT EXISTS 'smoke_tool';--> statement-breakpoint
ALTER TYPE "public"."agent_task_kind" ADD VALUE IF NOT EXISTS 'smoke_sandbox';--> statement-breakpoint
ALTER TABLE "autopep_agent_run" ALTER COLUMN "model" SET DEFAULT 'gpt-5.5';
