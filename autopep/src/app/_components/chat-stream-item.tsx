"use client";

import { CaretRight, FileText, Flask } from "@phosphor-icons/react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

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
				<MarkdownMessage content={item.content} />
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

function MarkdownMessage({ content }: { content: string }) {
	return (
		<ReactMarkdown
			components={{
				a: ({ children, ...props }) => (
					<a
						{...props}
						className="font-medium text-[#087a66] underline decoration-[#087a66]/30 underline-offset-3 hover:decoration-[#087a66]"
						rel="noreferrer"
						target="_blank"
					>
						{children}
					</a>
				),
				blockquote: ({ children }) => (
					<blockquote className="my-3 border-[#cbd736] border-l-2 py-0.5 pl-3 text-[#52605a]">
						{children}
					</blockquote>
				),
				code: ({ children, className, ...props }) => (
					<code
						{...props}
						className={`${className ?? ""} rounded bg-[#ece9df] px-1 py-0.5 font-mono text-[#20352e] text-[12px]`}
					>
						{children}
					</code>
				),
				h1: ({ children }) => (
					<h1 className="mt-3 mb-1 font-semibold text-[#17211e] text-base first:mt-0">
						{children}
					</h1>
				),
				h2: ({ children }) => (
					<h2 className="mt-3 mb-1 font-semibold text-[#17211e] text-sm first:mt-0">
						{children}
					</h2>
				),
				h3: ({ children }) => (
					<h3 className="mt-3 mb-1 font-semibold text-[#17211e] text-sm first:mt-0">
						{children}
					</h3>
				),
				li: ({ children }) => <li className="pl-1">{children}</li>,
				ol: ({ children }) => (
					<ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>
				),
				p: ({ children }) => (
					<p className="my-2 first:mt-0 last:mb-0">{children}</p>
				),
				pre: ({ children }) => (
					<pre className="my-3 overflow-x-auto rounded-md border border-[#dedbd2] bg-[#fffef9] p-3 font-mono text-[#27322f] text-[12px] leading-5">
						{children}
					</pre>
				),
				table: ({ children }) => (
					<div className="my-3 overflow-x-auto rounded-md border border-[#dedbd2]">
						<table className="w-full border-collapse text-left text-xs">
							{children}
						</table>
					</div>
				),
				td: ({ children }) => (
					<td className="border-[#dedbd2] border-t px-2 py-1.5 align-top">
						{children}
					</td>
				),
				th: ({ children }) => (
					<th className="bg-[#f0efe8] px-2 py-1.5 font-medium text-[#3c4741]">
						{children}
					</th>
				),
				ul: ({ children }) => (
					<ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>
				),
			}}
			remarkPlugins={[remarkGfm]}
		>
			{content}
		</ReactMarkdown>
	);
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
