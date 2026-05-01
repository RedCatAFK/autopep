"use client";

import { Send, Square } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { api } from "@/trpc/react";
import { ContextPills, type WorkspaceContextReference } from "./context-pills";
import { ToolStep } from "./tool-step";
import {
	type RunEvent,
	type RunEventSource,
	useRunEvents,
} from "./use-run-events";

export type WorkspaceMessage = {
	id: string;
	role: "user" | "assistant" | "system";
	content: string;
	createdAt?: string | Date | null;
};

type ChatPanelProps = {
	projectId: string;
	threadId?: string | null;
	messages: WorkspaceMessage[];
	contextReferences: WorkspaceContextReference[];
	onRunCreated: (source: RunEventSource) => void;
	onRemoveContext: (referenceId: string) => void;
	runSource: RunEventSource | null;
};

export function ChatPanel({
	projectId,
	threadId,
	messages,
	contextReferences,
	onRunCreated,
	onRemoveContext,
	runSource,
}: ChatPanelProps) {
	const [prompt, setPrompt] = useState("");
	const [localMessages, setLocalMessages] =
		useState<WorkspaceMessage[]>(messages);
	const runEvents = useRunEvents(runSource);
	const sendMessage = api.run.sendMessage.useMutation({
		onSuccess(data) {
			const source = toRunEventSource(data);
			if (!source) return;
			// Append an optimistic assistant placeholder so the streaming draft
			// has a target row to overlay. Without it, the first delta lands on
			// the *previous* run's assistant message (until polling refetches
			// the new placeholder ~5s later) and visibly clobbers it.
			const assistantMessageId =
				typeof (data as { assistantMessageId?: unknown }).assistantMessageId ===
				"string"
					? (data as { assistantMessageId: string }).assistantMessageId
					: `pending-${source.runId}`;
			setLocalMessages((current) => [
				...current,
				{
					id: assistantMessageId,
					role: "assistant",
					content: "",
				},
			]);
			onRunCreated(source);
		},
	});
	const cancelRun = api.run.cancel.useMutation();

	useEffect(() => {
		setLocalMessages(messages);
	}, [messages]);

	const runSegments = useMemo(
		() => buildRunSegments(runEvents.events),
		[runEvents.events],
	);
	const hasRunOutput = runSegments.length > 0;
	const assistantDraft = useMemo(
		() =>
			runSegments
				.filter((segment) => segment.kind === "text")
				.map((segment) => (segment.kind === "text" ? segment.text : ""))
				.join(""),
		[runSegments],
	);

	const renderItems = useMemo(
		() => buildRenderItems(localMessages, hasRunOutput ? runSegments : null),
		[localMessages, hasRunOutput, runSegments],
	);

	const latestEvent = runEvents.events.at(-1);
	const busy =
		sendMessage.isPending ||
		Boolean(runSource && !isTerminalEvent(latestEvent));
	const canStop = busy && Boolean(runSource) && !cancelRun.isPending;

	const submit = () => {
		const content = prompt.trim();
		if (!content || sendMessage.isPending) return;

		setPrompt("");
		setLocalMessages((current) => [
			...current,
			{
				id: `local-${Date.now()}`,
				role: "user",
				content,
				createdAt: new Date(),
			},
		]);
		sendMessage.mutate({
			projectId,
			threadId: threadId ?? undefined,
			message: content,
			contextReferenceIds: contextReferences.map((reference) => reference.id),
		});
	};

	const stop = () => {
		if (!runSource || cancelRun.isPending) return;
		cancelRun.mutate({ runId: runSource.runId });
	};

	return (
		<aside aria-label="Julia chat" className="chat-panel">
			<div className="panel-header">
				<div>
					<h2>Chat</h2>
				</div>
				<RunStatus connection={runEvents.connection} event={latestEvent} />
			</div>
			<div className="message-list">
				{renderItems.length === 0 ? (
					<div className="empty-panel">
						<p>
							Describe a target. Julia will search the literature, propose
							binders, and run the workflow.
						</p>
					</div>
				) : (
					renderItems.map((item) => {
						if (item.kind === "message") {
							const message = item.message;
							return (
								<article className={`message ${message.role}`} key={message.id}>
									<span className="message-role">{message.role}</span>
									<div className="message-body">
										{message.role === "assistant" ? (
											<ReactMarkdown remarkPlugins={[remarkGfm]}>
												{message.content}
											</ReactMarkdown>
										) : (
											<p>{message.content}</p>
										)}
									</div>
								</article>
							);
						}
						if (item.kind === "text") {
							return (
								<article className="message assistant" key={item.id}>
									<span className="message-role">assistant</span>
									<div className="message-body">
										<ReactMarkdown remarkPlugins={[remarkGfm]}>
											{item.text}
										</ReactMarkdown>
									</div>
								</article>
							);
						}
						return <ToolStep event={item.event} key={item.id} />;
					})
				)}
				{busy ? (
					<ThinkingIndicator
						label={thinkingLabel(
							latestEvent,
							sendMessage.isPending,
							cancelRun.isPending,
							assistantDraft.length > 0,
						)}
					/>
				) : null}
				{sendMessage.error ? (
					<div className="run-error" role="alert">
						{sendMessage.error.message}
					</div>
				) : null}
				{cancelRun.error ? (
					<div className="run-error" role="alert">
						{cancelRun.error.message}
					</div>
				) : null}
			</div>
			<div className="chat-composer">
				<ContextPills
					disabled={sendMessage.isPending}
					onRemove={onRemoveContext}
					references={contextReferences}
				/>
				<div className="status-row">
					<span className={`status-dot ${busy ? "running" : "completed"}`} />
					<span>
						{cancelRun.isPending
							? "Stopping…"
							: statusText(
									latestEvent,
									runEvents.connection,
									sendMessage.isPending,
								)}
					</span>
				</div>
				<div className="prompt-row">
					<textarea
						aria-label="Prompt"
						onChange={(event) => setPrompt(event.target.value)}
						onKeyDown={(event) => {
							if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
								event.preventDefault();
								submit();
							}
						}}
						placeholder="Message Julia"
						value={prompt}
					/>
					{busy && runSource ? (
						<button
							aria-label="Stop agent"
							className="primary-button icon-only stop-button"
							disabled={!canStop}
							onClick={stop}
							title="Stop"
							type="button"
						>
							<Square aria-hidden="true" fill="currentColor" size={12} />
						</button>
					) : (
						<button
							aria-label="Send message"
							className="primary-button icon-only"
							disabled={!prompt.trim() || sendMessage.isPending}
							onClick={submit}
							type="button"
						>
							<Send aria-hidden="true" size={16} strokeWidth={1.8} />
						</button>
					)}
				</div>
			</div>
		</aside>
	);
}

