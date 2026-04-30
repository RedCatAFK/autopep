"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

import type { RunEvent } from "./use-run-events";

type ToolStepProps = {
	event: RunEvent;
};

export function ToolStep({ event }: ToolStepProps) {
	const [expanded, setExpanded] = useState(false);
	const metadata = event.metadata ?? {};
	const toolName =
		getString(metadata.name) ??
		getString(metadata.toolName) ??
		getString(metadata.tool) ??
		"tool";
	const status = event.type.endsWith("completed") ? "completed" : "running";
	const error = getString(metadata.error);

	return (
		<div className={`tool-step ${error ? "error" : ""}`}>
			<button
				className="tool-step-summary"
				onClick={() => setExpanded((value) => !value)}
				type="button"
			>
				{expanded ? (
					<ChevronDown aria-hidden="true" size={15} />
				) : (
					<ChevronRight aria-hidden="true" size={15} />
				)}
				<span className="tool-name">{toolName}</span>
				<span className={`status-dot ${status}`} />
				<span className="tool-status">{error ? "error" : status}</span>
			</button>
			{expanded ? (
				<div className="tool-step-details">
					<Detail label="Started" value={formatDate(metadata.startedAt)} />
					<Detail label="Completed" value={formatDate(metadata.completedAt)} />
					{error ? <Detail label="Error" value={error} /> : null}
					<JsonBlock label="Args" value={metadata.args ?? metadata.input} />
					<JsonBlock
						label="Output"
						value={metadata.output ?? metadata.result ?? event.message}
					/>
					<ArtifactLinks value={metadata.artifacts} />
				</div>
			) : null}
		</div>
	);
}

function Detail({ label, value }: { label: string; value?: string | null }) {
	if (!value) return null;
	return (
		<div className="tool-detail-row">
			<span>{label}</span>
			<code>{value}</code>
		</div>
	);
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
	if (value === undefined || value === null || value === "") return null;
	return (
		<div className="tool-json-block">
			<span>{label}</span>
			<pre>
				{typeof value === "string" ? value : JSON.stringify(value, null, 2)}
			</pre>
		</div>
	);
}

function ArtifactLinks({ value }: { value: unknown }) {
	if (!Array.isArray(value) || value.length === 0) return null;
	return (
		<div className="tool-artifact-links">
			<span>Artifacts</span>
			{value.map((artifact, index) => {
				const item = artifact as {
					id?: string;
					filename?: string;
					viewerUrl?: string;
				};
				return item.viewerUrl ? (
					<a
						href={item.viewerUrl}
						key={item.id ?? index}
						rel="noreferrer"
						target="_blank"
					>
						{item.filename ?? item.id ?? "artifact"}
					</a>
				) : (
					<span key={item.id ?? index}>
						{item.filename ?? item.id ?? "artifact"}
					</span>
				);
			})}
		</div>
	);
}

function getString(value: unknown): string | null {
	return typeof value === "string" && value.trim() ? value : null;
}

function formatDate(value: unknown): string | null {
	if (!value) return null;
	const date = new Date(String(value));
	if (Number.isNaN(date.getTime())) return null;
	return date.toLocaleTimeString([], {
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit",
	});
}
