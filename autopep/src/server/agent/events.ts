import { desc, eq } from "drizzle-orm";

import type { db as appDb } from "@/server/db";
import { agentEvents } from "@/server/db/schema";
import type { AgentEventType } from "./contracts";

type LegacyAgentEventType =
	| "codex_agent_started"
	| "codex_agent_finished"
	| "codex_agent_fallback"
	| "normalizing_target"
	| "searching_structures"
	| "searching_literature"
	| "searching_biorxiv"
	| "ranking_candidates"
	| "downloading_cif"
	| "preparing_cif"
	| "uploading_artifact"
	| "ready_for_proteina"
	| "source_failed"
	| "run_start_skipped";

type AppendRunEventInput = {
	db: typeof appDb;
	runId: string;
	type: AgentEventType | LegacyAgentEventType;
	title: string;
	summary?: string | null;
	display?: Record<string, unknown> | null;
	raw?: Record<string, unknown> | null;
	detail?: string | null;
	payload?: Record<string, unknown> | null;
};

const RUN_EVENT_SEQUENCE_RETRY_ATTEMPTS = 50;
const RUN_EVENT_SEQUENCE_RETRY_BASE_DELAY_MS = 2;
const RUN_EVENT_SEQUENCE_RETRY_JITTER_MS = 4;

export const deriveNextSequence = (latestSequence: number | undefined) =>
	(latestSequence ?? 0) + 1;

const sequenceRetryDelay = (attempt: number) =>
	Math.min(20, RUN_EVENT_SEQUENCE_RETRY_BASE_DELAY_MS * (attempt + 1)) +
	Math.random() * RUN_EVENT_SEQUENCE_RETRY_JITTER_MS;

const wait = (milliseconds: number) =>
	new Promise((resolve) => setTimeout(resolve, milliseconds));

export const appendRunEvent = async ({
	db,
	runId,
	type,
	title,
	summary,
	display,
	raw,
	detail,
	payload,
}: AppendRunEventInput) => {
	for (
		let attempt = 0;
		attempt < RUN_EVENT_SEQUENCE_RETRY_ATTEMPTS;
		attempt += 1
	) {
		const [latestEvent] = await db
			.select({ sequence: agentEvents.sequence })
			.from(agentEvents)
			.where(eq(agentEvents.runId, runId))
			.orderBy(desc(agentEvents.sequence))
			.limit(1);

		const [event] = await db
			.insert(agentEvents)
			.values({
				displayJson: display ?? payload ?? {},
				rawJson: raw ?? {},
				runId,
				sequence: deriveNextSequence(latestEvent?.sequence),
				summary: summary ?? detail ?? null,
				title,
				type,
			})
			.onConflictDoNothing({
				target: [agentEvents.runId, agentEvents.sequence],
			})
			.returning();

		if (event) {
			return event;
		}

		if (attempt < RUN_EVENT_SEQUENCE_RETRY_ATTEMPTS - 1) {
			await wait(sequenceRetryDelay(attempt));
		}
	}

	throw new Error("Failed to append run event after sequence retries.");
};