const COMP_BIO_VERBS = [
	"Aligning",
	"AlphaFolding",
	"Annotating",
	"Assembling",
	"Basecalling",
	"Benchmarking",
	"Catalyzing",
	"Cell-Typing",
	"Chaperoning",
	"Clustering",
	"Computing",
	"Curating",
	"Decoding",
	"Designing",
	"Diagnosing",
	"Docking",
	"Elucidating",
	"Embedding",
	"Evolving",
	"Expressing",
	"Folding",
	"Forecasting",
	"Genotyping",
	"Graphing",
	"Harmonizing",
	"Hypothesizing",
	"Imputing",
	"Inferring",
	"Mapping",
	"Mining",
	"Modeling",
	"Optimizing",
	"Perturbing",
	"Profiling",
	"Reticulating",
	"Scaffolding",
	"Screening",
	"Sequencing",
	"Simulating",
	"Splicing",
] as const;

const GENERIC_THINKING_LABEL = "__thinking__";

function ThinkingIndicator({ label }: { label: string }) {
	const isGeneric = label === GENERIC_THINKING_LABEL;
	const [verb, setVerb] = useState(() => pickVerb());
	const recentRef = useRef<string[]>([]);

	useEffect(() => {
		if (!isGeneric) return;
		const next = pickVerb(recentRef.current);
		setVerb(next);
		recentRef.current = [...recentRef.current, next].slice(-8);
		const id = window.setInterval(() => {
			const v = pickVerb(recentRef.current);
			recentRef.current = [...recentRef.current, v].slice(-8);
			setVerb(v);
		}, 2200);
		return () => window.clearInterval(id);
	}, [isGeneric]);

	const display = isGeneric ? `${verb}…` : label;

	return (
		<div aria-live="polite" className="thinking-indicator" role="status">
			<span aria-hidden="true" className="thinking-dots">
				<span />
				<span />
				<span />
			</span>
			<span className="thinking-label">{display}</span>
		</div>
	);
}

