"use client";

import {
	ArrowClockwise,
	ArrowRight,
	ArrowsOutSimple,
	Atom,
	BookOpen,
	BoundingBox,
	CaretRight,
	Check,
	CircleNotch,
	Cube,
	DotsThreeVertical,
	Eye,
	FileText,
	FolderOpen,
	GearSix,
	HandPalm,
	HouseLine,
	Lightning,
	MagnifyingGlass,
	Paperclip,
	PaperPlaneTilt,
	Question,
	ShareNetwork,
	SlidersHorizontal,
	Sparkle,
	UserCircle,
} from "@phosphor-icons/react";
import type { ReactNode } from "react";

export type WorkspaceCandidate = {
	id: string;
	method: string | null;
	organism: string | null;
	proteinaReady: boolean;
	rank: number;
	rcsbId: string;
	relevanceScore: number;
	resolutionAngstrom: number | null;
	selectionRationale: string;
	title: string;
};

export type WorkspaceEvent = {
	detail: string | null;
	id: string;
	sequence: number;
	title: string;
	type: string;
};

type WorkspaceShellProps = {
	artifactLabel: string;
	candidates: WorkspaceCandidate[];
	children: ReactNode;
	events: WorkspaceEvent[];
	isCreatingRun: boolean;
	isLoadingWorkspace: boolean;
	onRefresh: () => void;
	onStartExample: (goal: string) => void;
	projectGoal: string;
	runStatus: string | null;
	selectedCandidate: WorkspaceCandidate | null;
	targetName: string;
};

const spikeGoal = "Design a protein binder for SARS-CoV-2 spike RBD";
const proteaseGoal = "Design a protein binder for 3CL-protease";

const statusCopy: Record<string, { detail: string; label: string }> = {
	canceled: {
		detail: "This run was stopped before a CIF could be prepared.",
		label: "Run canceled",
	},
	failed: {
		detail: "Autopep hit an issue while preparing the target.",
		label: "Needs attention",
	},
	queued: {
		detail: "Autopep is waiting for the retrieval worker.",
		label: "Queued for research",
	},
	running: {
		detail: "Searching structures, checking evidence, and preparing CIF files.",
		label: "Preparing target",
	},
	succeeded: {
		detail: "We found a relevant structure and prepared it for design.",
		label: "Target structure ready",
	},
};

const eventTypeLabels: Record<string, string> = {
	downloading_cif: "Downloading CIF",
	normalizing_target: "Understanding target",
	preparing_cif: "Preparing CIF",
	ranking_candidates: "Ranking matches",
	ready_for_proteina: "Ready for Proteina",
	searching_literature: "Reading literature",
	searching_structures: "Finding structures",
	uploading_artifact: "Saving artifact",
};

