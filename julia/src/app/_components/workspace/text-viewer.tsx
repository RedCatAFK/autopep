"use client";

import { useEffect, useState } from "react";

import type { ViewerArtifact } from "./molstar-viewer";

const MAX_PREVIEW_BYTES = 256 * 1024;

type TextViewerProps = {
	artifact: ViewerArtifact;
};

export function TextViewer({ artifact }: TextViewerProps) {
	const [state, setState] = useState<"loading" | "ready" | "error">("loading");
	const [content, setContent] = useState<string>("");
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let canceled = false;
		const url = artifact.viewerUrl;
		if (!url) {
			setState("error");
			setError("No viewer URL");
			return () => {
				canceled = true;
			};
		}
		setState("loading");
		setError(null);
		fetch(url)
			.then(async (response) => {
				if (!response.ok) {
					throw new Error(`Failed to load (${response.status})`);
				}
				const text = await response.text();
				if (canceled) return;
				const truncated =
					text.length > MAX_PREVIEW_BYTES
						? `${text.slice(0, MAX_PREVIEW_BYTES)}\n\n... <truncated ${text.length - MAX_PREVIEW_BYTES} bytes>`
						: text;
				setContent(formatIfJson(artifact.filename, truncated));
				setState("ready");
			})
			.catch((caught) => {
				if (canceled) return;
				setError(caught instanceof Error ? caught.message : "Load failed");
				setState("error");
			});
		return () => {
			canceled = true;
		};
	}, [artifact.viewerUrl, artifact.filename]);

	return (
		<div className="text-viewer">
			{state === "loading" ? (
				<div className="viewer-state">
					<strong>Loading file</strong>
					<p>{artifact.filename}</p>
				</div>
			) : state === "error" ? (
				<div className="viewer-state error">
					<strong>Could not load file</strong>
					<p>{error ?? "Unknown error"}</p>
				</div>
			) : (
				<pre className="text-viewer-pre">
					<code>{content}</code>
				</pre>
			)}
		</div>
	);
}

function formatIfJson(filename: string, text: string): string {
	if (!filename.toLowerCase().endsWith(".json")) return text;
	try {
		return JSON.stringify(JSON.parse(text), null, 2);
	} catch {
		return text;
	}
}
