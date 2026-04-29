"use client";

import {
	DownloadSimple,
	FileImage,
	FileText,
	WarningCircle,
} from "@phosphor-icons/react";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

const MolstarViewer = dynamic(
	() => import("./molstar-viewer").then((mod) => mod.MolstarViewer),
	{ ssr: false },
);

const STRUCTURE_EXTENSIONS = new Set(["cif", "mmcif", "pdb"]);
const TEXT_EXTENSIONS = new Set([
	"csv",
	"fa",
	"fasta",
	"json",
	"log",
	"md",
	"py",
	"txt",
	"yaml",
	"yml",
]);
const IMAGE_EXTENSIONS = new Set(["jpeg", "jpg", "png", "svg"]);

type FilePreviewProps = {
	artifactId: string;
	fileName: string;
	signedUrl: string | null;
};

export function FilePreview({
	artifactId,
	fileName,
	signedUrl,
}: FilePreviewProps) {
	const extension = useMemo(() => extractExtension(fileName), [fileName]);

	if (!signedUrl) {
		return (
			<div className="flex h-full items-center justify-center px-6 text-[#7a817a] text-sm">
				No signed URL available for {fileName}.
			</div>
		);
	}

	if (STRUCTURE_EXTENSIONS.has(extension)) {
		return (
			<div className="h-full min-h-0">
				<MolstarViewer
					artifactId={artifactId}
					label={fileName}
					url={signedUrl}
				/>
			</div>
		);
	}

	if (IMAGE_EXTENSIONS.has(extension)) {
		return <ImagePreview fileName={fileName} signedUrl={signedUrl} />;
	}

	if (TEXT_EXTENSIONS.has(extension)) {
		return <TextPreview fileName={fileName} signedUrl={signedUrl} />;
	}

	return <SkeletonPreview fileName={fileName} signedUrl={signedUrl} />;
}

function ImagePreview({
	fileName,
	signedUrl,
}: {
	fileName: string;
	signedUrl: string;
}) {
	const checkered =
		"repeating-conic-gradient(#f0efe8 0% 25%, #fffef9 0% 50%) 50% / 16px 16px";
	return (
		<div
			className="flex h-full items-center justify-center overflow-auto p-6"
			style={{ background: checkered }}
		>
			{/* biome-ignore lint/performance/noImgElement: signed URLs cannot use next/image */}
			<img
				alt={fileName}
				className="max-h-full max-w-full rounded border border-[#e5e2d9] bg-[#fffef9] shadow-[0_18px_50px_-32px_rgba(25,39,33,0.55)]"
				src={signedUrl}
			/>
		</div>
	);
}

function TextPreview({
	fileName,
	signedUrl,
}: {
	fileName: string;
	signedUrl: string;
}) {
	const [content, setContent] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [softWrap, setSoftWrap] = useState(false);

	useEffect(() => {
		let cancelled = false;
		setContent(null);
		setError(null);

		(async () => {
			try {
				const response = await fetch(signedUrl);
				if (!response.ok) {
					throw new Error(`HTTP ${response.status}`);
				}
				const text = await response.text();
				if (!cancelled) {
					setContent(text);
				}
			} catch (cause) {
				if (!cancelled) {
					setError(cause instanceof Error ? cause.message : String(cause));
				}
			}
		})();

		return () => {
			cancelled = true;
		};
	}, [signedUrl]);

	const byteSize = useMemo(() => {
		if (content == null) {
			return 0;
		}
		return new Blob([content]).size;
	}, [content]);

	const lines = useMemo(() => (content ?? "").split("\n"), [content]);

	if (error) {
		return (
			<div className="flex h-full items-center justify-center gap-2 px-6 text-[#7b2c20] text-sm">
				<WarningCircle aria-hidden="true" size={18} />
				<span>
					Could not load {fileName}: {error}
				</span>
			</div>
		);
	}

	if (content == null) {
		return (
			<div className="flex h-full items-center justify-center text-[#7a817a] text-sm">
				Loading {fileName}…
			</div>
		);
	}

	return (
		<div className="flex h-full min-h-0 flex-col">
			<div className="flex shrink-0 items-center justify-between gap-3 border-[#e5e2d9] border-b bg-[#f8f7f2] px-3 py-1.5 text-[#5a6360] text-xs">
				<span>
					{lines.length} lines · {formatBytes(byteSize)}
				</span>
				<label className="flex cursor-pointer items-center gap-1.5">
					<input
						checked={softWrap}
						onChange={(event) => setSoftWrap(event.target.checked)}
						type="checkbox"
					/>
					Soft wrap
				</label>
			</div>
			<div className="flex min-h-0 flex-1 overflow-auto bg-[#fffef9] font-mono text-[#26332e] text-xs leading-5">
				<pre
					aria-hidden="true"
					className="shrink-0 select-none bg-[#f8f7f2] px-3 py-2 text-right text-[#9aa19c]"
				>
					{lines.map((_, index) => `${index + 1}\n`).join("")}
				</pre>
				<pre
					className={`min-w-0 flex-1 px-3 py-2 ${
						softWrap ? "whitespace-pre-wrap break-words" : "whitespace-pre"
					}`}
				>
					{content}
				</pre>
			</div>
		</div>
	);
}

function SkeletonPreview({
	fileName,
	signedUrl,
}: {
	fileName: string;
	signedUrl: string;
}) {
	const isImageHint = IMAGE_EXTENSIONS.has(extractExtension(fileName));
	return (
		<div className="flex h-full flex-col items-center justify-center gap-3 text-[#7a817a] text-sm">
			{isImageHint ? (
				<FileImage aria-hidden="true" size={36} />
			) : (
				<FileText aria-hidden="true" size={36} />
			)}
			<p>No preview available for {fileName}.</p>
			<a
				className="inline-flex items-center gap-1.5 rounded border border-[#cbd736] bg-[#f5f8df] px-3 py-1.5 text-[#315419] text-xs transition-colors hover:bg-[#eaf4cf]"
				download
				href={signedUrl}
				rel="noreferrer"
				target="_blank"
			>
				<DownloadSimple aria-hidden="true" size={14} />
				Download
			</a>
		</div>
	);
}

function extractExtension(fileName: string) {
	const dot = fileName.lastIndexOf(".");
	if (dot === -1 || dot === fileName.length - 1) {
		return "";
	}
	return fileName.slice(dot + 1).toLowerCase();
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
