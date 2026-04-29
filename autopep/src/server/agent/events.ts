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
	detail?: string | null;
	payload?: Record<string, unknown>;
};

export const appendRunEvent = async ({
	db,
	runId,
	type,
	title,
	detail = null,
	payload = {},
}: AppendRunEventInput) => {
	for (let attempt = 0; attempt < 5; attempt += 1) {
		const [latestEvent] = await db
			.select({ sequence: agentEvents.sequence })
			.from(agentEvents)
			.where(eq(agentEvents.runId, runId))
			.orderBy(desc(agentEvents.sequence))
			.limit(1);

		const [event] = await db
			.insert(agentEvents)
			.values({
				detail,
				payloadJson: payload,
				runId,
				sequence: (latestEvent?.sequence ?? 0) + 1,
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
	}

	throw new Error("Failed to append run event after sequence retries.");
};
