import { NextResponse } from "next/server";

import { env } from "@/env.js";
import { db } from "@/server/db";

import { processAgentMessageWebhook } from "./webhook";

const ALLOWED_ROLES = new Set(["assistant", "system"]);

const UUID_RE =
	/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function POST(request: Request): Promise<NextResponse> {
	const expectedSecret = env.AUTOPEP_MODAL_WEBHOOK_SECRET;
	if (!expectedSecret) {
		return NextResponse.json(
			{ error: "Webhook secret not configured." },
			{ status: 500 },
		);
	}

	const auth = request.headers.get("authorization") ?? "";
	if (auth !== `Bearer ${expectedSecret}`) {
		return NextResponse.json({ error: "Unauthorized." }, { status: 401 });
	}

	let payload: unknown;
	try {
		payload = await request.json();
	} catch {
		return NextResponse.json({ error: "Invalid JSON." }, { status: 400 });
	}

	if (
		!payload ||
		typeof payload !== "object" ||
		!("runId" in payload) ||
		!("threadId" in payload) ||
		!("role" in payload) ||
		!("content" in payload)
	) {
		return NextResponse.json(
			{ error: "Missing required fields." },
			{ status: 422 },
		);
	}

	const typed = payload as {
		runId: unknown;
		threadId: unknown;
		role: unknown;
		content: unknown;
		metadata?: unknown;
	};

	if (
		typeof typed.runId !== "string" ||
		!UUID_RE.test(typed.runId) ||
		typeof typed.threadId !== "string" ||
		!UUID_RE.test(typed.threadId)
	) {
		return NextResponse.json(
			{ error: "runId and threadId must be UUIDs." },
			{ status: 422 },
		);
	}

	if (typeof typed.role !== "string" || !ALLOWED_ROLES.has(typed.role)) {
		return NextResponse.json({ error: "Invalid role." }, { status: 422 });
	}

	if (typeof typed.content !== "string") {
		return NextResponse.json(
			{ error: "content must be a string." },
			{ status: 422 },
		);
	}

	const metadata =
		typed.metadata && typeof typed.metadata === "object"
			? (typed.metadata as Record<string, unknown>)
			: undefined;

	await processAgentMessageWebhook({
		db,
		payload: {
			content: typed.content,
			metadata,
			role: typed.role as "assistant" | "system",
			runId: typed.runId,
			threadId: typed.threadId,
		},
	});

	return NextResponse.json({ ok: true });
}
