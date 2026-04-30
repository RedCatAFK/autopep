"use client";

import {
	ArrowClockwise,
	ArrowsOutSimple,
	DownloadSimple,
	GearSix,
	Selection,
} from "@phosphor-icons/react";
import { type ComponentType, useRef, useState } from "react";

import { MolstarViewer, type ProteinSelection } from "./molstar-viewer";

export type { ProteinSelection } from "./molstar-viewer";

export type StageArtifact = {
	id: string;
	label: string;
	name: string;
	url: string | null;
};

export type StageCandidate = {
	id: string;
	title: string;
};

type StageViewerProps = {
	artifactId?: string | null;
	candidateId?: string | null;
	label: string;
	onProteinSelection?: (selection: ProteinSelection) => void;
	url: string | null;
};

type MolstarStageProps = {
	artifact: StageArtifact | null;
	candidate: StageCandidate | null;
	onProteinSelection: (selection: ProteinSelection) => void;
	viewerComponent?: ComponentType<StageViewerProps>;
};

export function MolstarStage({
	artifact,
	candidate,
	onProteinSelection,
	viewerComponent: Viewer = MolstarViewer,
}: MolstarStageProps) {
	const stageRef = useRef<HTMLElement>(null);
	const [settingsOpen, setSettingsOpen] = useState(false);
	const [selection, setSelection] = useState<ProteinSelection | null>(null);
	const label = artifact?.label ?? artifact?.name ?? "Awaiting CIF";

	const resetCamera = () => {
		window.dispatchEvent(
			new CustomEvent("autopep:viewer-action", {
				detail: { action: "Reset" },
			}),
		);
	};

	const fullscreen = () => {
		void stageRef.current?.requestFullscreen?.();
	};

	const handleSelection = (nextSelection: ProteinSelection) => {
		setSelection(nextSelection);
		onProteinSelection(nextSelection);
	};

	return (
		<section
			className="relative flex min-h-[520px] min-w-0 flex-col overflow-hidden bg-[#f8f7f2] lg:min-h-0"
			ref={stageRef}
		>
			<header className="flex flex-wrap items-start justify-end gap-4 px-5 pt-5 pb-3 md:px-6">
				<div className="flex items-center gap-1 rounded-md border border-[#e1ded4] bg-[#fffef9] p-1">
					<StageAction
						icon={<ArrowsOutSimple aria-hidden="true" size={18} />}
						label="Fullscreen viewer"
						onClick={fullscreen}
					/>
					{artifact?.url ? (
						<a
							aria-label="Download structure"
							className="flex size-8 items-center justify-center rounded-md text-[#394541] transition-colors duration-200 hover:bg-[#f0efe8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 active:translate-y-px"
							href={artifact.url}
							rel="noreferrer"
							target="_blank"
							title="Download structure"
						>
							<DownloadSimple aria-hidden="true" size={18} />
						</a>
					) : (
						<StageAction
							disabled
							icon={<DownloadSimple aria-hidden="true" size={18} />}
							label="Download structure"
							onClick={() => undefined}
						/>
					)}
					<StageAction
						icon={<ArrowClockwise aria-hidden="true" size={18} />}
						label="Reset camera"
						onClick={resetCamera}
					/>
					<StageAction
						icon={<GearSix aria-hidden="true" size={18} />}
						label="Viewer settings"
						onClick={() => setSettingsOpen((value) => !value)}
					/>
				</div>
			</header>

			<div className="relative min-h-[430px] flex-1 px-4 pb-5 md:px-6 md:pb-6 lg:min-h-0">
				<div className="relative h-full min-h-[430px] overflow-hidden rounded-lg border border-[#e2dfd5] bg-[#fffef9] shadow-[0_20px_80px_-62px_rgba(25,39,33,0.9)] lg:min-h-0">
					{artifact ? (
						<>
							<Viewer
								artifactId={artifact.id}
								candidateId={candidate?.id ?? null}
								label={label}
								onProteinSelection={handleSelection}
								url={artifact.url}
							/>
							<div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_45%,rgba(33,126,104,0.04),transparent_40%)]" />
						</>
					) : (
						<div className="flex h-full items-center justify-center text-[#7a817a] text-sm">
							Select a candidate or open a structure file.
						</div>
					)}
				</div>

				{selection ? (
					<div className="absolute bottom-8 left-8 max-w-[calc(100%-4rem)] rounded-md border border-[#d6dec0] bg-[#fffef9]/95 px-3 py-2 text-[#315419] text-xs shadow-[0_16px_44px_-32px_rgba(25,39,33,0.55)] backdrop-blur">
						<div className="flex items-center gap-2">
							<Selection aria-hidden="true" size={15} />
							<span className="truncate">{selection.label}</span>
						</div>
					</div>
				) : null}

				{settingsOpen ? (
					<div className="absolute top-2 right-8 w-64 rounded-md border border-[#d7d4c9] bg-[#fffef9] p-3 text-[#4c5752] text-sm shadow-[0_22px_70px_-48px_rgba(25,39,33,0.75)]">
						<p className="font-medium text-[#26332e]">Viewer settings</p>
						<p className="mt-2 text-xs leading-5">
							Mol* controls stay compact so the structure remains the largest
							surface in the workspace.
						</p>
					</div>
				) : null}
			</div>
		</section>
	);
}

function StageAction({
	disabled = false,
	icon,
	label,
	onClick,
}: {
	disabled?: boolean;
	icon: React.ReactNode;
	label: string;
	onClick: () => void;
}) {
	return (
		<button
			aria-label={label}
			className="flex size-8 items-center justify-center rounded-md text-[#394541] transition-colors duration-200 hover:bg-[#f0efe8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-45"
			disabled={disabled}
			onClick={onClick}
			title={label}
			type="button"
		>
			{icon}
		</button>
	);
}
