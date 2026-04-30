type AnswerCandidate = {
	citationJson: Record<string, unknown>;
	method: string | null;
	proteinaReady: boolean;
	rank: number;
	rcsbId: string;
	relevanceScore: number;
	resolutionAngstrom: number | null;
	selectionRationale: string;
	title: string;
};

type AnswerArtifact = {
	fileName: string;
	signedUrl?: string | null;
	sourceUrl: string | null;
	type: string;
};

type AnswerEvent = {
	detail: string | null;
	title: string;
	type: string;
};

type WorkspaceForAnswer = {
	activeRun: {
		errorSummary: string | null;
		prompt: string;
		status: string;
	} | null;
	artifacts: AnswerArtifact[];
	candidates: AnswerCandidate[];
	events: AnswerEvent[];
	targetEntities: Array<{ name: string; organism: string | null }>;
} | null;

type AnswerWorkspaceQuestionInput = {
	question: string;
	workspace: WorkspaceForAnswer;
};

const asRefArray = (
	value: unknown,
): Array<{ title?: string; url?: string; id?: string }> =>
	Array.isArray(value) ? value.filter((item) => typeof item === "object") : [];

const formatCandidate = (candidate: AnswerCandidate) => {
	const score = Math.round(candidate.relevanceScore * 100);
	const resolution = candidate.resolutionAngstrom
		? `, ${candidate.resolutionAngstrom.toFixed(1)} A`
		: "";
	const method = candidate.method ? `, ${candidate.method}` : "";

	return `#${candidate.rank} ${candidate.rcsbId} (${score}%${method}${resolution})`;
};

const summarizeLiterature = (candidate: AnswerCandidate | null) => {
	if (!candidate) {
		return "No candidate has been ranked yet, so there are no linked literature references.";
	}

	const pubmed = asRefArray(candidate.citationJson.pubmed);
	const biorxiv = asRefArray(candidate.citationJson.biorxiv);
	const references = [
		...pubmed.slice(0, 2).map((ref) => ref.title ?? ref.id ?? "PubMed result"),
		...biorxiv
			.slice(0, 2)
			.map((ref) => ref.title ?? ref.id ?? "bioRxiv preprint"),
	];

	if (references.length === 0) {
		return "The run checked literature sources, but no linked PubMed or bioRxiv references were returned for the selected candidate.";
	}

	return `Literature considered: ${references.join("; ")}.`;
};

const summarizeArtifact = (artifact: AnswerArtifact | null) => {
	if (!artifact) {
		return "No CIF artifact is ready yet. Once RCSB download and R2 upload finish, the workspace will show a Download CIF action.";
	}

	return `CIF artifact ${artifact.fileName} is ready for download and Mol* visualization.`;
};

const summarizeStructure = (candidate: AnswerCandidate | null) => {
	if (!candidate) {
		return "No RCSB candidates have been ranked yet. The worker will list structures here after the RCSB search completes.";
	}

	return `Top ranked structure: ${formatCandidate(candidate)}. ${candidate.selectionRationale}`;
};

export const answerWorkspaceQuestion = ({
	question,
	workspace,
}: AnswerWorkspaceQuestionInput) => {
	if (!workspace?.activeRun) {
		return "No retrieval run has been started yet. Start with a target goal and I can summarize structures, literature evidence, and CIF readiness once the worker writes results.";
	}

	const normalizedQuestion = question.toLowerCase();
	const topCandidate = workspace.candidates[0] ?? null;
	const readyArtifact =
		workspace.artifacts.find((artifact) =>
			["prepared_cif", "source_cif"].includes(artifact.type),
		) ?? null;
	const target = workspace.targetEntities[0];
	const latestEvent = workspace.events.at(-1);
	const status = workspace.activeRun.status;
	const asksStatus =
		/status|progress|log|running|queued|failed|done|finish/u.test(
			normalizedQuestion,
		);
	const asksLiterature =
		/literature|paper|pubmed|biorxiv|preprint|research/u.test(
			normalizedQuestion,
		);
	const asksArtifact = /download|cif|file|artifact/u.test(normalizedQuestion);
	const asksStructure =
		/pdb|rcsb|structure|candidate|rank|sort|resolution/u.test(
			normalizedQuestion,
		);
	const multiPartAnswer = [
		asksStatus
			? (() => {
					const detail =
						status === "failed"
							? (workspace.activeRun?.errorSummary ?? latestEvent?.detail)
							: (latestEvent?.detail ?? latestEvent?.title);
					return `Run status is ${status}${
						detail ? `; latest trace: ${detail}` : ""
					}.`;
				})()
			: null,
		asksStructure ? summarizeStructure(topCandidate) : null,
		asksArtifact ? summarizeArtifact(readyArtifact) : null,
		asksLiterature ? summarizeLiterature(topCandidate) : null,
	].filter(Boolean);

	if (multiPartAnswer.length > 1) {
		return multiPartAnswer.join(" ");
	}

	if (asksStatus) {
		const detail =
			status === "failed"
				? (workspace.activeRun.errorSummary ?? latestEvent?.detail)
				: (latestEvent?.detail ?? latestEvent?.title);
		return `Run status is ${status}. ${
			detail
				? `Latest trace: ${detail}`
				: "No trace detail has been written yet."
		}`;
	}

	if (asksLiterature) {
		return summarizeLiterature(topCandidate);
	}

	if (asksArtifact) {
		return summarizeArtifact(readyArtifact);
	}

	if (asksStructure) {
		return summarizeStructure(topCandidate);
	}

	const targetText = target
		? `${target.name}${target.organism ? ` from ${target.organism}` : ""}`
		: workspace.activeRun.prompt;
	const candidateText = topCandidate
		? `The leading structure is ${formatCandidate(topCandidate)}.`
		: "No ranked structure is available yet.";
	const artifactText = readyArtifact
		? `CIF artifact ${readyArtifact.fileName} is ready.`
		: "The CIF artifact is not ready yet.";

	return `Julia is working on ${targetText}. Run status is ${status}. ${candidateText} ${artifactText} ${summarizeLiterature(topCandidate)}`;
};
