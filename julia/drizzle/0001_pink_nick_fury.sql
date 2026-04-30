ALTER TYPE "public"."julia_run_event_type" ADD VALUE 'run_status' BEFORE 'tool_started';--> statement-breakpoint
ALTER TYPE "public"."julia_run_event_type" ADD VALUE 'text_delta' BEFORE 'tool_started';--> statement-breakpoint
ALTER TYPE "public"."julia_run_event_type" ADD VALUE 'tool_call_started' BEFORE 'message';--> statement-breakpoint
ALTER TYPE "public"."julia_run_event_type" ADD VALUE 'tool_call_completed' BEFORE 'message';