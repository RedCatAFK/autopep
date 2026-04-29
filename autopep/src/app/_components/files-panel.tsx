"use client";

import {
	CaretRight,
	FileText,
	Flask,
	Paperclip,
	Trash,
} from "@phosphor-icons/react";
import { useMemo, useState } from "react";

import { type FileGroup, groupArtifacts } from "./file-tree";
import { HoverTooltip } from "./hover-tooltip";

type ArtifactRow = {
	id: string;
	fileName: string;
	kind: string;
	candidateId: string | null;
	runId: string | null;
	signedUrl: string | null;
	byteSize: number;
};

type FilesPanelProps = {
	activeArtifactId: string | null;
	artifacts: ArtifactRow[];
	candidates: { id: string; rank: number; title: string }[];
	onDeleteAttachment?: (artifactId: string) => void;
	onOpenFile: (artifact: ArtifactRow) => void;
	runs: { id: string; startedAt: string; status: string }[];
};

const LONG_FILENAME = 24;

export function FilesPanel({
	activeArtifactId,
	artifacts,
	candidates,
	onDeleteAttachment,
	onOpenFile,
	runs,
}: FilesPanelProps) {
	const [filter, setFilter] = useState("");
	const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

	const groups = useMemo(() => {
		const all = groupArtifacts({ artifacts, candidates, runs });
		if (!filter) return all;
		const needle = filter.toLowerCase();
		return all
			.map((group) => ({
				...group,
				files: group.files.filter((f) =>
					f.fileName.toLowerCase().includes(needle),
				),
			}))
			.filter((group) => group.files.length > 0);
	}, [artifacts, candidates, runs, filter]);

	const isCollapsed = (key: string, defaultCollapsed: boolean) => {
		if (key in collapsed) return collapsed[key] ?? defaultCollapsed;
		return defaultCollapsed;
	};

	const toggle = (key: string, defaultCollapsed: boolean) => {
		setCollapsed((prev) => ({
			...prev,
			[key]: !isCollapsed(key, defaultCollapsed),
		}));
	};

	return (
		<aside className="flex h-full min-h-0 flex-col bg-[#fbfaf6]">
			<div className="shrink-0 border-[#e5e2d9] border-b p-3">
				<p className="mb-2 text-[#7a817a] text-xs uppercase">Files</p>
				<input
					className="w-full rounded-md border border-[#ddd9cf] bg-[#fffef9] px-2 py-1.5 text-[#27322f] text-xs outline-none transition-colors placeholder:text-[#9ba39c] focus:border-[#cbd736]"
					onChange={(event) => setFilter(event.target.value)}
					placeholder="Filter files…"
					type="search"
					value={filter}
				/>
			</div>
			<div className="min-h-0 flex-1 overflow-y-auto p-2">
				{groups.length === 0 ? (
					<p className="px-2 py-4 text-[#7a817a] text-sm">
						No files yet. Attach one or send a prompt.
					</p>
				) : (
					groups.map((group) => {
						const key = groupKey(group);
						const defaultCollapsed = group.kind === "run";
						return (
							<FilesGroup
								activeArtifactId={activeArtifactId}
								collapsed={isCollapsed(key, defaultCollapsed)}
								group={group}
								key={key}
								onDeleteAttachment={onDeleteAttachment}
								onOpenFile={onOpenFile}
								onToggle={() => toggle(key, defaultCollapsed)}
							/>
						);
					})
				)}
			</div>
		</aside>
	);
}

function groupKey(group: FileGroup): string {
	if (group.kind === "run") return `run:${group.runId}`;
	if (group.kind === "candidate") return `c:${group.candidateId}`;
	return "attachments";
}

function FilesGroup({
	activeArtifactId,
	collapsed,
	group,
	onDeleteAttachment,
	onOpenFile,
	onToggle,
}: {
	activeArtifactId: string | null;
	collapsed: boolean;
	group: FileGroup;
	onDeleteAttachment?: (artifactId: string) => void;
	onOpenFile: (artifact: ArtifactRow) => void;
	onToggle: () => void;
}) {
	const Icon =
		group.kind === "attachments"
			? Paperclip
			: group.kind === "candidate"
				? FileText
				: Flask;

	return (
		<div className="mb-1">
			<button
				aria-expanded={!collapsed}
				className="flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-left transition-colors hover:bg-[#f1efe6]"
				onClick={onToggle}
				type="button"
			>
				<CaretRight
					aria-hidden="true"
					className={`transition-transform ${collapsed ? "" : "rotate-90"}`}
					size={12}
					weight="bold"
				/>
				<Icon aria-hidden="true" size={14} />
				<span className="min-w-0 flex-1 truncate text-[#27322f] text-xs">
					{group.label}
				</span>
				<span className="shrink-0 font-mono text-[#7a817a] text-xs tabular-nums">
					{group.files.length}
				</span>
			</button>
			{collapsed ? null : (
				<ul className="ml-4 border-[#e5e2d9] border-l">
					{group.files.map((file) => (
						<FileRow
							active={activeArtifactId === file.id}
							file={file}
							isAttachment={group.kind === "attachments"}
							key={file.id}
							onDeleteAttachment={onDeleteAttachment}
							onOpenFile={onOpenFile}
						/>
					))}
				</ul>
			)}
		</div>
	);
}

function FileRow({
	active,
	file,
	isAttachment,
	onDeleteAttachment,
	onOpenFile,
}: {
	active: boolean;
	file: ArtifactRow;
	isAttachment: boolean;
	onDeleteAttachment?: (artifactId: string) => void;
	onOpenFile: (artifact: ArtifactRow) => void;
}) {
	const longName = file.fileName.length > LONG_FILENAME;
	const nameNode = (
		<span className="min-w-0 flex-1 truncate text-left text-[#27322f] text-xs">
			{file.fileName}
		</span>
	);

	return (
		<li
			className={`group flex items-center gap-2 rounded px-2 py-1 ${
				active ? "bg-[#eaf4cf]" : "hover:bg-[#f1efe6]"
			}`}
		>
			<button
				className="flex min-w-0 flex-1 items-center gap-2 text-left"
				onClick={() => onOpenFile(file)}
				type="button"
			>
				{longName ? (
					<HoverTooltip label={file.fileName}>{nameNode}</HoverTooltip>
				) : (
					nameNode
				)}
				{file.byteSize > 0 ? (
					<span className="shrink-0 font-mono text-[#9aa19c] text-xs tabular-nums">
						{formatBytes(file.byteSize)}
					</span>
				) : null}
			</button>
			{isAttachment && onDeleteAttachment ? (
				<button
					aria-label={`Delete ${file.fileName}`}
					className="shrink-0 rounded p-1 text-[#9aa19c] opacity-0 transition-opacity hover:bg-[#f3e3df] hover:text-[#7b2c20] focus:opacity-100 group-hover:opacity-100"
					onClick={() => onDeleteAttachment(file.id)}
					type="button"
				>
					<Trash aria-hidden="true" size={12} />
				</button>
			) : null}
		</li>
	);
}

function formatBytes(bytes: number) {
	if (bytes < 1024) {
		return `${bytes} B`;
	}
	if (bytes < 1024 * 1024) {
		return `${(bytes / 1024).toFixed(1)} KB`;
	}
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
