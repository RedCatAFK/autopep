"use client";

import {
	ArrowClockwise,
	ArrowRight,
	ArrowsOutSimple,
	Atom,
	BookOpen,
	BoundingBox,
	CaretRight,
	ChatCircleText,
	Check,
	CircleNotch,
	Cube,
	DotsThreeVertical,
	DownloadSimple,
	Eye,
	FileText,
	FolderOpen,
	FunnelSimple,
	GearSix,
	HandPalm,
	HouseLine,
	Info,
	Lightning,
	LinkSimple,
	MagnifyingGlass,
	Paperclip,
	PaperPlaneTilt,
	Question,
	ShareNetwork,
	SlidersHorizontal,
	SortAscending,
	Sparkle,
	UserCircle,
	X,
} from "@phosphor-icons/react";
import Image from "next/image";
import {
	type FormEvent,
	type ReactNode,
	useEffect,
	useMemo,
	useState,
} from "react";

import { proteinTargetPreview } from "@/app/_components/protein-preview-image";

export type WorkspaceCandidate = {
	citationJson: Record<string, unknown>;
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
	payloadJson: Record<string, unknown>;
	sequence: number;
	title: string;
	type: string;
};

export type WorkspaceArtifact = {
	byteSize: number;
	candidateId: string | null;
	fileName: string;
	id: string;
	signedUrl: string | null;
	sourceUrl: string | null;
	type: string;
};

export type WorkspaceChatMessage = {
	id: string;
	role: "assistant" | "user";
	text: string;
};

type WorkspaceShellProps = {
	artifactLabel: string;
	artifacts: WorkspaceArtifact[];
	candidates: WorkspaceCandidate[];
	chatMessages: WorkspaceChatMessage[];
	children: ReactNode;
	events: WorkspaceEvent[];
	isAnsweringQuestion: boolean;
	isCreatingRun: boolean;
	isLoadingWorkspace: boolean;
	onAskQuestion: (question: string) => void;
	onRefresh: () => void;
	onStartGoal: (goal: string, options?: { topK: number }) => void;
	projectGoal: string;
	runStatus: string | null;
	selectedArtifact: WorkspaceArtifact | null;
	selectedCandidate: WorkspaceCandidate | null;
	targetName: string;
};

const spikeGoal = "Design a protein binder for SARS-CoV-2 spike RBD";
const proteaseGoal = "Design a protein binder for 3CL-protease";

