import { describe, expect, it } from "vitest";

import { buildArtifactMetadata } from "./artifact-service";

describe("buildArtifactMetadata", () => {
	it("builds R2 artifact metadata for database insertion", () => {
		expect(
			buildArtifactMetadata({
				byteSize: 1234,
				candidateId: "candidate-1",
				contentType: "chemical/x-cif",
				fileName: "source.cif",
				kind: "mmcif",
				runId: "run-1",
				sha256: "sha256-digest",
				sourceArtifactId: "artifact-source-1",
				storageKey: "projects/workspace-1/runs/run-1/source.cif",
				workspaceId: "workspace-1",
			}),
		).toEqual({
			contentType: "chemical/x-cif",
			kind: "mmcif",
			metadataJson: { candidateId: "candidate-1" },
			name: "source.cif",
			runId: "run-1",
			sha256: "sha256-digest",
			sizeBytes: 1234,
			sourceArtifactId: "artifact-source-1",
			storageKey: "projects/workspace-1/runs/run-1/source.cif",
			storageProvider: "r2",
			workspaceId: "workspace-1",
		});
	});

	it("normalizes nullable artifact fields for schema-compatible inserts", () => {
		expect(
			buildArtifactMetadata({
				byteSize: 120,
				candidateId: null,
				contentType: "chemical/x-pdb",
				fileName: "candidate-1.pdb",
				kind: "pdb",
				runId: "run-1",
				sha256: null,
				sourceArtifactId: null,
				storageKey: "workspaces/w/runs/r/candidate-1.pdb",
				workspaceId: "workspace-1",
			}),
		).toMatchObject({
			metadataJson: { candidateId: null },
			sha256: null,
			sizeBytes: 120,
			sourceArtifactId: null,
		});
	});
});