export function WorkspaceShell({
	artifactLabel,
	candidates,
	children,
	events,
	isCreatingRun,
	isLoadingWorkspace,
	onRefresh,
	onStartExample,
	projectGoal,
	runStatus,
	selectedCandidate,
	targetName,
}: WorkspaceShellProps) {
	const status = runStatus ? statusCopy[runStatus] : null;
	const hasRun = Boolean(runStatus);
	const isActive = runStatus === "queued" || runStatus === "running";
	const hasArtifact = artifactLabel !== "No CIF artifact yet";
	const structureReady = Boolean(selectedCandidate);
	const evidenceReady =
		events.some((event) => event.type === "searching_literature") ||
		runStatus === "succeeded";
	const designInputReady = Boolean(
		selectedCandidate?.proteinaReady && hasArtifact,
	);
	const latestEvents = events.slice(-4).reverse();

	return (
		<main className="min-h-[100dvh] bg-[#f8f7f2] text-[#17211e]">
			<header className="sticky top-0 z-20 flex h-16 items-center justify-between border-[#e5e2d9] border-b bg-[#fffef9]/95 px-4 backdrop-blur md:px-5">
				<div className="flex items-center gap-3">
					<AutopepMark />
					<p className="font-semibold text-[21px] tracking-[-0.02em]">
						Autopep
					</p>
				</div>
				<div className="flex items-center gap-2">
					<IconButton ariaLabel="Help" title="Help">
						<Question size={18} />
					</IconButton>
					<div className="flex size-9 items-center justify-center rounded-full border border-[#e5e2d9] bg-[#f6f4ee] font-medium text-[#2b332f] text-xs">
						<UserCircle size={18} weight="duotone" />
					</div>
				</div>
			</header>

			<div className="grid min-h-[calc(100dvh-4rem)] grid-cols-1 md:grid-cols-[72px_minmax(0,1fr)] xl:grid-cols-[72px_minmax(330px,390px)_minmax(0,1fr)_minmax(320px,370px)]">
				<aside className="flex min-h-16 items-center justify-between border-[#e5e2d9] border-b bg-[#fbfaf6] px-3 md:min-h-0 md:flex-col md:border-r md:border-b-0 md:px-0 md:py-5">
					<nav className="flex items-center gap-2 md:flex-col md:gap-4">
						<RailButton active label="Home">
							<HouseLine size={21} weight="fill" />
						</RailButton>
						<RailButton label="Projects">
							<FolderOpen size={21} />
						</RailButton>
						<RailButton label="Graph">
							<ShareNetwork size={21} />
						</RailButton>
						<RailButton label="Notebook">
							<BookOpen size={21} />
						</RailButton>
						<RailButton label="Settings">
							<GearSix size={21} />
						</RailButton>
					</nav>
					<button
						aria-label="Collapse navigation"
						className="hidden size-9 items-center justify-center rounded-md text-[#69716b] transition hover:bg-[#efeee6] md:flex"
						type="button"
					>
						<CaretRight size={18} />
					</button>
				</aside>

				<aside className="border-[#e5e2d9] border-b bg-[#fbfaf6] p-5 md:col-start-2 xl:col-start-auto xl:border-r xl:border-b-0">
					<section>
						<p className="font-semibold text-[17px] tracking-[-0.01em]">
							What would you like to design?
						</p>
						<p className="mt-1 text-[#6c726c] text-sm">
							Describe your goal in plain English.
						</p>

						<div className="mt-5 rounded-lg border border-[#d7d4c9] bg-[#fffef9] p-4 shadow-[0_16px_50px_-42px_rgba(25,39,33,0.7)]">
							<p className="min-h-[72px] text-[#27322f] text-xl leading-8 tracking-[-0.02em]">
								{projectGoal || spikeGoal}
							</p>
							<div className="mt-6 flex items-center justify-between gap-3">
								<div className="flex items-center gap-3 text-[#44504b]">
									<button
										aria-label="Attach research context"
										className="rounded-md p-1.5 transition hover:bg-[#f0f0e9]"
										type="button"
									>
										<Paperclip size={19} />
									</button>
									<button
										aria-label="Prompt settings"
										className="rounded-md p-1.5 transition hover:bg-[#f0f0e9]"
										type="button"
									>
										<SlidersHorizontal size={19} />
									</button>
								</div>
								<button
									aria-label="Start target retrieval"
									className="flex size-11 items-center justify-center rounded-lg bg-[#dfe94c] text-[#1d342e] transition hover:bg-[#d4e337] active:translate-y-[1px] disabled:cursor-not-allowed disabled:opacity-60"
									disabled={isCreatingRun}
									onClick={() => onStartExample(spikeGoal)}
									title="Start target retrieval"
									type="button"
								>
									<PaperPlaneTilt size={22} weight="fill" />
								</button>
							</div>
						</div>

						<div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-1">
							<ExampleButton
								disabled={isCreatingRun}
								label="SARS-CoV-2 spike RBD"
								onClick={() => onStartExample(spikeGoal)}
							/>
							<ExampleButton
								disabled={isCreatingRun}
								label="3CL-protease"
								onClick={() => onStartExample(proteaseGoal)}
							/>
						</div>
					</section>

					<section className="mt-7">
						<div className="flex items-center gap-2">
							<Sparkle size={17} weight="fill" />
							<p className="font-medium text-sm">Autopep Assistant</p>
						</div>
						<div className="mt-4 rounded-lg border border-[#d7d4c9] bg-[#fffef9] p-4">
							<div className="flex gap-4">
								<ProgressGlyph
									active={isActive || isLoadingWorkspace}
									done={runStatus === "succeeded"}
								/>
								<div>
									<p className="font-semibold text-[#16705f] text-sm">
										{status?.label ?? "Ready to prepare a target"}
									</p>
									<p className="mt-1 text-[#656f68] text-sm leading-6">
										{status?.detail ??
											"Choose an example to search known structures and evidence."}
									</p>
								</div>
							</div>
						</div>
					</section>

					<section className="mt-7 rounded-lg border border-[#d7d4c9] bg-[#fffef9] p-4">
						{selectedCandidate ? (
							<div className="grid grid-cols-[104px_minmax(0,1fr)] items-center gap-4">
								<MiniStructure />
								<div className="min-w-0">
									<p className="text-[#59625c] text-xs">Best match found:</p>
									<p className="mt-1 line-clamp-2 font-medium text-[#202b27] leading-6">
										{selectedCandidate.title}
									</p>
									<div className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-[#eaf4cf] px-2.5 py-1 font-medium text-[#315419] text-xs">
										Ready for design <Check size={13} weight="bold" />
									</div>
								</div>
							</div>
						) : (
							<div className="grid grid-cols-[86px_minmax(0,1fr)] items-center gap-4">
								<MiniStructure muted />
								<div>
									<p className="font-medium text-[#202b27]">
										No match selected yet
									</p>
									<p className="mt-1 text-[#656f68] text-sm leading-6">
										Ranked RCSB structures appear here once the worker finishes.
									</p>
								</div>
							</div>
						)}
					</section>

					<section className="mt-7">
						<p className="font-semibold text-sm">What's ready</p>
						<div className="mt-3 grid grid-cols-3 gap-2">
							<ReadinessChip
								icon={<Cube size={17} />}
								label="Structure"
								ready={structureReady}
							/>
							<ReadinessChip
								icon={<FileText size={17} />}
								label="Evidence"
								ready={evidenceReady}
							/>
							<ReadinessChip
								icon={<Lightning size={17} />}
								label="Design input"
								ready={designInputReady}
							/>
						</div>
					</section>
				</aside>

				<section className="flex min-w-0 flex-col bg-[#f8f7f2] xl:border-[#e5e2d9] xl:border-r">
					<div className="flex flex-wrap items-start justify-between gap-4 p-5 md:p-6">
						<div className="flex min-w-0 items-start gap-4">
							<StatusBadge
								active={isActive}
								done={hasArtifact}
								error={runStatus === "failed"}
							/>
							<div className="min-w-0">
								<h1 className="font-semibold text-[20px] tracking-[-0.02em]">
									{status?.label ?? "Start with a target structure"}
								</h1>
								<p className="mt-1 max-w-xl text-[#6a716b] text-sm leading-6">
									{hasArtifact
										? `Prepared CIF selected: ${artifactLabel}`
										: "Autopep will search RCSB and literature, rank relevant structures, and stage a CIF for downstream design."}
								</p>
							</div>
						</div>
						<div className="flex items-center gap-2 rounded-lg border border-[#e1ded4] bg-[#fffef9] p-1">
							<IconButton
								ariaLabel="Refresh workspace"
								onClick={onRefresh}
								title="Refresh"
							>
								<ArrowClockwise size={18} />
							</IconButton>
							<IconButton ariaLabel="Fit viewer" title="Fit viewer">
								<ArrowsOutSimple size={18} />
							</IconButton>
							<IconButton ariaLabel="More options" title="More options">
								<DotsThreeVertical size={18} weight="bold" />
							</IconButton>
						</div>
					</div>

					<div className="relative min-h-[480px] flex-1 px-4 pb-5 md:px-6 md:pb-6">
						<div className="relative h-full min-h-[480px] overflow-hidden rounded-lg border border-[#e2dfd5] bg-[#fffef9] shadow-[0_20px_80px_-62px_rgba(25,39,33,0.9)]">
							{children}
							<div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_45%,rgba(33,126,104,0.04),transparent_40%)]" />
						</div>

						<div className="absolute right-1/2 bottom-9 z-10 flex translate-x-1/2 items-center gap-1 rounded-lg border border-[#e1ded4] bg-[#fffef9]/95 p-1.5 shadow-[0_18px_60px_-38px_rgba(25,39,33,0.55)] backdrop-blur">
							<StageTool active label="Select">
								<BoundingBox size={18} />
							</StageTool>
							<StageTool label="Pan">
								<HandPalm size={18} />
							</StageTool>
							<StageTool label="Reset">
								<ArrowClockwise size={18} />
							</StageTool>
							<StageTool label="View">
								<Eye size={18} />
							</StageTool>
							<StageTool label="Annotate">
								<Sparkle size={18} />
							</StageTool>
						</div>
					</div>
				</section>

				<aside className="border-[#e5e2d9] border-t bg-[#fbfaf6] p-5 md:col-start-2 xl:col-start-auto xl:border-t-0">
					<div className="flex items-center justify-between gap-3">
						<div>
							<p className="font-semibold text-sm">Your design journey</p>
							<p className="mt-1 text-[#72776f] text-xs">
								Current target: {targetName}
							</p>
						</div>
						<button
							aria-label="Continue to binder design"
							className="flex size-9 items-center justify-center rounded-md border border-[#d7d4c9] bg-[#fffef9] transition hover:border-[#cbd736] active:translate-y-[1px]"
							type="button"
						>
							<ArrowRight size={18} />
						</button>
					</div>

					<div className="relative mt-5 space-y-3">
						<div className="absolute top-4 bottom-4 left-4 w-px bg-[#d9e34a]" />
						<JourneyStep
							done={hasRun}
							index={1}
							kicker="We analyze your goal"
							state={hasRun ? "done" : "active"}
							title="Understand target"
							visual="inspect"
						/>
						<JourneyStep
							done={candidates.length > 0}
							index={2}
							kicker="We search known data"
							state={
								candidates.length > 0 ? "done" : hasRun ? "active" : "idle"
							}
							title="Find structures"
							visual="rank"
						/>
						<JourneyStep
							done={hasArtifact}
							index={3}
							kicker="We build your target"
							state={hasArtifact ? "done" : isActive ? "active" : "idle"}
							title="Prepare target"
							visual="prepare"
						/>
						<JourneyStep
							done={false}
							index={4}
							kicker="We create and refine binders"
							state={designInputReady ? "active" : "idle"}
							title="Design binder"
							visual="handoff"
						/>
					</div>

					<div className="mt-5 rounded-lg border border-[#dfe8b3] bg-[#f2f7d7] p-3">
						<div className="flex items-center justify-between gap-3">
							<div className="min-w-0">
								<p className="font-medium text-[#53641e] text-xs">
									Next up:{" "}
									<span className="text-[#27322f]">
										{designInputReady ? "Design binder" : "Prepare target"}
									</span>
								</p>
								<p className="mt-1 text-[#70785e] text-xs leading-5">
									{designInputReady
										? "The CIF is ready for sequence generation and scoring."
										: "Once the target is ready, binder design can begin."}
								</p>
							</div>
							<div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-[#fffef9]">
								<ArrowRight size={16} />
							</div>
						</div>
					</div>

					<section className="mt-6">
						<p className="font-semibold text-sm">Ranked structures</p>
						<div className="mt-3 space-y-2">
							{candidates.length === 0 ? (
								<p className="rounded-lg border border-[#e2dfd5] bg-[#fffef9] p-3 text-[#69716b] text-sm leading-6">
									Candidates will appear after Autopep ranks the RCSB results.
								</p>
							) : (
								candidates
									.slice(0, 3)
									.map((candidate) => (
										<CandidateRow candidate={candidate} key={candidate.id} />
									))
							)}
						</div>
					</section>

					<section className="mt-6">
						<div className="flex items-center justify-between gap-3">
							<p className="font-semibold text-sm">Research trace</p>
							<p className="font-mono text-[#747b74] text-[11px]">
								{runStatus ?? "no-run"}
							</p>
						</div>
						<div className="mt-3 space-y-2">
							{latestEvents.length === 0 ? (
								<p className="rounded-lg border border-[#e2dfd5] bg-[#fffef9] p-3 text-[#69716b] text-sm leading-6">
									Live agent events will sync here as the worker writes
									progress.
								</p>
							) : (
								latestEvents.map((event) => (
									<div
										className="rounded-lg border border-[#e2dfd5] bg-[#fffef9] p-3"
										key={event.id}
									>
										<div className="flex items-center justify-between gap-3">
											<p className="font-medium text-[#24302b] text-sm">
												{event.title}
											</p>
											<p className="font-mono text-[#7b817a] text-[11px]">
												{event.sequence.toString().padStart(2, "0")}
											</p>
										</div>
										<p className="mt-1 text-[#69716b] text-xs">
											{eventTypeLabels[event.type] ?? event.type}
										</p>
										{event.detail ? (
											<p className="mt-2 text-[#69716b] text-xs leading-5">
												{event.detail}
											</p>
										) : null}
									</div>
								))
							)}
						</div>
					</section>
				</aside>
			</div>
		</main>
	);
}

