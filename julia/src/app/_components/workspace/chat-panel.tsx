"use client";

import { Send } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { api } from "@/trpc/react";
import { ContextPills, type WorkspaceContextReference } from "./context-pills";
import { ToolStep } from "./tool-step";
import { type RunEvent, useRunEvents } from "./use-run-events";

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
	onRunCreated: (runId: string) => void;
	onRemoveContext: (referenceId: string) => void;
	activeRunId: string | null;
};

export function ChatPanel({
	projectId,
	threadId,
	messages,
	contextReferences,
	onRunCreated,
	onRemoveContext,
	activeRunId,
}: ChatPanelProps) {
	const [prompt, setPrompt] = useState("");
	const [localMessages, setLocalMessages] =
		useState<WorkspaceMessage[]>(messages);
	const [assistantDraft, setAssistantDraft] = useState("");
	const runEvents = useRunEvents(activeRunId);
	const sendMessage = api.run.sendMessage.useMutation({
		onSuccess(data) {
			const runId = getRunId(data);
			if (runId) onRunCreated(runId);
		},
	});

	useEffect(() => {
		setLocalMessages(messages);
	}, [messages]);

	useEffect(() => {
		for (const event of runEvents.events) {
			if (event.type !== "message") continue;
			const delta = getTextDelta(event);
			if (delta) setAssistantDraft((value) => value + delta);
		}
	}, [runEvents.events]);

	const visibleMessages = useMemo(() => {
		if (!assistantDraft) return localMessages;
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
		Boolean(activeRunId && latestEvent?.type !== "completed");

	const submit = () => {
		const content = prompt.trim();
		if (!content || sendMessage.isPending) return;

		setPrompt("");
		setAssistantDraft("");
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

	return (
		<aside aria-label="Julia chat" className="chat-panel">
			<div className="panel-header">
				<div>
					<p className="eyebrow">Julia</p>
					<h2>Chat</h2>
				</div>
				<RunStatus connection={runEvents.connection} event={latestEvent} />
			</div>
			<div className="message-list">
				{visibleMessages.length === 0 ? (
					<div className="empty-panel">
						<p>Ask Julia to design, inspect, or refine a protein workflow.</p>
					</div>
				) : (
					visibleMessages.map((message) => (
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
				{runEvents.events
					.filter(
						(event) =>
							event.type === "tool_started" || event.type === "tool_completed",
					)
					.map((event) => (
						<ToolStep event={event} key={event.id} />
					))}
				{sendMessage.error ? (
					<div className="run-error" role="alert">
						{sendMessage.error.message}
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
						{statusText(
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
						placeholder="Message Julia..."
						value={prompt}
					/>
					<button
						aria-label="Send message"
						className="primary-button icon-only"
						disabled={!prompt.trim() || sendMessage.isPending}
						onClick={submit}
						type="button"
					>
						<Send aria-hidden="true" size={17} />
					</button>
				</div>
			</div>
		</aside>
	);
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
				className={`status-dot ${event?.type === "completed" ? "completed" : "running"}`}
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
	if (event?.type === "completed") return "Done";
	if (event?.type) return event.type.replaceAll("_", " ");
	if (connection === "streaming") return "Waiting for events";
	if (connection === "polling") return "Polling for events";
	return "Idle";
}

function getRunId(value: unknown): string | null {
	if (!value || typeof value !== "object") return null;
	const record = value as {
		id?: unknown;
		runId?: unknown;
		run?: { id?: unknown };
	};
	if (typeof record.runId === "string") return record.runId;
	if (typeof record.id === "string") return record.id;
	if (typeof record.run?.id === "string") return record.run.id;
	return null;
}

function getTextDelta(event: RunEvent): string | null {
	const metadata = event.metadata ?? {};
	const delta = metadata.text_delta ?? metadata.delta ?? metadata.content_delta;
	if (typeof delta === "string") return delta;
	if (event.message && metadata.final !== true) return event.message;
	return null;
}
