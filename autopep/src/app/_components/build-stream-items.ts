import type { StreamItem } from "./chat-stream-item";
import { isMeaningfulTraceEvent } from "./event-filters";

type Message = {
	id: string;
	role: string;
	content: string;
	createdAt: string;
};

type Event = {
	id: string;
	sequence: number;
	type: string;
	createdAt: string;
	displayJson: Record<string, unknown>;
	summary?: string | null;
	title?: string | null;
};

type BuildArgs = { messages: Message[]; events: Event[] };

const getString = (value: unknown) =>
	typeof value === "string" ? value : undefined;

export const buildStreamItems = ({
	messages,
	events,
}: BuildArgs): StreamItem[] => {
	const ordered: { ts: number; render: () => StreamItem | null }[] = [];

	for (const message of messages) {
		const ts = Date.parse(message.createdAt);
		ordered.push({
			ts,
			render: () => {
				if (message.role === "user") {
					return {
						kind: "user_message",
						id: message.id,
						content: message.content,
					};
				}
				if (message.role === "assistant") {
					return {
						kind: "assistant_message",
						id: message.id,
						content: message.content,
						streaming: false,
					};
				}
				return null;
			},
		});
	}

	const toolCallStarts = new Map<string, Event>();
	const sandboxStarts = new Map<string, Event>();

	for (const event of events) {
		if (!isMeaningfulTraceEvent(event.type)) continue;

		if (event.type === "tool_call_started") {
			const callId = getString(event.displayJson.callId);
			if (callId) toolCallStarts.set(callId, event);
			continue;
		}

		if (event.type === "run_failed") {
			const reason = getString(event.displayJson.reason);
			ordered.push({
				ts: Date.parse(event.createdAt),
				render: () => ({
					kind: "run_error",
					id: event.id,
					content:
						getString(event.displayJson.message) ??
						(reason === "openai_prompt_blocked"
							? "Message blocked by OpenAI."
							: "Run failed."),
					detail:
						getString(event.displayJson.error) ??
						event.summary ??
						event.title ??
						undefined,
					tone: reason === "openai_prompt_blocked" ? "blocked" : "error",
				}),
			});
			continue;
		}

		if (
			event.type === "tool_call_completed" ||
			event.type === "tool_call_failed"
		) {
			const callId = getString(event.displayJson.callId);
			const start = callId ? toolCallStarts.get(callId) : undefined;
			const ts = Date.parse(start?.createdAt ?? event.createdAt);
			const startedMs = start ? Date.parse(start.createdAt) : ts;
			const endedMs = Date.parse(event.createdAt);
			ordered.push({
				ts,
				render: () => ({
					kind: "tool_call",
					id: event.id,
					tool: String(
						start?.displayJson.name ?? event.displayJson.name ?? "tool",
					),
					status: event.type === "tool_call_failed" ? "failed" : "completed",
					durationMs: endedMs - startedMs,
					display: {
						...(start?.displayJson ?? {}),
						...(event.displayJson ?? {}),
					},
					output: getString(event.displayJson.output),
					error: getString(event.displayJson.error),
				}),
			});
			if (callId) toolCallStarts.delete(callId);
			continue;
		}

		if (event.type === "sandbox_command_started") {
			const id = getString(event.displayJson.commandId);
			if (id) sandboxStarts.set(id, event);
			continue;
		}

		if (event.type === "sandbox_command_completed") {
			const id = getString(event.displayJson.commandId);
			const start = id ? sandboxStarts.get(id) : undefined;
			const ts = Date.parse(start?.createdAt ?? event.createdAt);
			const startedMs = start ? Date.parse(start.createdAt) : ts;
			const endedMs = Date.parse(event.createdAt);
			ordered.push({
				ts,
				render: () => ({
					kind: "sandbox_command",
					id: event.id,
					command: String(
						start?.displayJson.command ?? event.displayJson.command ?? "",
					),
					status:
						getString(event.displayJson.status) === "failed"
							? "failed"
							: "completed",
					stdout: getString(event.displayJson.stdout),
					stderr: getString(event.displayJson.stderr),
					durationMs: endedMs - startedMs,
				}),
			});
			if (id) sandboxStarts.delete(id);
			continue;
		}

		if (event.type === "artifact_created") {
			ordered.push({
				ts: Date.parse(event.createdAt),
				render: () => ({
					kind: "artifact",
					id: event.id,
					artifactId: String(event.displayJson.artifactId ?? ""),
					fileName: String(event.displayJson.fileName ?? "artifact"),
					byteSize:
						typeof event.displayJson.byteSize === "number"
							? (event.displayJson.byteSize as number)
							: undefined,
				}),
			});
			continue;
		}

		if (event.type === "candidate_ranked") {
			ordered.push({
				ts: Date.parse(event.createdAt),
				render: () => ({
					kind: "candidate",
					id: event.id,
					candidateId: String(event.displayJson.candidateId ?? ""),
					rank: Number(event.displayJson.rank ?? 0),
					title: String(event.displayJson.title ?? "candidate"),
				}),
			});
		}
	}

	// Surface still-running tool calls at their start time.
	for (const start of toolCallStarts.values()) {
		ordered.push({
			ts: Date.parse(start.createdAt),
			render: () => ({
				kind: "tool_call",
				id: start.id,
				tool: String(start.displayJson.name ?? "tool"),
				status: "running",
				display: start.displayJson,
			}),
		});
	}

	return ordered
		.sort((a, b) => a.ts - b.ts)
		.map((entry) => entry.render())
		.filter((value): value is StreamItem => value !== null);
};