function pickVerb(recent: string[] = []): string {
	const pool = COMP_BIO_VERBS.filter((v) => !recent.includes(v));
	const choices = pool.length > 0 ? pool : COMP_BIO_VERBS;
	return choices[Math.floor(Math.random() * choices.length)] ?? "Thinking";
}

function thinkingLabel(
	event: RunEvent | undefined,
	isSending: boolean,
	isCanceling: boolean,
	hasDraft: boolean,
): string {
	if (isCanceling) return "Stopping…";
	if (isSending) return "Sending…";
	if (event?.type === "tool_call_started" || event?.type === "tool_started") {
		const name =
			(typeof event.metadata?.toolName === "string" &&
				event.metadata.toolName) ||
			(typeof event.metadata?.name === "string" && event.metadata.name) ||
			null;
		return name ? `Running ${name}…` : "Running tool…";
	}
	if (hasDraft || event?.type === "text_delta" || event?.type === "message") {
		return "Writing response…";
	}
	return GENERIC_THINKING_LABEL;
}

function RunStatus({
	event,
	connection,
}: {
	event?: RunEvent;
	connection: string;
}) {
	return (
		<div className="run-status">
			<span
				className={`status-dot ${isTerminalEvent(event) ? "completed" : "running"}`}
			/>
			<span>{event?.type ? event.type.replaceAll("_", " ") : connection}</span>
		</div>
	);
}

function statusText(
	event: RunEvent | undefined,
	connection: string,
	isSending: boolean,
): string {
	if (isSending) return "Sending";
	if (isTerminalEvent(event)) return terminalStatus(event) ?? "Done";
	if (event?.type) return event.type.replaceAll("_", " ");
	if (connection === "open") return "Streaming";
	if (connection === "connecting") return "Connecting";
	if (connection === "error") return "Connection error";
	if (connection === "closed") return "Reconnecting";
	return "Idle";
}

function toRunEventSource(value: unknown): RunEventSource | null {
	if (!value || typeof value !== "object") return null;
	const record = value as {
		runId?: unknown;
		wsUrl?: unknown;
		wsToken?: unknown;
	};
	if (
		typeof record.runId !== "string" ||
		typeof record.wsUrl !== "string" ||
		typeof record.wsToken !== "string"
	) {
		return null;
	}
	return {
		runId: record.runId,
		wsUrl: record.wsUrl,
		wsToken: record.wsToken,
	};
}

/**
 * Walk the run's events in chronological (sequence) order and produce an
 * interleaved segment list: text deltas accumulate into a text segment until a
 * tool call appears, the tool call becomes its own segment, and any further
 * text deltas start a fresh text segment after the tool. tool_call_started and
 * tool_call_completed for the same toolCallId are merged into one segment that
 * progresses running → completed in place.
 */
type RunSegment =
	| { kind: "text"; id: string; text: string }
	| { kind: "tool"; id: string; event: RunEvent };

