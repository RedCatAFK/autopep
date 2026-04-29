type ArtifactInput = {
	id: string;
	fileName: string;
	kind: string;
	candidateId: string | null;
	runId: string | null;
	signedUrl: string | null;
	byteSize: number;
};

export type FileGroup =
	| { kind: "attachments"; label: "Attachments"; files: ArtifactInput[] }
	| {
			kind: "candidate";
			label: string;
			candidateId: string;
			files: ArtifactInput[];
	  }
	| {
			kind: "run";
			label: string;
			runId: string;
			startedAt: string;
			status: string;
			files: ArtifactInput[];
	  };

type GroupArgs = {
	artifacts: ArtifactInput[];
	candidates: { id: string; rank: number; title: string }[];
	runs: { id: string; startedAt: string; status: string }[];
};

export const groupArtifacts = ({
	artifacts,
	candidates,
	runs,
}: GroupArgs): FileGroup[] => {
	const attachments = artifacts.filter((a) => a.kind === "attachment");
	const groups: FileGroup[] = [];

	groups.push({
		kind: "attachments",
		label: "Attachments",
		files: attachments,
	});

	const byCandidate = new Map<string, ArtifactInput[]>();
	for (const artifact of artifacts) {
		if (artifact.kind === "attachment" || !artifact.candidateId) continue;
		const list = byCandidate.get(artifact.candidateId) ?? [];
		list.push(artifact);
		byCandidate.set(artifact.candidateId, list);
	}
	for (const candidate of candidates) {
		const files = byCandidate.get(candidate.id) ?? [];
		if (files.length === 0) continue;
		groups.push({
			kind: "candidate",
			label: `#${candidate.rank} ${candidate.title}`,
			candidateId: candidate.id,
			files,
		});
	}

	const byRun = new Map<string, ArtifactInput[]>();
	for (const artifact of artifacts) {
		if (artifact.kind === "attachment" || artifact.candidateId) continue;
		if (!artifact.runId) continue;
		const list = byRun.get(artifact.runId) ?? [];
		list.push(artifact);
		byRun.set(artifact.runId, list);
	}
	for (const run of runs) {
		const files = byRun.get(run.id) ?? [];
		if (files.length === 0) continue;
		groups.push({
			kind: "run",
			label: `run · ${new Date(run.startedAt).toLocaleString()}`,
			runId: run.id,
			startedAt: run.startedAt,
			status: run.status,
			files,
		});
	}

	return groups;
};