function AutopepMark() {
	return (
		<div
			aria-hidden
			className="relative size-8 rounded-md border border-[#cfd8cc] bg-[#fffef9]"
		>
			<div className="absolute inset-[6px] bg-[#0b715f] [clip-path:polygon(25%_5%,75%_5%,100%_50%,75%_95%,25%_95%,0_50%)]" />
			<div className="absolute inset-[9px] bg-[#fffef9] [clip-path:polygon(25%_5%,75%_5%,100%_50%,75%_95%,25%_95%,0_50%)]" />
			<div className="absolute right-[5px] bottom-[5px] size-2 rounded-full bg-[#dfe94c]" />
		</div>
	);
}

function RailButton({
	active,
	children,
	label,
}: {
	active?: boolean;
	children: ReactNode;
	label: string;
}) {
	return (
		<button
			aria-label={label}
			className={`flex size-10 items-center justify-center rounded-lg transition active:translate-y-[1px] ${
				active
					? "bg-[#dfe94c] text-[#1d332e]"
					: "text-[#66706a] hover:bg-[#efeee6] hover:text-[#24302b]"
			}`}
			title={label}
			type="button"
		>
			{children}
		</button>
	);
}

function IconButton({
	ariaLabel,
	children,
	onClick,
	title,
}: {
	ariaLabel: string;
	children: ReactNode;
	onClick?: () => void;
	title: string;
}) {
	return (
		<button
			aria-label={ariaLabel}
			className="flex size-8 items-center justify-center rounded-md text-[#394541] transition hover:bg-[#f0efe8] active:translate-y-[1px]"
			onClick={onClick}
			title={title}
			type="button"
		>
			{children}
		</button>
	);
}

