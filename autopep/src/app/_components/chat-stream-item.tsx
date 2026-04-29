"use client";

import { CaretRight, FileText, Flask } from "@phosphor-icons/react";
import { useState } from "react";

import { renderToolDisplay } from "./tool-renderers";

export type StreamItem =
	| { kind: "user_message"; id: string; content: string }
	| {
			kind: "assistant_message";
			id: string;
			content: string;
			streaming: boolean;
	  }
	| {
			kind: "tool_call";
			id: string;
			tool: string;
			status: "running" | "completed" | "failed";
			durationMs?: number;
			display: Record<string, unknown>;
			output?: string;
			error?: string;
	  }
	| {
			kind: "sandbox_command";
			id: string;
			command: string;
			status: "running" | "completed" | "failed";
			stdout?: string;
			stderr?: string;
			durationMs?: number;
	  }
	| {
			kind: "artifact";
			id: string;
			artifactId: string;
			fileName: string;
			byteSize?: number;
	  }
	| {
			kind: "candidate";
			id: string;
			candidateId: string;
			rank: number;
			title: string;
	  };

type ChatStreamItemProps = {
	item: StreamItem;
	onOpenArtifact?: (artifactId: string) => void;
	onOpenCandidate?: (candidateId: string) => void;
};

export function ChatStreamItem({
	item,
	onOpenArtifact,
	onOpenCandidate,
}: ChatStreamItemProps) {
	if (item.kind === "user_message") {
		return (
			<div className="ml-8 break-words rounded-md bg-[#edf4ed] px-3 py-2 text-[#24302b] text-sm leading-6">
				{item.content}
			</div>
		);
	}

	if (item.kind === "assistant_message") {
		return (
			<div className="break-words text-[#24302b] text-sm leading-6">
				{item.content}
				{item.streaming ? (
					<span className="ml-0.5 animate-pulse">▍</span>
				) : null}
			</div>
		);
	}

	if (item.kind === "tool_call" || item.kind === "sandbox_command") {
		return <CollapsibleCard item={item} />;
	}

	if (item.kind === "artifact") {
		return (
			<button
				className="flex w-full items-center gap-2 rounded-md border border-[#dedbd2] bg-[#fffef9] px-3 py-2 text-left text-sm transition-colors hover:border-[#cbd736]"
				onClick={() => onOpenArtifact?.(item.artifactId)}
				type="button"
			>
				<FileText aria-hidden="true" size={16} />
				<span className="truncate">{item.fileName}</span>
				{item.byteSize ? (
					<span className="ml-auto text-[#7a817a] text-xs tabular-nums">
						{formatBytes(item.byteSize)}
					</span>
				) : null}
			</button>
		);
	}

	if (item.kind === "candidate") {
		return (
			<button
				className="flex w-full items-center gap-2 rounded-md border border-[#dedbd2] bg-[#fffef9] px-3 py-2 text-left text-sm transition-colors hover:border-[#cbd736]"
				onClick={() => onOpenCandidate?.(item.candidateId)}
				type="button"
			>
				<Flask aria-hidden="true" size={16} />
				<span className="truncate">
					#{item.rank} {item.title}
				</span>
			</button>
		);
	}

	return null;
}

function CollapsibleCard({
	item,
}: {
	item: Extract<StreamItem, { kind: "tool_call" | "sandbox_command" }>;
}) {
	const [open, setOpen] = useState(false);
	const isFailure = item.status === "failed";
	const summary = item.kind === "sandbox_command" ? item.command : "";

	return (
		<article
			className={`overflow-hidden rounded-md border ${
				isFailure ? "border-[#e3b6a8]" : "border-[#dedbd2]"
			} bg-[#fffef9]`}
		>
			<button
				aria-expanded={open}
				className="flex w-full items-center gap-2 px-3 py-2 text-left"
				onClick={() => setOpen((value) => !value)}
				type="button"
			>
				<CaretRight
					aria-hidden="true"
					className={`transition-transform ${open ? "rotate-90" : ""}`}
					size={14}
					weight="bold"
				/>
				<span className="font-mono text-[#3c4741] text-xs">
					{item.kind === "tool_call" ? item.tool : "$"}
				</span>
				<span className="min-w-0 flex-1 truncate text-[#26332e] text-sm">
					{summary}
				</span>
				{item.durationMs ? (
					<span className="font-mono text-[#7a817a] text-xs tabular-nums">
						{item.durationMs}ms
					</span>
				) : null}
				<span
					className={`rounded-md px-1.5 py-0.5 text-[10px] uppercase ${
						isFailure
							? "bg-[#f5d8cd] text-[#7c2f1c]"
							: item.status === "running"
								? "bg-[#eaf4cf] text-[#315419]"
								: "bg-[#e8f0e3] text-[#36573b]"
					}`}
				>
					{item.status}
				</span>
			</button>
			{open ? (
				<div className="border-[#dedbd2] border-t bg-[#f7f5ee] p-3 text-xs">
					{item.kind === "tool_call" ? (
						<ToolCallBody item={item} />
					) : (
						<SandboxBody item={item} />
					)}
				</div>
			) : null}
		</article>
	);
}

function ToolCallBody({
	item,
}: {
	item: Extract<StreamItem, { kind: "tool_call" }>;
}) {
	const render = renderToolDisplay(item.tool, item.display);
	return (
		<div className="space-y-2">
			<dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-1">
				{render.fields.map(([key, value]) => (
					<div className="contents" key={key}>
						<dt className="font-mono text-[#7a817a]">{key}</dt>
						<dd className="break-words font-mono text-[#27322f]">{value}</dd>
					</div>
				))}
			</dl>
			{item.output ? (
				<pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-[#fffef9] p-2 font-mono text-[#27322f] text-[11px]">
					{item.output}
				</pre>
			) : null}
			{item.error ? (
				<pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-[#fbe9e1] p-2 font-mono text-[#7c2f1c] text-[11px]">
					{item.error}
				</pre>
			) : null}
		</div>
	);
}

function SandboxBody({
	item,
}: {
	item: Extract<StreamItem, { kind: "sandbox_command" }>;
}) {
	return (
		<div className="space-y-2">
			<pre className="overflow-x-auto rounded bg-[#fffef9] p-2 font-mono text-[#27322f] text-[11px]">
				$ {item.command}
			</pre>
			{item.stdout ? (
				<pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-[#fffef9] p-2 font-mono text-[#27322f] text-[11px]">
					{item.stdout}
				</pre>
			) : null}
			{item.stderr ? (
				<pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-[#fbe9e1] p-2 font-mono text-[#7c2f1c] text-[11px]">
					{item.stderr}
				</pre>
			) : null}
		</div>
	);
}

const formatBytes = (bytes: number) => {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};