function buildRunSegments(events: RunEvent[]): RunSegment[] {
	const segments: RunSegment[] = [];
	const toolByCallId = new Map<
		string,
		{ kind: "tool"; id: string; event: RunEvent }
	>();
	let currentText: { kind: "text"; id: string; text: string } | null = null;

	for (const event of events) {
		const delta = getTextDelta(event);
		if (delta !== null) {
			if (!currentText) {
				currentText = {
					kind: "text",
					id: `text-${event.sequence}`,
					text: "",
				};
				segments.push(currentText);
			}
			currentText.text += delta;
			continue;
		}

		const isStarted =
			event.type === "tool_call_started" || event.type === "tool_started";
		const isCompleted =
			event.type === "tool_call_completed" || event.type === "tool_completed";
		if (!isStarted && !isCompleted) continue;

		const metadata = event.metadata ?? {};
		const callId =
			(typeof metadata.toolCallId === "string" && metadata.toolCallId) ||
			(typeof metadata.callId === "string" && metadata.callId) ||
			`seq-${event.sequence}`;

		if (isStarted) {
			currentText = null;
			if (!toolByCallId.has(callId)) {
				const segment = { kind: "tool" as const, id: callId, event };
				toolByCallId.set(callId, segment);
				segments.push(segment);
			}
			continue;
		}

		// tool_call_completed: merge into the started segment if we have it,
		// otherwise drop it as a standalone (covers reconnect-mid-run).
		const existing = toolByCallId.get(callId);
		const startedMeta = existing?.event.metadata ?? {};
		const completedMeta = event.metadata ?? {};
		const merged: RunEvent = {
			...event,
			metadata: {
				...startedMeta,
				...completedMeta,
				input: startedMeta.input ?? completedMeta.input,
			},
		};
		if (existing) {
			existing.event = merged;
		} else {
			currentText = null;
			const segment = { kind: "tool" as const, id: callId, event: merged };
			toolByCallId.set(callId, segment);
			segments.push(segment);
		}
	}

	return segments;
}

type RenderItem =
	| { kind: "message"; message: WorkspaceMessage }
	| { kind: "text"; id: string; text: string }
	| { kind: "tool"; id: string; event: RunEvent };

/**
 * Combine the persisted message list with the live run's interleaved segments.
 * The last assistant slot is replaced by the run segments while a run is
 * producing output; once the run finishes and polling refreshes the persisted
 * assistant message, the segments still cover that slot until a new run starts
 * and `useRunEvents` resets the event list.
 */
function buildRenderItems(
	messages: WorkspaceMessage[],
	runSegments: RunSegment[] | null,
): RenderItem[] {
	const lastAssistantIndex = findLastAssistantMessageIndex(messages);
	const items: RenderItem[] = [];

	for (let index = 0; index < messages.length; index += 1) {
		const message = messages[index];
		if (!message) continue;
		if (index === lastAssistantIndex && runSegments && runSegments.length > 0) {
			for (const segment of runSegments) items.push(segment);
			continue;
		}
		if (message.role === "assistant" && message.content === "") continue;
		items.push({ kind: "message", message });
	}

	if (
		runSegments &&
		runSegments.length > 0 &&
		(lastAssistantIndex < 0 ||
			!items.some((item) => item.kind === "text" || item.kind === "tool"))
	) {
		for (const segment of runSegments) items.push(segment);
	}

	return items;
}

function findLastAssistantMessageIndex(messages: WorkspaceMessage[]): number {
	for (let index = messages.length - 1; index >= 0; index -= 1) {
		if (messages[index]?.role === "assistant") return index;
	}
	return -1;
}

function getTextDelta(event: RunEvent): string | null {
	if (event.type !== "message" && event.type !== "text_delta") return null;
	const metadata = event.metadata ?? {};
	const delta =
		metadata.text_delta ??
		metadata.delta ??
		metadata.content_delta ??
		metadata.text;
	if (typeof delta === "string") return delta;
	if (event.message && metadata.final !== true) return event.message;
	return null;
}

function isTerminalEvent(event: RunEvent | undefined): boolean {
	const status = terminalStatus(event);
	return status === "completed" || status === "failed" || status === "canceled";
}

function terminalStatus(event: RunEvent | undefined): string | null {
	if (!event) return null;
	if (event.type === "completed") return "completed";
	if (event.type === "run_error") return "failed";
	const metadata = event.metadata ?? {};
	return typeof metadata.status === "string" ? metadata.status : null;
}
