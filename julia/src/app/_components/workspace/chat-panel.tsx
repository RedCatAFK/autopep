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
			if (source) onRunCreated(source);
		},
	});
	const cancelRun = api.run.cancel.useMutation();

	useEffect(() => {
		setLocalMessages(messages);
	}, [messages]);

	const assistantDraft = useMemo(
		() => runEvents.events.map(getTextDelta).filter(Boolean).join(""),
		[runEvents.events],
	);

	const visibleMessages = useMemo(() => {
		if (!assistantDraft) return localMessages;
		const lastAssistantIndex = findLastAssistantMessageIndex(localMessages);
		if (lastAssistantIndex >= 0) {
			return localMessages.map((message, index) =>
				index === lastAssistantIndex
					? { ...message, content: assistantDraft }
					: message,
			);
		}
		return [
			...localMessages,
			{
				id: "assistant-draft",
				role: "assistant" as const,
				content: assistantDraft,
			},
		];
	}, [localMessages, assistantDraft]);

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
				{visibleMessages.length === 0 ? (
					<div className="empty-panel">
						<p>
							Describe a target. Julia will search the literature, propose
							binders, and run the workflow.
						</p>
					</div>
				) : (
					visibleMessages
						.filter(
							(message) => message.role !== "assistant" || message.content !== "",
						)
						.map((message) => (
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
					))
				)}
				{mergeToolEvents(runEvents.events).map((event) => (
					<ToolStep event={event} key={event.id ?? `seq-${event.sequence}`} />
				))}
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
			(typeof event.metadata?.toolName === "string" && event.metadata.toolName) ||
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
 * Pair tool_call_started with its tool_call_completed (by toolCallId) so the UI
 * shows one row per tool call that progresses from running → completed in place.
 */
function mergeToolEvents(events: RunEvent[]): RunEvent[] {
	type Bucket = {
		started: RunEvent;
		completed?: RunEvent;
	};
	const buckets = new Map<string, Bucket>();
	const order: string[] = [];

	for (const event of events) {
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
			if (!buckets.has(callId)) {
				buckets.set(callId, { started: event });
				order.push(callId);
			}
		} else {
			const bucket = buckets.get(callId);
			if (bucket) {
				bucket.completed = event;
			} else {
				buckets.set(callId, { started: event });
				order.push(callId);
			}
		}
	}

	return order.map((id) => {
		const bucket = buckets.get(id);
		if (!bucket) return { type: "tool_call_started", sequence: 0 } as RunEvent;
		if (!bucket.completed) return bucket.started;
		const startedMeta = bucket.started.metadata ?? {};
		const completedMeta = bucket.completed.metadata ?? {};
		return {
			...bucket.completed,
			metadata: {
				...startedMeta,
				...completedMeta,
				input: startedMeta.input ?? completedMeta.input,
			},
		};
	});
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
