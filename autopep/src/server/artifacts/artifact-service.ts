import type { ArtifactKind } from "@/server/agent/contracts";

type BuildArtifactMetadataInput = {
	byteSize: number;
	candidateId?: string | null;
	contentType: string;
	fileName: string;
	kind: ArtifactKind;
	runId: string;
	sha256?: string | null;
	sourceArtifactId?: string | null;
	storageKey: string;
	workspaceId: string;
};

export const buildArtifactMetadata = ({
	byteSize,
	candidateId,
	contentType,
	fileName,
	kind,
	runId,
	sha256,
	sourceArtifactId,
	storageKey,
	workspaceId,
}: BuildArtifactMetadataInput) => ({
	contentType,
	kind,
	metadataJson: {
		candidateId: candidateId ?? null,
	},
	name: fileName,
	runId,
	sha256: sha256 ?? null,
	sizeBytes: byteSize,
	sourceArtifactId: sourceArtifactId ?? null,
	storageKey,
	storageProvider: "r2" as const,
	workspaceId,
});
