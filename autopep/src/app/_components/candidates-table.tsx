"use client";

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

type CandidatesTableProps = {
	candidates: CandidateRow[];
	candidateScores: ScoreRow[];
	onOpenCandidate?: (candidateId: string) => void;
};

export function CandidatesTable({
	candidates,
	candidateScores,
	onOpenCandidate,
}: CandidatesTableProps) {
	if (candidates.length === 0) {
		return (
			<div className="flex h-full items-center justify-center px-6 text-[#7a817a] text-sm">
				No candidates yet — they will appear here once the agent finishes
				generation, folding, and scoring.
			</div>
		);
	}

	const scoreByCandidate = new Map<string, ScoreRow[]>();
	for (const score of candidateScores) {
		scoreByCandidate.set(score.candidateId, [
			...(scoreByCandidate.get(score.candidateId) ?? []),
			score,
		]);
	}

	return (
		<div className="h-full overflow-auto">
			<table className="w-full text-left text-[#26332e] text-sm">
				<thead className="sticky top-0 bg-[#f8f7f2] text-[#5a6360] text-xs uppercase tracking-wide">
					<tr>
						<th className="px-3 py-2 font-medium">Rank</th>
						<th className="px-3 py-2 font-medium">Title</th>
						<th className="px-3 py-2 font-medium">Organism</th>
						<th className="px-3 py-2 font-medium">Method</th>
						<th className="px-3 py-2 font-medium">Resolution</th>
						<th className="px-3 py-2 font-medium">D-SCRIPT</th>
						<th className="px-3 py-2 font-medium">PRODIGY</th>
						<th className="px-3 py-2 font-medium">Aggregate</th>
						<th className="px-3 py-2 font-medium">Label</th>
						<th className="px-3 py-2 font-medium">Action</th>
					</tr>
				</thead>
				<tbody>
					{candidates.map((candidate) => {
						const scores = scoreByCandidate.get(candidate.id) ?? [];
						const dscript = scores.find((score) => score.scorer === "dscript");
						const prodigy = scores.find((score) => score.scorer === "prodigy");
						const aggregate = scores.find(
							(score) => score.scorer === "protein_interaction_aggregate",
						);

						return (
							<tr
								className="border-[#e5e2d9] border-b last:border-b-0 hover:bg-[#fffef9]"
								key={candidate.id}
							>
								<td className="px-3 py-2 text-[#5a6360]">#{candidate.rank}</td>
								<td className="px-3 py-2 font-medium">{candidate.title}</td>
								<td className="px-3 py-2 text-[#5a6360]">
									{candidate.organism ?? "—"}
								</td>
								<td className="px-3 py-2 text-[#5a6360]">
									{candidate.method ?? "—"}
								</td>
								<td className="px-3 py-2 text-[#5a6360]">
									{candidate.resolutionAngstrom != null
										? `${formatNumber(candidate.resolutionAngstrom)} Å`
										: "—"}
								</td>
								<td className="px-3 py-2 text-[#5a6360]">
									{formatScoreValue(dscript)}
								</td>
								<td className="px-3 py-2 text-[#5a6360]">
									{formatScoreValue(prodigy)}
								</td>
								<td className="px-3 py-2 text-[#5a6360]">
									{formatScoreValue(aggregate)}
								</td>
								<td className="px-3 py-2">
									{aggregate?.label ? (
										<span className="rounded bg-[#eaf4cf] px-2 py-1 text-[#315419] text-xs">
											{aggregate.label}
										</span>
									) : (
										<span className="text-[#5a6360]">—</span>
									)}
								</td>
								<td className="px-3 py-2">
									<button
										className="rounded border border-[#cbd736] bg-[#f5f8df] px-2 py-1 text-[#315419] text-xs transition-colors hover:bg-[#eaf4cf] disabled:cursor-not-allowed disabled:opacity-50"
										disabled={!onOpenCandidate}
										onClick={() => onOpenCandidate?.(candidate.id)}
										type="button"
									>
										Open structure
									</button>
								</td>
							</tr>
						);
					})}
				</tbody>
			</table>
		</div>
	);
}

function formatScoreValue(score: ScoreRow | undefined) {
	if (!score || score.value == null) {
		return "—";
	}
	const formatted = formatNumber(score.value);
	return score.unit ? `${formatted} ${score.unit}` : formatted;
}

function formatNumber(value: number) {
	return new Intl.NumberFormat("en-US", {
		maximumFractionDigits: 2,
	}).format(value);
}