function ExampleButton({
	disabled,
	label,
	onClick,
}: {
	disabled: boolean;
	label: string;
	onClick: () => void;
}) {
	return (
		<button
			className="flex items-center justify-between gap-3 rounded-lg border border-[#dcd8cf] bg-[#fffef9] px-3 py-2.5 text-left text-[#34403b] text-sm transition hover:border-[#cbd736] active:translate-y-[1px] disabled:cursor-not-allowed disabled:opacity-60"
			disabled={disabled}
			onClick={onClick}
			type="button"
		>
			<span>{label}</span>
			<PaperPlaneTilt className="shrink-0" size={16} />
		</button>
	);
}

function ProgressGlyph({ active, done }: { active: boolean; done: boolean }) {
	if (done) {
		return (
			<div className="flex size-12 shrink-0 items-center justify-center rounded-full border border-[#d4df4b] bg-[#fbfff0] text-[#1e735f]">
				<Check size={22} weight="bold" />
			</div>
		);
	}

	return (
		<div className="relative size-12 shrink-0 rounded-full border-[#e8e9d7] border-[6px]">
			<div
				className={`absolute inset-[-6px] rounded-full border-[#dfe94c] border-[6px] border-r-transparent ${
					active ? "animate-spin" : ""
				}`}
			/>
		</div>
	);
}

