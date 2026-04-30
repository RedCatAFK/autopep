import { describe, expect, it } from "vitest";
import {
	buildArtifactR2Key,
	classifyArtifactKind,
	isStructureArtifact,
} from "./artifacts";

describe("classifyArtifactKind", () => {
	it("classifies common artifact file types", () => {
		expect(classifyArtifactKind("prediction.pdb")).toBe("structure");
		expect(classifyArtifactKind("prediction.cif")).toBe("structure");
		expect(classifyArtifactKind("metadata.json")).toBe("json");
		expect(classifyArtifactKind("sequence.fasta")).toBe("fasta");
		expect(classifyArtifactKind("sequence.fa")).toBe("fasta");
		expect(classifyArtifactKind("worker.log")).toBe("log");
		expect(classifyArtifactKind("notes.txt")).toBe("text");
		expect(classifyArtifactKind("archive.bin")).toBe("other");
	});

	it("uses MIME type when filename extension is not enough", () => {
		expect(classifyArtifactKind("artifact", "application/json")).toBe("json");
		expect(classifyArtifactKind("artifact", "text/x-fasta")).toBe("fasta");
		expect(classifyArtifactKind("artifact", "text/plain")).toBe("text");
	});
});

describe("isStructureArtifact", () => {
	it("recognizes structure artifacts", () => {
		expect(isStructureArtifact("model.pdb")).toBe(true);
		expect(isStructureArtifact("model.mmcif")).toBe(true);
		expect(isStructureArtifact("model.json")).toBe(false);
	});
});

describe("buildArtifactR2Key", () => {
	it("includes sanitized project, run, artifact, and filename parts", () => {
		expect(
			buildArtifactR2Key({
				projectId: "Project 01/alpha",
				runId: "Run:42",
				artifactId: "Artifact#7",
				filename: "final model (A).pdb",
			}),
		).toBe(
			"projects/project-01-alpha/runs/run-42/artifacts/artifact-7/final-model-a.pdb",
		);
	});
});
