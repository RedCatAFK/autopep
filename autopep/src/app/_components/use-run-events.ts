import { useEffect, useRef, useState } from "react";

export type RunEvent = {
	id: string;
	sequence: number;
	type: string;
	createdAt: string;
	displayJson: Record<string, unknown>;
};

export type RunEventsFetcher = (input: {
	runId: string;
	sinceSequence: number;
}) => Promise<{
	events: RunEvent[];
	runStatus: string;
}>;

type RunEventsArgs = {
	fetcher: RunEventsFetcher;
	intervalMs?: number;
	runId: string | null;
};

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

const isTerminal = (status: string | null): boolean =>
	status !== null && TERMINAL_STATUSES.has(status);

export function useRunEvents({
	fetcher,
	intervalMs = 800,
	runId,
}: RunEventsArgs) {
	const [events, setEvents] = useState<RunEvent[]>([]);
	const [runStatus, setRunStatus] = useState<string | null>(null);
	const sinceRef = useRef(0);
	const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

	const isPolling = runId !== null && !isTerminal(runStatus);

	useEffect(() => {
		setEvents([]);
		setRunStatus(null);
		sinceRef.current = 0;

		if (!runId) {
			return;
		}

		let cancelled = false;

		const tick = async () => {
			try {
				const result = await fetcher({
					runId,
					sinceSequence: sinceRef.current,
				});
				if (cancelled) {
					return;
				}
				if (result.events.length > 0) {
					const lastSeq =
						result.events[result.events.length - 1]?.sequence ?? 0;
					sinceRef.current = Math.max(sinceRef.current, lastSeq);
					setEvents((prev) => [...prev, ...result.events]);
				}
				setRunStatus(result.runStatus);
				if (!isTerminal(result.runStatus)) {
					timerRef.current = setTimeout(tick, intervalMs);
				}
			} catch {
				if (!cancelled) {
					timerRef.current = setTimeout(tick, intervalMs * 2);
				}
			}
		};

		void tick();

		return () => {
			cancelled = true;
			if (timerRef.current) {
				clearTimeout(timerRef.current);
				timerRef.current = null;
			}
		};
	}, [runId, fetcher, intervalMs]);

	return { events, isPolling, runStatus };
}