const statusCopy: Record<string, { detail: string; label: string }> = {
	cancelled: {
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
	completed: {
		detail: "We found a relevant structure and prepared it for design.",
		label: "Target structure ready",
	},
};

const eventTypeLabels: Record<string, string> = {
	codex_agent_fallback: "Agent fallback",
	codex_agent_finished: "Codex finished",
	codex_agent_started: "Codex running",
	downloading_cif: "Downloading CIF",
	normalizing_target: "Understanding target",
	preparing_cif: "Preparing CIF",
	ranking_candidates: "Ranking matches",
	ready_for_proteina: "Ready for Proteina",
	run_start_skipped: "Run already active",
	searching_literature: "Reading literature",
	searching_biorxiv: "Searching bioRxiv",
	searching_structures: "Finding structures",
	uploading_artifact: "Saving artifact",
};

export function WorkspaceShell({
	artifactLabel,
	artifacts,
	candidates,
	chatMessages,
	children,
	events,
	isAnsweringQuestion,
	isCreatingRun,
	isLoadingWorkspace,
	onAskQuestion,
	onRefresh,
	onStartGoal,
	projectGoal,
	runStatus,
	selectedArtifact,
	selectedCandidate,
	targetName,
}: WorkspaceShellProps) {
	const [draftGoal, setDraftGoal] = useState(projectGoal || spikeGoal);
	const [attachedContext, setAttachedContext] = useState("");
	const [candidateFilter, setCandidateFilter] = useState<
		"all" | "ready" | "structure"
	>("all");
	const [candidateSort, setCandidateSort] = useState<
		"rank" | "resolution" | "score"
	>("rank");
	const [isHelpOpen, setIsHelpOpen] = useState(false);
	const [isOptionsOpen, setIsOptionsOpen] = useState(false);
	const [isSettingsOpen, setIsSettingsOpen] = useState(false);
	const [isContextOpen, setIsContextOpen] = useState(false);
	const [questionDraft, setQuestionDraft] = useState("");
	const [showAllEvents, setShowAllEvents] = useState(false);
	const [stageTool, setStageTool] = useState("Select");
	const [topK, setTopK] = useState(5);
	const status = runStatus ? statusCopy[runStatus] : null;
	const hasRun = Boolean(runStatus);
	const isActive = runStatus === "queued" || runStatus === "running";
	const hasArtifact = artifactLabel !== "No CIF artifact yet";
	const canStartRun = draftGoal.trim().length >= 3 && !isCreatingRun;
	const structureReady = Boolean(selectedCandidate);
	const evidenceReady =
		events.some((event) => event.type === "searching_literature") ||
		runStatus === "completed";
	const designInputReady = Boolean(
		selectedCandidate?.proteinaReady && hasArtifact,
	);
	const selectedCandidateReady = Boolean(
		selectedCandidate?.proteinaReady && hasArtifact,
	);
	const eventsToDisplay = showAllEvents ? events : events.slice(-5);
	const latestEvents = eventsToDisplay.slice().reverse();
	const artifactByCandidateId = useMemo(
		() =>
			new Map(
				artifacts
					.filter((artifact) => artifact.candidateId)
					.map((artifact) => [artifact.candidateId, artifact]),
			),
		[artifacts],
	);
	const sortedCandidates = useMemo(() => {
		const filtered = candidates.filter((candidate) => {
			if (candidateFilter === "ready") {
				return candidate.proteinaReady;
			}
			if (candidateFilter === "structure") {
				return Boolean(candidate.method || candidate.resolutionAngstrom);
			}

			return true;
		});

		return filtered.slice().sort((left, right) => {
			if (candidateSort === "score") {
				return right.relevanceScore - left.relevanceScore;
			}
			if (candidateSort === "resolution") {
				const leftResolution =
					left.resolutionAngstrom ?? Number.POSITIVE_INFINITY;
				const rightResolution =
					right.resolutionAngstrom ?? Number.POSITIVE_INFINITY;
				return leftResolution - rightResolution;
			}

			return left.rank - right.rank;
		});
	}, [candidateFilter, candidateSort, candidates]);
	const selectedArtifactHref = selectedArtifact?.signedUrl ?? null;
	const submitGoal = (goal: string) => {
		const trimmedGoal = goal.trim();
		if (trimmedGoal.length < 3 || isCreatingRun) {
			return;
		}

		const goalWithContext = attachedContext.trim()
			? `${trimmedGoal}\n\nContext:\n${attachedContext.trim()}`
			: trimmedGoal;
		onStartGoal(goalWithContext, { topK });
	};
	const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		submitGoal(draftGoal);
	};
	const handleQuestionSubmit = (event: FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		const trimmedQuestion = questionDraft.trim();
		if (!trimmedQuestion || isAnsweringQuestion) {
			return;
		}

		setQuestionDraft("");
		onAskQuestion(trimmedQuestion);
	};
	const triggerViewerAction = (action: string) => {
		setStageTool(action);
		window.dispatchEvent(
			new CustomEvent("autopep:viewer-action", {
				detail: { action },
			}),
		);
	};

	useEffect(() => {
		setDraftGoal(projectGoal || spikeGoal);
	}, [projectGoal]);

	return (
		<main className="min-h-[100dvh] bg-[#f8f7f2] text-[#17211e] lg:fixed lg:inset-0 lg:flex lg:min-h-0 lg:flex-col lg:overflow-hidden">
			<header className="sticky top-0 z-20 flex h-16 items-center justify-between border-[#e5e2d9] border-b bg-[#fffef9]/95 px-4 backdrop-blur md:px-5 lg:shrink-0">
				<div className="flex items-center gap-3">
					<AutopepMark />
					<p className="font-semibold text-[21px] tracking-[-0.02em]">
						Autopep
					</p>
				</div>
				<div className="flex items-center gap-2">
					<IconButton
						ariaLabel="Help"
						onClick={() => setIsHelpOpen((isOpen) => !isOpen)}
						title="Help"
					>
						<Question size={18} />
					</IconButton>
					<div className="flex size-9 items-center justify-center rounded-full border border-[#e5e2d9] bg-[#f6f4ee] font-medium text-[#2b332f] text-xs">
						<UserCircle size={18} weight="duotone" />
					</div>
				</div>
			</header>
			{isHelpOpen ? (
				<div className="fixed top-[4.5rem] right-4 z-30 w-[min(360px,calc(100vw-2rem))] rounded-lg border border-[#d7d4c9] bg-[#fffef9] p-4 shadow-[0_24px_80px_-46px_rgba(25,39,33,0.75)]">
					<div className="flex items-start justify-between gap-3">
						<div className="flex items-center gap-2">
							<Info size={18} />
							<p className="font-semibold text-sm">Current scope</p>
						</div>
						<button
							aria-label="Close help"
							className="rounded-md p-1 text-[#5f6963] hover:bg-[#f0efe8]"
							onClick={() => setIsHelpOpen(false)}
							type="button"
						>
							<X size={16} />
						</button>
					</div>
					<p className="mt-3 text-[#626c66] text-sm leading-6">
						Autopep currently retrieves target structures, reviews PubMed and
						bioRxiv-style preprints, downloads CIF files, and visualizes them in
						Mol*. Binder generation and mutation tools are intentionally out of
						scope.
					</p>
				</div>
			) : null}

			<div className="grid min-h-[calc(100dvh-4rem)] grid-cols-1 md:grid-cols-[72px_minmax(0,1fr)] lg:min-h-0 lg:flex-1 lg:grid-cols-[72px_minmax(300px,360px)_minmax(0,1fr)_minmax(300px,340px)]">
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

				<aside className="border-[#e5e2d9] border-b bg-[#fbfaf6] p-5 md:col-start-2 lg:col-start-auto lg:min-h-0 lg:overflow-y-auto lg:border-r lg:border-b-0">
					<section>
						<p className="font-semibold text-[17px] tracking-[-0.01em]">
							What would you like to design?
						</p>
						<p className="mt-1 text-[#6c726c] text-sm">
							Describe your goal in plain English.
						</p>

						<form
							className="mt-5 rounded-lg border border-[#d7d4c9] bg-[#fffef9] p-4 shadow-[0_16px_50px_-42px_rgba(25,39,33,0.7)]"
							onSubmit={handleSubmit}
						>
							<label className="sr-only" htmlFor="autopep-goal">
								Protein design goal
							</label>
							<textarea
								className="min-h-[96px] w-full resize-none bg-transparent text-[#27322f] text-xl leading-8 tracking-[-0.02em] outline-none placeholder:text-[#a0a69f]"
								disabled={isCreatingRun}
								id="autopep-goal"
								onChange={(event) => setDraftGoal(event.target.value)}
								placeholder={spikeGoal}
								value={draftGoal}
							/>
							<div className="mt-6 flex items-center justify-between gap-3">
								<div className="flex items-center gap-3 text-[#44504b]">
									<button
										aria-label="Attach research context"
										className="rounded-md p-1.5 transition hover:bg-[#f0f0e9]"
										onClick={() => setIsContextOpen((isOpen) => !isOpen)}
										type="button"
									>
										<Paperclip size={19} />
									</button>
									<button
										aria-label="Prompt settings"
										className="rounded-md p-1.5 transition hover:bg-[#f0f0e9]"
										onClick={() => setIsSettingsOpen((isOpen) => !isOpen)}
										type="button"
									>
										<SlidersHorizontal size={19} />
									</button>
								</div>
								<button
									aria-label="Start target retrieval"
									className="flex size-11 items-center justify-center rounded-lg bg-[#dfe94c] text-[#1d342e] transition hover:bg-[#d4e337] active:translate-y-[1px] disabled:cursor-not-allowed disabled:opacity-60"
									disabled={!canStartRun}
									title="Start target retrieval"
									type="submit"
								>
									<PaperPlaneTilt size={22} weight="fill" />
								</button>
							</div>
							{isContextOpen ? (
								<div className="mt-4 border-[#ece9df] border-t pt-4">
									<label
										className="font-medium text-[#49524d] text-xs"
										htmlFor="autopep-context"
									>
										Research context
									</label>
									<textarea
										className="mt-2 min-h-20 w-full resize-none rounded-md border border-[#ddd9cf] bg-[#fbfaf6] px-3 py-2 text-[#34403b] text-sm leading-6 outline-none transition focus:border-[#cbd736]"
										id="autopep-context"
										onChange={(event) => setAttachedContext(event.target.value)}
										placeholder="Optional constraints, organism, assay context, or known PDB IDs"
										value={attachedContext}
									/>
								</div>
							) : null}
							{isSettingsOpen ? (
								<div className="mt-4 border-[#ece9df] border-t pt-4">
									<div className="flex items-center justify-between gap-3">
										<label
											className="font-medium text-[#49524d] text-xs"
											htmlFor="autopep-top-k"
										>
											RCSB results
										</label>
										<p className="font-mono text-[#41504b] text-xs">{topK}</p>
									</div>
									<input
										className="mt-3 w-full accent-[#0b715f]"
										id="autopep-top-k"
										max={10}
										min={1}
										onChange={(event) => setTopK(Number(event.target.value))}
										type="range"
										value={topK}
									/>
								</div>
							) : null}
						</form>

						<div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-1">
							<ExampleButton
								disabled={isCreatingRun}
								label="SARS-CoV-2 spike RBD"
								onClick={() => {
									setDraftGoal(spikeGoal);
									submitGoal(spikeGoal);
								}}
							/>
							<ExampleButton
								disabled={isCreatingRun}
								label="3CL-protease"
								onClick={() => {
									setDraftGoal(proteaseGoal);
									submitGoal(proteaseGoal);
								}}
							/>
						</div>
					</section>

					<section className="mt-7">
						<div className="flex items-center gap-2">
							<ChatCircleText size={17} weight="fill" />
							<p className="font-medium text-sm">Autopep Assistant</p>
						</div>
						<div className="mt-4 rounded-lg border border-[#d7d4c9] bg-[#fffef9] p-4">
							<div className="flex gap-4">
								<ProgressGlyph
									active={isActive || isLoadingWorkspace}
									done={runStatus === "completed"}
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
							<div className="mt-4 max-h-52 space-y-2 overflow-y-auto pr-1">
								{chatMessages.map((message) => (
									<div
										className={`rounded-lg px-3 py-2 text-sm leading-6 ${
											message.role === "user"
												? "ml-7 bg-[#edf4ed] text-[#24302b]"
												: "mr-7 bg-[#f4f2ea] text-[#4e5953]"
										}`}
										key={message.id}
									>
										{message.text}
									</div>
								))}
								{isAnsweringQuestion ? (
									<div className="mr-7 rounded-lg bg-[#f4f2ea] px-3 py-2 text-[#4e5953] text-sm">
										<CircleNotch className="inline animate-spin" size={14} />{" "}
										Thinking
									</div>
								) : null}
							</div>
							<form className="mt-3 flex gap-2" onSubmit={handleQuestionSubmit}>
								<label className="sr-only" htmlFor="autopep-question">
									Ask Autopep
								</label>
								<input
									className="min-w-0 flex-1 rounded-md border border-[#ddd9cf] bg-[#fbfaf6] px-3 py-2 text-[#303b37] text-sm outline-none transition placeholder:text-[#9ba39c] focus:border-[#cbd736]"
									disabled={isAnsweringQuestion}
									id="autopep-question"
									onChange={(event) => setQuestionDraft(event.target.value)}
									placeholder="Ask about PDB, bioRxiv, or CIF"
									value={questionDraft}
								/>
								<button
									aria-label="Ask Autopep"
									className="flex size-10 shrink-0 items-center justify-center rounded-md bg-[#dfe94c] text-[#20342f] transition hover:bg-[#d4e337] disabled:cursor-not-allowed disabled:opacity-60"
									disabled={!questionDraft.trim() || isAnsweringQuestion}
									type="submit"
								>
									<PaperPlaneTilt size={18} weight="fill" />
								</button>
							</form>
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
									<div
										className={`mt-3 inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 font-medium text-xs ${
											selectedCandidateReady
												? "bg-[#eaf4cf] text-[#315419]"
												: "bg-[#f0efe8] text-[#58625d]"
										}`}
									>
										{selectedCandidateReady ? "Ready for design" : "Candidate"}
										{selectedCandidateReady ? (
											<Check size={13} weight="bold" />
										) : null}
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

				<section className="flex min-w-0 flex-col bg-[#f8f7f2] lg:min-h-0 lg:overflow-hidden lg:border-[#e5e2d9] lg:border-r">
					<div className="flex flex-wrap items-start justify-between gap-4 p-5 md:p-6 lg:shrink-0">
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
							{selectedArtifactHref ? (
								<a
									aria-label="Download CIF"
									className="flex size-8 items-center justify-center rounded-md text-[#394541] transition hover:bg-[#f0efe8] active:translate-y-[1px]"
									href={selectedArtifactHref}
									rel="noreferrer"
									target="_blank"
									title="Download CIF"
								>
									<DownloadSimple size={18} />
								</a>
							) : null}
							<IconButton
								ariaLabel="Refresh workspace"
								onClick={onRefresh}
								title="Refresh"
							>
								<ArrowClockwise size={18} />
							</IconButton>
							<IconButton
								ariaLabel="Fit viewer"
								onClick={() => triggerViewerAction("Reset")}
								title="Fit viewer"
							>
								<ArrowsOutSimple size={18} />
							</IconButton>
							<IconButton
								ariaLabel="More options"
								onClick={() => setIsOptionsOpen((isOpen) => !isOpen)}
								title="More options"
							>
								<DotsThreeVertical size={18} weight="bold" />
							</IconButton>
						</div>
					</div>
					{isOptionsOpen ? (
						<div className="absolute top-[7.25rem] right-5 z-20 w-64 rounded-lg border border-[#d7d4c9] bg-[#fffef9] p-3 shadow-[0_24px_80px_-50px_rgba(25,39,33,0.75)]">
							<p className="font-semibold text-[#27322f] text-sm">
								Workspace actions
							</p>
							<div className="mt-3 space-y-2">
								<ActionLink
									disabled={!selectedCandidate}
									href={
										selectedCandidate
											? `https://www.rcsb.org/structure/${selectedCandidate.rcsbId}`
											: null
									}
									icon={<LinkSimple size={16} />}
									label="Open RCSB entry"
								/>
								<ActionLink
									disabled={!selectedArtifactHref}
									href={selectedArtifactHref}
									icon={<DownloadSimple size={16} />}
									label="Download CIF"
								/>
							</div>
						</div>
					) : null}

					<div className="relative min-h-[480px] flex-1 px-4 pb-5 md:px-6 md:pb-6 lg:min-h-0">
						<div className="relative h-full min-h-[480px] overflow-hidden rounded-lg border border-[#e2dfd5] bg-[#fffef9] shadow-[0_20px_80px_-62px_rgba(25,39,33,0.9)] lg:min-h-0">
							{children}
							<div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_45%,rgba(33,126,104,0.04),transparent_40%)]" />
						</div>

						<div className="absolute right-1/2 bottom-9 z-10 flex translate-x-1/2 items-center gap-1 rounded-lg border border-[#e1ded4] bg-[#fffef9]/95 p-1.5 shadow-[0_18px_60px_-38px_rgba(25,39,33,0.55)] backdrop-blur">
							<StageTool
								active={stageTool === "Select"}
								label="Select"
								onClick={() => triggerViewerAction("Select")}
							>
								<BoundingBox size={18} />
							</StageTool>
							<StageTool
								active={stageTool === "Pan"}
								label="Pan"
								onClick={() => triggerViewerAction("Pan")}
							>
								<HandPalm size={18} />
							</StageTool>
							<StageTool
								active={stageTool === "Reset"}
								label="Reset"
								onClick={() => triggerViewerAction("Reset")}
							>
								<ArrowClockwise size={18} />
							</StageTool>
							<StageTool
								active={stageTool === "View"}
								label="View"
								onClick={() => triggerViewerAction("View")}
							>
								<Eye size={18} />
							</StageTool>
							<StageTool
								active={stageTool === "Annotate"}
								label="Annotate"
								onClick={() => triggerViewerAction("Annotate")}
							>
								<Sparkle size={18} />
							</StageTool>
						</div>
					</div>
				</section>

				<aside className="border-[#e5e2d9] border-t bg-[#fbfaf6] p-5 md:col-start-2 lg:col-start-auto lg:min-h-0 lg:overflow-y-auto lg:border-t-0">
					<div className="flex items-center justify-between gap-3">
						<div>
							<p className="font-semibold text-sm">Your design journey</p>
							<p className="mt-1 text-[#72776f] text-xs">
								Current target: {targetName}
							</p>
						</div>
						<button
							aria-label="Binder design is not available yet"
							className="flex size-9 cursor-not-allowed items-center justify-center rounded-md border border-[#d7d4c9] bg-[#fffef9] opacity-50"
							disabled
							title="Binder design is a future milestone"
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
							kicker="Sequence generation is out of scope"
							state="idle"
							title="Design binder (future)"
							visual="handoff"
						/>
					</div>

					<div className="mt-5 rounded-lg border border-[#dfe8b3] bg-[#f2f7d7] p-3">
						<div className="flex items-center justify-between gap-3">
							<div className="min-w-0">
								<p className="font-medium text-[#53641e] text-xs">
									Next up:{" "}
									<span className="text-[#27322f]">
										{designInputReady ? "Inspect target" : "Prepare target"}
									</span>
								</p>
								<p className="mt-1 text-[#70785e] text-xs leading-5">
									{designInputReady
										? "The CIF is ready to visualize, download, and hand off."
										: "Once the target is ready, inspection and export can begin."}
								</p>
							</div>
							<div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-[#fffef9]">
								<ArrowRight size={16} />
							</div>
						</div>
					</div>

					<section className="mt-6">
						<div className="flex items-center justify-between gap-3">
							<p className="font-semibold text-sm">Ranked structures</p>
							<div className="flex items-center gap-1">
								<FunnelSimple size={15} />
								<select
									aria-label="Filter ranked structures"
									className="rounded-md border border-[#dcd8cf] bg-[#fffef9] px-2 py-1 text-[#394541] text-xs outline-none"
									onChange={(event) =>
										setCandidateFilter(
											event.target.value as "all" | "ready" | "structure",
										)
									}
									value={candidateFilter}
								>
									<option value="all">All</option>
									<option value="ready">CIF ready</option>
									<option value="structure">Resolved</option>
								</select>
							</div>
						</div>
						<div className="mt-2 flex items-center gap-2 text-[#68716a] text-xs">
							<SortAscending size={14} />
							<select
								aria-label="Sort ranked structures"
								className="rounded-md border border-[#dcd8cf] bg-[#fffef9] px-2 py-1 text-[#394541] text-xs outline-none"
								onChange={(event) =>
									setCandidateSort(
										event.target.value as "rank" | "resolution" | "score",
									)
								}
								value={candidateSort}
							>
								<option value="rank">Rank</option>
								<option value="score">Score</option>
								<option value="resolution">Resolution</option>
							</select>
						</div>
						<div className="mt-3 space-y-2">
							{candidates.length === 0 ? (
								<p className="rounded-lg border border-[#e2dfd5] bg-[#fffef9] p-3 text-[#69716b] text-sm leading-6">
									Candidates will appear after Autopep ranks the RCSB results.
								</p>
							) : sortedCandidates.length === 0 ? (
								<p className="rounded-lg border border-[#e2dfd5] bg-[#fffef9] p-3 text-[#69716b] text-sm leading-6">
									No structures match the current filter.
								</p>
							) : (
								sortedCandidates
									.slice(0, 5)
									.map((candidate) => (
										<CandidateRow
											artifact={artifactByCandidateId.get(candidate.id) ?? null}
											candidate={candidate}
											key={candidate.id}
										/>
									))
							)}
						</div>
					</section>

					<section className="mt-6">
						<div className="flex items-center justify-between gap-3">
							<p className="font-semibold text-sm">Research trace</p>
							<button
								className="rounded-md border border-[#dcd8cf] bg-[#fffef9] px-2 py-1 font-medium text-[#58625d] text-xs transition hover:border-[#cbd736]"
								onClick={() => setShowAllEvents((showAll) => !showAll)}
								type="button"
							>
								{showAllEvents ? "Latest" : "All logs"}
							</button>
						</div>
						<div className="mt-2 flex items-center justify-between gap-3">
							<p className="font-mono text-[#747b74] text-[11px]">
								{runStatus ?? "no-run"}
							</p>
							<p className="text-[#747b74] text-[11px]">
								{events.length} event{events.length === 1 ? "" : "s"}
							</p>
						</div>
						<div className="mt-3 max-h-[360px] space-y-2 overflow-y-auto pr-1">
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
												{truncateMiddle(event.detail, 260)}
											</p>
										) : null}
										<EventPayload payload={event.payloadJson} />
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