function MiniStructure({ muted = false }: { muted?: boolean }) {
	return (
		<div
			className={`relative h-[92px] overflow-hidden rounded-lg border ${
				muted
					? "border-[#e2dfd5] bg-[#f5f3ed]"
					: "border-[#d7d4c9] bg-[#edf4ed]"
			}`}
		>
			<div className="absolute inset-2 rounded-full bg-[#dfe8e1]" />
			<div
				className={`absolute top-5 left-5 h-10 w-16 rounded-[45%] border-4 ${
					muted ? "border-[#aeb5ad]" : "border-[#087a66]"
				}`}
			/>
			<div
				className={`absolute right-5 bottom-5 h-9 w-14 rounded-[45%] border-4 ${
					muted ? "border-[#c2c7c1]" : "border-[#119079]"
				}`}
			/>
			<div
				className={`absolute top-10 left-8 h-8 w-20 rounded-[55%] border-4 border-t-transparent ${
					muted ? "border-[#bbc1ba]" : "border-[#087a66]"
				}`}
			/>
		</div>
	);
}

function ReadinessChip({
	icon,
	label,
	ready,
}: {
	icon: ReactNode;
	label: string;
	ready: boolean;
}) {
	return (
		<div className="min-h-[68px] rounded-lg border border-[#e0ddd3] bg-[#fffef9] p-2.5">
			<div className="flex items-center gap-2 text-[#35403b]">
				{icon}
				<p className="min-w-0 truncate text-[11px]">{label}</p>
			</div>
			<div className="mt-2 flex justify-end">
				{ready ? (
					<Check className="text-[#27845d]" size={15} weight="bold" />
				) : (
					<div className="size-3 rounded-full border border-[#ccd0c6]" />
				)}
			</div>
		</div>
	);
}

