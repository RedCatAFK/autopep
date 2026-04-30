import { and, eq } from "drizzle-orm";
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { auth } from "@/server/better-auth";
import { db } from "@/server/db";
import { artifacts, projects } from "@/server/db/schema";
import { createSignedArtifactUrl } from "@/server/r2";

type RouteContext = {
	params: Promise<{ artifactId: string }>;
};

const STREAMABLE_KIND_LIMIT_BYTES = 16 * 1024 * 1024;

/**
 * Serve an artifact's bytes from the same origin as the app so Mol* and the
 * text-preview pane don't need cross-origin headers from R2. We always try to
 * stream the body back; only fall back to a redirect for unreasonably large
 * files (>16 MiB) where proxying would burn Vercel function bandwidth.
 */
export async function GET(request: NextRequest, context: RouteContext) {
	const session = await auth.api.getSession({ headers: request.headers });
	if (!session?.user) {
		return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
	}

	const { artifactId } = await context.params;
	const [artifact] = await db
		.select({
			r2Key: artifacts.r2Key,
			filename: artifacts.filename,
			contentType: artifacts.contentType,
			sizeBytes: artifacts.sizeBytes,
		})
		.from(artifacts)
		.innerJoin(projects, eq(projects.id, artifacts.projectId))
		.where(
			and(eq(artifacts.id, artifactId), eq(projects.ownerId, session.user.id)),
		)
		.limit(1);

	if (!artifact) {
		return NextResponse.json({ error: "Artifact not found" }, { status: 404 });
	}

	const signedUrl = await createSignedArtifactUrl(artifact.r2Key);
	if (
		typeof artifact.sizeBytes === "number" &&
		artifact.sizeBytes > STREAMABLE_KIND_LIMIT_BYTES
	) {
		return NextResponse.redirect(signedUrl);
	}

	const upstream = await fetch(signedUrl);
	if (!upstream.ok || !upstream.body) {
		return NextResponse.json(
			{ error: `R2 fetch failed (${upstream.status})` },
			{ status: 502 },
		);
	}

	const headers = new Headers();
	headers.set(
		"content-type",
		artifact.contentType ?? guessContentType(artifact.filename),
	);
	const upstreamLength = upstream.headers.get("content-length");
	if (upstreamLength) headers.set("content-length", upstreamLength);
	headers.set("cache-control", "private, max-age=300");
	return new NextResponse(upstream.body, { status: 200, headers });
}

function guessContentType(filename: string): string {
	const lower = filename.toLowerCase();
	if (lower.endsWith(".cif") || lower.endsWith(".mmcif"))
		return "chemical/x-mmcif";
	if (lower.endsWith(".pdb")) return "chemical/x-pdb";
	if (lower.endsWith(".bcif")) return "application/octet-stream";
	if (lower.endsWith(".json")) return "application/json";
	if (lower.endsWith(".fa") || lower.endsWith(".fasta")) return "text/x-fasta";
	if (lower.endsWith(".txt") || lower.endsWith(".log") || lower.endsWith(".md"))
		return "text/plain; charset=utf-8";
	return "application/octet-stream";
}
