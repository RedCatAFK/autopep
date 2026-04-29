"use client";

import { Check, CircleNotch } from "@phosphor-icons/react";

type Score = {
	candidateId: string;
	label: string | null;
	scorer:
		| "dscript"
		| "future_scorer"
		| "prodigy"
		| "protein_interaction_aggregate"
		| string;
	unit: string | null;
	value: number | null;
};

type JourneyPanelProps = {
	activeRunStatus: string | null;
	artifacts: { id: string; kind: string; name: string }[];
	candidateScores: Score[];
	candidates: { id: string; rank: number; title: string }[];
	objective: string;
};

const milestones = [
	"Understand target",
	"Find structures",
	"Prepare target",
	"Generate, fold, score",
];

export function JourneyPanel({
	activeRunStatus,
	artifacts,
	candidateScores,
	candidates,
}: JourneyPanelProps) {
	const scoreByCandidate = new Map<string, Score[]>();
	for (const score of candidateScores) {
		scoreByCandidate.set(score.candidateId, [
			...(scoreByCandidate.get(score.candidateId) ?? []),
			score,
		]);
	}

	const completed = activeRunStatus === "completed";
	const active = activeRunStatus === "queued" || activeRunStatus === "running";

	return (
		<section className="border-[#e5e2d9] border-b px-4 py-4">
			<div className="space-y-2">
				{milestones.map((milestone, index) => {
					const done =
						index < 3
							? candidates.length > 0 || artifacts.length > 0 || completed
							: completed;
					const isActive = !done && active && index === 3;
					return (
						<Milestone
							done={done}
							key={milestone}
							label={milestone}
							loading={isActive}
						/>
					);
				})}
			</div>

			<div className="mt-5 space-y-2">
				{candidates.length === 0 ? (
					<p className="rounded-md border border-[#d7d4c9] border-dashed bg-[#fffef9] p-3 text-[#69716b] text-sm leading-6">
						Candidate score leaves appear after the generation, folding, and
						interaction scoring loop writes results.
					</p>
				) : (
					candidates.map((candidate) => {
						const scores = scoreByCandidate.get(candidate.id) ?? [];
						const aggregate = scores.find(
							(score) => score.scorer === "protein_interaction_aggregate",
						);
						const dscript = scores.find((score) => score.scorer === "dscript");
						const prodigy = scores.find((score) => score.scorer === "prodigy");

						return (
							<div
								className="rounded-md border border-[#ddd9cf] bg-[#fffef9] p-3"
								key={candidate.id}
							>
								<div className="flex items-center justify-between gap-2">
									<p className="min-w-0 truncate font-medium text-[#24302b] text-sm">
										#{candidate.rank} {candidate.title}
									</p>
									{aggregate?.label ? (
										<span className="shrink-0 rounded bg-[#eaf4cf] px-2 py-1 text-[#315419] text-xs">
											{aggregate.label}
										</span>
									) : null}
								</div>
								<div className="mt-3 grid grid-cols-1 gap-1 text-[#58625d] text-xs">
									{dscript?.value !== null && dscript?.value !== undefined ? (
										<p>D-SCRIPT {formatNumber(dscript.value)}</p>
									) : null}
									{prodigy?.value !== null && prodigy?.value !== undefined ? (
										<p>
											PRODIGY {formatNumber(prodigy.value)}
											{prodigy.unit ? ` ${prodigy.unit}` : ""}
										</p>
									) : null}
								</div>
							</div>
						);
					})
				)}
			</div>

			<p className="mt-4 rounded-md bg-[#f0efe8] px-3 py-2 text-[#626c66] text-xs">
				{completed ? "MVP loop complete" : "MVP loop pending"}
			</p>
		</section>
	);
}

function Milestone({
	done,
	label,
	loading,
}: {
	done: boolean;
	label: string;
	loading: boolean;
}) {
	return (
		<div className="flex items-center gap-2 text-[#36433e] text-sm">
			<span
				className={`flex size-5 shrink-0 items-center justify-center rounded-full ${
					done
						? "bg-[#2d8c5a] text-[#fffef9]"
						: "border border-[#c8c5ba] bg-[#fffef9] text-[#7c837b]"
				}`}
			>
				{done ? (
					<Check aria-hidden="true" size={12} weight="bold" />
				) : loading ? (
					<CircleNotch aria-hidden="true" className="animate-spin" size={12} />
				) : null}
			</span>
			<span>{label}</span>
		</div>
	);
}

function formatNumber(value: number) {
	return new Intl.NumberFormat("en-US", {
		maximumFractionDigits: 2,
	}).format(value);
}