function StatusBadge({
	active,
	done,
	error,
}: {
	active: boolean;
	done: boolean;
	error: boolean;
}) {
	return (
		<div
			className={`flex size-12 shrink-0 items-center justify-center rounded-full border ${
				error
					? "border-[#efc7bd] bg-[#fff7f4] text-[#9c3d2d]"
					: done
						? "border-[#d4df4b] bg-[#fcfff0] text-[#1e735f]"
						: "border-[#dbe0c2] bg-[#fffef9] text-[#62705f]"
			}`}
		>
			{error ? (
				<Question size={22} />
			) : done ? (
				<Check size={22} weight="bold" />
			) : active ? (
				<CircleNotch className="animate-spin" size={22} />
			) : (
				<Atom size={22} weight="duotone" />
			)}
		</div>
	);
}

function StageTool({
	active,
	children,
	label,
}: {
	active?: boolean;
	children: ReactNode;
	label: string;
}) {
	return (
		<button
			aria-label={label}
			className={`flex size-9 items-center justify-center rounded-md transition active:translate-y-[1px] ${
				active
					? "bg-[#e8ef75] text-[#21352f]"
					: "text-[#3d4844] hover:bg-[#f0efe8]"
			}`}
			title={label}
			type="button"
		>
			{children}
		</button>
	);
}

function JourneyStep({
	done,
	index,
	kicker,
	state,
	title,
	visual,
}: {
	done: boolean;
	index: number;
	kicker: string;
	state: "active" | "done" | "idle";
	title: string;
	visual: "handoff" | "inspect" | "prepare" | "rank";
}) {
	return (
		<div className="relative pl-9">
			<div
				className={`absolute top-1 left-0 z-[1] flex size-8 items-center justify-center rounded-full font-semibold text-sm ${
					state === "active"
						? "bg-[#dfe94c] text-[#304018]"
						: done
							? "bg-[#dfe94c] text-[#304018]"
							: "bg-[#ecebe4] text-[#565d57]"
				}`}
			>
				{index}
			</div>
			<div
				className={`rounded-lg border bg-[#fffef9] p-4 ${
					state === "active" ? "border-[#d4df4b]" : "border-[#e2dfd5]"
				}`}
			>
				<div className="flex items-start justify-between gap-3">
					<div>
						<p className="font-medium text-[#26312d]">{title}</p>
						<p className="mt-1 text-[#71776f] text-xs">{kicker}</p>
					</div>
					{done ? (
						<div className="flex size-6 shrink-0 items-center justify-center rounded-full bg-[#2d995e] text-white">
							<Check size={14} weight="bold" />
						</div>
					) : state === "active" ? (
						<CircleNotch
							className="shrink-0 animate-spin text-[#c8d334]"
							size={24}
						/>
					) : null}
				</div>
				<JourneyVisual visual={visual} />
			</div>
		</div>
	);
}

