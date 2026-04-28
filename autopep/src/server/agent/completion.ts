import type { ArtifactType } from "./contracts";

type CompletionCandidate = {
	id: string;
	rank: number;
	proteinaReady: boolean;
};

type CompletionArtifact = {
	id: string;
	candidateId: string | null;
	type: ArtifactType;
};

type RunCompletionInput = {
	candidates: CompletionCandidate[];
	artifacts: CompletionArtifact[];
};

type RunCompletionResult =
	| {
			ok: true;
			selectedCandidateId: string;
			selectedArtifactId: string;
	  }
	| {
			ok: false;
			reason:
				| "No proteina-ready candidate exists."
				| "No proteina-ready CIF artifact is linked to the selected candidate.";
	  };

const cifArtifactTypes = new Set<ArtifactType>(["prepared_cif", "source_cif"]);

export const validateRunCompletion = ({
	candidates,
	artifacts,
}: RunCompletionInput): RunCompletionResult => {
	const selectedCandidate = candidates
		.filter((candidate) => candidate.proteinaReady)
		.sort((left, right) => left.rank - right.rank)[0];

	if (!selectedCandidate) {
		return { ok: false, reason: "No proteina-ready candidate exists." };
	}

	const selectedArtifact = artifacts.find(
		(artifact) =>
			artifact.candidateId === selectedCandidate.id &&
			cifArtifactTypes.has(artifact.type),
	);

	if (!selectedArtifact) {
		return {
			ok: false,
			reason:
				"No proteina-ready CIF artifact is linked to the selected candidate.",
		};
	}

	return {
		ok: true,
		selectedArtifactId: selectedArtifact.id,
		selectedCandidateId: selectedCandidate.id,
	};
};
