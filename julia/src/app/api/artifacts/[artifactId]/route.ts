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

export async function GET(request: NextRequest, context: RouteContext) {
	const session = await auth.api.getSession({ headers: request.headers });
	if (!session?.user) {
		return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
	}

	const { artifactId } = await context.params;
	const [artifact] = await db
		.select({ r2Key: artifacts.r2Key })
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
	return NextResponse.redirect(signedUrl);
}