function JourneyVisual({
	visual,
}: {
	visual: "handoff" | "inspect" | "prepare" | "rank";
}) {
	if (visual === "rank") {
		return (
			<div className="mt-4 grid grid-cols-3 gap-2">
				<MiniCell muted />
				<MiniCell active />
				<MiniCell muted />
			</div>
		);
	}

	if (visual === "prepare") {
		return (
			<div className="mt-4 flex items-center justify-center gap-4">
				<MiniCell active />
				<ArrowRight className="text-[#858b83]" size={18} />
				<MiniCell active compact />
			</div>
		);
	}

	if (visual === "handoff") {
		return (
			<div className="mt-4 flex items-center justify-center gap-2">
				<MiniCell active />
				<div className="h-px w-8 border-[#c7cec4] border-t border-dashed" />
				<MiniCell accent />
			</div>
		);
	}

	return (
		<div className="mt-4 flex items-center justify-center">
			<div className="relative h-16 w-32 rounded-md border border-[#e4e1d8] bg-[#f7f6f0]">
				<MiniCell active className="absolute top-3 left-5" compact />
				<MagnifyingGlass
					className="absolute right-4 bottom-2 text-[#38433f]"
					size={42}
					weight="regular"
				/>
			</div>
		</div>
	);
}

function MiniCell({
	active,
	accent,
	className = "",
	compact,
	muted,
}: {
	active?: boolean;
	accent?: boolean;
	className?: string;
	compact?: boolean;
	muted?: boolean;
}) {
	return (
		<div
			className={`${compact ? "h-12 w-14" : "h-14 w-full"} relative overflow-hidden rounded-md border ${
				active
					? "border-[#cbd736] bg-[#f1f8df]"
					: accent
						? "border-[#d6dd8d] bg-[#f2f6ce]"
						: muted
							? "border-[#e1ded5] bg-[#f6f4ef]"
							: "border-[#e1ded5] bg-[#fffef9]"
			} ${className}`}
		>
			<div
				className={`absolute top-4 left-3 h-6 w-8 rounded-[45%] border-2 ${
					accent
						? "border-[#9cab22]"
						: active
							? "border-[#087a66]"
							: "border-[#b4bab2]"
				}`}
			/>
			<div
				className={`absolute right-3 bottom-3 h-5 w-7 rounded-[45%] border-2 ${
					accent
						? "border-[#c0c635]"
						: active
							? "border-[#12927b]"
							: "border-[#c8ccc4]"
				}`}
			/>
		</div>
	);
}

function CandidateRow({ candidate }: { candidate: WorkspaceCandidate }) {
	return (
		<div className="rounded-lg border border-[#e2dfd5] bg-[#fffef9] p-3">
			<div className="flex items-center justify-between gap-3">
				<p className="font-medium text-[#24302b] text-sm">
					#{candidate.rank} {candidate.rcsbId}
				</p>
				<p className="font-mono text-[#57615b] text-xs">
					{Math.round(candidate.relevanceScore * 100)}%
				</p>
			</div>
			<p className="mt-1 line-clamp-2 text-[#68716a] text-xs leading-5">
				{candidate.selectionRationale}
			</p>
			<div className="mt-2 flex flex-wrap gap-1.5">
				{candidate.method ? <MetaPill>{candidate.method}</MetaPill> : null}
				{candidate.resolutionAngstrom ? (
					<MetaPill>{candidate.resolutionAngstrom.toFixed(1)} A</MetaPill>
				) : null}
				{candidate.proteinaReady ? <MetaPill>CIF ready</MetaPill> : null}
			</div>
		</div>
	);
}

function MetaPill({ children }: { children: ReactNode }) {
	return (
		<span className="rounded-md bg-[#eef1e8] px-2 py-1 text-[#5b655f] text-[11px]">
			{children}
		</span>
	);
}