function ActionLink({
	disabled,
	href,
	icon,
	label,
}: {
	disabled: boolean;
	href: string | null;
	icon: ReactNode;
	label: string;
}) {
	if (disabled || !href) {
		return (
			<div className="flex items-center gap-2 rounded-md px-2 py-2 text-[#9aa199] text-sm">
				{icon}
				<span>{label}</span>
			</div>
		);
	}

	return (
		<a
			className="flex items-center gap-2 rounded-md px-2 py-2 text-[#36443f] text-sm transition hover:bg-[#f0efe8]"
			href={href}
			rel="noreferrer"
			target="_blank"
		>
			{icon}
			<span>{label}</span>
		</a>
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
			<Image
				alt=""
				className={`object-cover ${muted ? "opacity-55 grayscale" : ""}`}
				fill
				sizes={muted ? "86px" : "104px"}
				src={proteinTargetPreview}
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
	onClick,
}: {
	active?: boolean;
	children: ReactNode;
	label: string;
	onClick: () => void;
}) {
	return (
		<button
			aria-label={label}
			className={`flex size-9 items-center justify-center rounded-md transition active:translate-y-[1px] ${
				active
					? "bg-[#e8ef75] text-[#21352f]"
					: "text-[#3d4844] hover:bg-[#f0efe8]"
			}`}
			onClick={onClick}
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
			<Image
				alt=""
				className={`object-cover mix-blend-multiply ${
					accent
						? "hue-rotate-[48deg] saturate-[1.18]"
						: active
							? ""
							: "opacity-35 grayscale"
				}`}
				fill
				sizes={compact ? "56px" : "100px"}
				src={proteinTargetPreview}
			/>
		</div>
	);
}

