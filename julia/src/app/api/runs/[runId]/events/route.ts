import { and, asc, eq, gt } from "drizzle-orm";
import type { NextRequest } from "next/server";

import { auth } from "@/server/better-auth";
import { db } from "@/server/db";
import { projects, runEvents, runs } from "@/server/db/schema";

type RouteContext = {
	params: Promise<{ runId: string }>;
};

const encoder = new TextEncoder();
const POLL_INTERVAL_MS = 850;
const MAX_STREAM_MS = 55_000;
const TERMINAL_STATUSES = new Set(["completed", "failed", "canceled"]);

export async function GET(request: NextRequest, context: RouteContext) {
	const session = await auth.api.getSession({ headers: request.headers });
	if (!session?.user) {
		return Response.json({ error: "Unauthorized" }, { status: 401 });
	}

	const { runId } = await context.params;
	const afterSequence = Number.parseInt(
		request.nextUrl.searchParams.get("after") ?? "0",
		10,
	);
	const initialSequence = Number.isFinite(afterSequence) ? afterSequence : 0;

	const [run] = await db
		.select({ id: runs.id, status: runs.status })
		.from(runs)
		.innerJoin(projects, eq(projects.id, runs.projectId))
		.where(and(eq(runs.id, runId), eq(projects.ownerId, session.user.id)))
		.limit(1);

	if (!run) {
		return Response.json({ error: "Run not found" }, { status: 404 });
	}

	let lastSequence = initialSequence;
	const startedAt = Date.now();

	const stream = new ReadableStream({
		async start(controller) {
			controller.enqueue(encoder.encode(": connected\n\n"));

			while (Date.now() - startedAt < MAX_STREAM_MS) {
				const rows = await db
					.select()
					.from(runEvents)
					.where(
						and(
							eq(runEvents.runId, runId),
							gt(runEvents.sequence, lastSequence),
						),
					)
					.orderBy(asc(runEvents.sequence));

				for (const event of rows) {
					lastSequence = Math.max(lastSequence, event.sequence);
					controller.enqueue(encoder.encode(formatRunEvent(event)));
				}

				const [currentRun] = await db
					.select({ status: runs.status })
					.from(runs)
					.where(eq(runs.id, runId))
					.limit(1);

				if (
					rows.length === 0 &&
					currentRun &&
					TERMINAL_STATUSES.has(currentRun.status)
				) {
					break;
				}

				controller.enqueue(encoder.encode(": heartbeat\n\n"));
				await sleep(POLL_INTERVAL_MS);
			}

			controller.close();
		},
	});

	return new Response(stream, {
		headers: {
			"cache-control": "no-cache, no-transform",
			connection: "keep-alive",
			"content-type": "text/event-stream; charset=utf-8",
			"x-accel-buffering": "no",
		},
	});
}

function formatRunEvent(event: typeof runEvents.$inferSelect): string {
	const data = JSON.stringify(event);
	return `event: run-event\ndata: ${data}\n\nevent: run_event\ndata: ${data}\n\n`;
}

function sleep(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}
