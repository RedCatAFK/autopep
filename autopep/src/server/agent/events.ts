import { desc, eq } from "drizzle-orm";

import type { db as appDb } from "@/server/db";
import { agentEvents } from "@/server/db/schema";
import type { AgentEventType } from "./contracts";

type AppendRunEventInput = {
	db: typeof appDb;
	runId: string;
	type: AgentEventType;
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
		.returning();

	if (!event) {
		throw new Error("Failed to append run event.");
	}

	return event;
};