function CandidateRow({
	artifact,
	candidate,
}: {
	artifact: WorkspaceArtifact | null;
	candidate: WorkspaceCandidate;
}) {
	const pubmedCount = getCitationCount(candidate.citationJson.pubmed);
	const biorxivCount = getCitationCount(candidate.citationJson.biorxiv);

	return (
		<div className="rounded-lg border border-[#e2dfd5] bg-[#fffef9] p-3">
			<div className="flex items-center justify-between gap-3">
				<a
					className="font-medium text-[#24302b] text-sm underline-offset-4 transition hover:text-[#0b715f] hover:underline"
					href={`https://www.rcsb.org/structure/${candidate.rcsbId}`}
					rel="noreferrer"
					target="_blank"
				>
					#{candidate.rank} {candidate.rcsbId}
				</a>
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
				{pubmedCount > 0 ? <MetaPill>{pubmedCount} PubMed</MetaPill> : null}
				{biorxivCount > 0 ? <MetaPill>{biorxivCount} bioRxiv</MetaPill> : null}
			</div>
			<div className="mt-3 flex items-center gap-2">
				<ActionLink
					disabled={!artifact?.signedUrl}
					href={artifact?.signedUrl ?? null}
					icon={<DownloadSimple size={15} />}
					label={artifact ? "Download CIF" : "CIF pending"}
				/>
				<ActionLink
					disabled={false}
					href={`https://www.rcsb.org/structure/${candidate.rcsbId}`}
					icon={<LinkSimple size={15} />}
					label="RCSB"
				/>
			</div>
		</div>
	);
}

function getCitationCount(value: unknown) {
	return Array.isArray(value) ? value.length : 0;
}

function EventPayload({ payload }: { payload: Record<string, unknown> }) {
	const entries = Object.entries(payload);
	if (entries.length === 0) {
		return null;
	}

	const compact = JSON.stringify(payload);
	if (!compact || compact === "{}") {
		return null;
	}

	return (
		<details className="mt-2 text-[#69716b] text-xs">
			<summary className="cursor-pointer font-medium text-[#49544e]">
				Details
			</summary>
			<pre className="mt-2 max-h-32 overflow-auto rounded-md bg-[#f5f3ed] p-2 font-mono text-[10px] leading-4">
				{truncateMiddle(compact, 700)}
			</pre>
		</details>
	);
}

function truncateMiddle(value: string, maxLength: number) {
	if (value.length <= maxLength) {
		return value;
	}

	const half = Math.floor((maxLength - 5) / 2);
	return `${value.slice(0, half)} ... ${value.slice(-half)}`;
}

function MetaPill({ children }: { children: ReactNode }) {
	return (
		<span className="rounded-md bg-[#eef1e8] px-2 py-1 text-[#5b655f] text-[11px]">
			{children}
		</span>
	);
}
