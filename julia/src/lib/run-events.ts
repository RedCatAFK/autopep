export type RunEventType =
	| "queued"
	| "running"
	| "tool_started"
	| "tool_completed"
	| "message"
	| "artifact_created"
	| "completed"
	| "run_error";

export type RunEventTone = "muted" | "info" | "success" | "warning" | "error";

const LABELS: Record<RunEventType, string> = {
	queued: "Queued",
	running: "Running",
	tool_started: "Tool started",
	tool_completed: "Tool completed",
	message: "Message",
	artifact_created: "Artifact created",
	completed: "Completed",
	run_error: "Run error",
};

const TONES: Record<RunEventType, RunEventTone> = {
	queued: "muted",
	running: "info",
	tool_started: "info",
	tool_completed: "success",
	message: "info",
	artifact_created: "success",
	completed: "success",
	run_error: "error",
};

export function eventDisplayLabel(type: RunEventType): string {
	return LABELS[type];
}

export function eventTone(type: RunEventType): RunEventTone {
	return TONES[type];
}
