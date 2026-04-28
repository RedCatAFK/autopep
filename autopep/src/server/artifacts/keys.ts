type ArtifactKeyInput = {
	projectId: string;
	runId: string;
	candidateId?: string | null;
	type: string;
	fileName: string;
};

const sanitizePathSegment = (value: string) =>
	value
		.trim()
		.toLowerCase()
		.replace(/[^a-z0-9._-]+/g, "-")
		.replace(/^-+|-+$/g, "");

export const buildArtifactKey = ({
	projectId,
	runId,
	candidateId,
	type,
	fileName,
}: ArtifactKeyInput) => {
	const sanitizedType = sanitizePathSegment(type);
	const sanitizedFileName = sanitizePathSegment(fileName);

	if (candidateId) {
		return `projects/${projectId}/runs/${runId}/candidates/${candidateId}/${sanitizedType}/${sanitizedFileName}`;
	}

	return `projects/${projectId}/runs/${runId}/run-artifacts/${sanitizedType}/${sanitizedFileName}`;
};
