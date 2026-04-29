"use client";

import { X } from "@phosphor-icons/react";

import { CandidatesTable } from "./candidates-table";
import { FilePreview } from "./file-preview";

export type ViewerTab =
	| { kind: "candidates"; id: "candidates" }
	| {
			artifactId: string;
			fileName: string;
			id: string;
			kind: "file";
			signedUrl: string | null;
	  };

type CandidateRow = {
	id: string;
	method?: string | null;
	organism?: string | null;
	rank: number;
	resolutionAngstrom?: number | null;
	title: string;
};

type ScoreRow = {
	candidateId: string;
	label: string | null;
	scorer: string;
	unit: string | null;
	value: number | null;
};

type ViewerTabsProps = {
	activeTabId: string | null;
	candidates: CandidateRow[];
	candidateScores: ScoreRow[];
	onClose: (tabId: string) => void;
	onOpenCandidate?: (candidateId: string) => void;
	onSelect: (tabId: string) => void;
	tabs: ViewerTab[];
};

export function ViewerTabs({
	activeTabId,
	candidates,
	candidateScores,
	onClose,
	onOpenCandidate,
	onSelect,
	tabs,
}: ViewerTabsProps) {
	const hasCandidates = candidates.length > 0;
	const allTabs: ViewerTab[] = hasCandidates
		? [{ id: "candidates", kind: "candidates" }, ...tabs]
		: tabs;
	const activeTab = allTabs.find((tab) => tab.id === activeTabId) ?? null;

	if (allTabs.length === 0) {
		return (
			<section className="flex h-full items-center justify-center text-[#7a817a] text-sm">
				Select a file from the right panel, or wait for the agent to produce
				candidates.
			</section>
		);
	}

	return (
		<section className="flex h-full min-h-0 flex-col">
			<div
				className="flex shrink-0 items-center gap-1 overflow-x-auto border-[#e5e2d9] border-b px-2"
				role="tablist"
			>
				{allTabs.map((tab) => {
					const active = tab.id === activeTabId;
					const label = tab.kind === "candidates" ? "Candidates" : tab.fileName;
					return (
						<div className="flex items-center" key={tab.id}>
							<button
								aria-selected={active}
								className={`px-3 py-2 text-sm transition-colors ${
									active
										? "border-[#cbd736] border-b-2 text-[#17211e]"
										: "text-[#5a6360] hover:text-[#26332e]"
								}`}
								onClick={() => onSelect(tab.id)}
								role="tab"
								type="button"
							>
								{label}
							</button>
							{tab.kind === "file" ? (
								<button
									aria-label={`Close ${tab.fileName}`}
									className="ml-1 rounded p-1 text-[#7a817a] hover:bg-[#f0efe8]"
									onClick={() => onClose(tab.id)}
									type="button"
								>
									<X aria-hidden="true" size={12} />
								</button>
							) : null}
						</div>
					);
				})}
			</div>
			<div className="min-h-0 flex-1 overflow-hidden">
				{activeTab?.kind === "candidates" ? (
					<CandidatesTable
						candidateScores={candidateScores}
						candidates={candidates}
						onOpenCandidate={onOpenCandidate}
					/>
				) : activeTab?.kind === "file" ? (
					<FilePreview
						artifactId={activeTab.artifactId}
						fileName={activeTab.fileName}
						signedUrl={activeTab.signedUrl}
					/>
				) : (
					<div className="flex h-full items-center justify-center text-[#7a817a] text-sm">
						Select a tab.
					</div>
				)}
			</div>
		</section>
	);
}
