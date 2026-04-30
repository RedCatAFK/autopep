export type ArtifactKind =
	| "structure"
	| "json"
	| "fasta"
	| "log"
	| "text"
	| "other";

type BuildArtifactR2KeyInput = {
	projectId: string;
	runId: string;
	artifactId: string;
	filename: string;
};

const STRUCTURE_EXTENSIONS = new Set(["pdb", "cif", "mmcif", "bcif"]);
const FASTA_EXTENSIONS = new Set(["fasta", "fa", "faa", "fna"]);
const TEXT_EXTENSIONS = new Set(["txt", "md", "csv", "tsv"]);

export function classifyArtifactKind(
	filename: string,
	contentType?: string | null,
): ArtifactKind {
	const extension = filename.split(".").pop()?.toLowerCase();
	const normalizedContentType = contentType?.toLowerCase() ?? "";

	if (extension && STRUCTURE_EXTENSIONS.has(extension)) return "structure";
	if (extension === "json" || normalizedContentType.includes("json")) {
		return "json";
	}
	if (
		(extension && FASTA_EXTENSIONS.has(extension)) ||
		normalizedContentType.includes("fasta")
	) {
		return "fasta";
	}
	if (extension === "log") return "log";
	if (
		(extension && TEXT_EXTENSIONS.has(extension)) ||
		normalizedContentType.startsWith("text/")
	) {
		return "text";
	}

	return "other";
}

export function isStructureArtifact(
	filename: string,
	contentType?: string | null,
): boolean {
	return classifyArtifactKind(filename, contentType) === "structure";
}

export function buildArtifactR2Key({
	projectId,
	runId,
	artifactId,
	filename,
}: BuildArtifactR2KeyInput): string {
	return [
		"projects",
		sanitizeKeyPart(projectId),
		"runs",
		sanitizeKeyPart(runId),
		"artifacts",
		sanitizeKeyPart(artifactId),
		sanitizeKeyPart(filename),
	].join("/");
}

function sanitizeKeyPart(value: string): string {
	const sanitized = value
		.trim()
		.toLowerCase()
		.replace(/[^a-z0-9.]+/g, "-")
		.replace(/-+/g, "-")
		.replace(/-\./g, ".")
		.replace(/^-|-$/g, "");

	return sanitized || "untitled";
}
