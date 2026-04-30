"use client";

import { FilePlus2, Files } from "lucide-react";

import type { ViewerArtifact } from "./molstar-viewer";

export type WorkspaceArtifact = ViewerArtifact & {
	runId?: string | null;
	sizeBytes?: number | null;
	createdAt?: string | Date | null;
};

type FilePanelProps = {
	artifacts: WorkspaceArtifact[];
	selectedArtifactId?: string | null;
	onSelectArtifact: (artifact: WorkspaceArtifact) => void;
	onAddContext: (artifact: WorkspaceArtifact) => void;
	disabled?: boolean;
};

export function FilePanel({
	artifacts,
	selectedArtifactId,
	onSelectArtifact,
	onAddContext,
	disabled,
}: FilePanelProps) {
	return (
		<aside aria-label="Files and artifacts" className="file-panel">
			<div className="panel-header">
				<div>
					<p className="eyebrow">Files</p>
					<h2>Artifacts</h2>
				</div>
				<span className="count-badge">{artifacts.length}</span>
			</div>
			<div className="artifact-list">
				{artifacts.length === 0 ? (
					<div className="empty-panel">
						<Files aria-hidden="true" size={18} />
						<p>Run outputs will appear here.</p>
					</div>
				) : (
					artifacts.map((artifact) => (
						<div
							className={`artifact-row ${
								selectedArtifactId === artifact.id ? "selected" : ""
							}`}
							key={artifact.id}
						>
							<button
								className="artifact-main"
								onClick={() => onSelectArtifact(artifact)}
								type="button"
							>
								<span className="artifact-name">{artifact.filename}</span>
								<span className="artifact-meta">
									{artifact.kind ?? "artifact"}
									{artifact.sizeBytes
										? ` · ${formatBytes(artifact.sizeBytes)}`
										: ""}
								</span>
							</button>
							<button
								aria-label={`Add ${artifact.filename} to context`}
								className="icon-button"
								disabled={disabled}
								onClick={() => onAddContext(artifact)}
								type="button"
							>
								<FilePlus2 aria-hidden="true" size={16} />
							</button>
						</div>
					))
				)}
			</div>
		</aside>
	);
}

function formatBytes(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
