const HIDDEN = new Set([
	"assistant_message_started",
	"assistant_message_completed",
	"assistant_token_delta",
	"agent_changed",
	"reasoning_step",
]);

export const isMeaningfulTraceEvent = (type: string) => !HIDDEN.has(type);
