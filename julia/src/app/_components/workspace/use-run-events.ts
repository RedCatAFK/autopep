"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/trpc/react";

export type RunEvent = {
	id: string;
	runId?: string | null;
	type: string;
	message?: string | null;
	sequence: number;
	metadata?: Record<string, unknown> | null;
	createdAt?: string | Date | null;
};

type UseRunEventsResult = {
	events: RunEvent[];
	connection: "idle" | "streaming" | "polling" | "error";
	latestSequence: number;
	appendEvent: (event: RunEvent) => void;
	reset: () => void;
};

export function useRunEvents(runId: string | null): UseRunEventsResult {
	const [events, setEvents] = useState<RunEvent[]>([]);
	const [connection, setConnection] =
		useState<UseRunEventsResult["connection"]>("idle");
	const latestSequenceRef = useRef(0);
	const [latestSequence, setLatestSequence] = useState(0);

	const appendEvent = useCallback((event: RunEvent) => {
		setEvents((current) => {
			if (current.some((item) => item.id === event.id)) return current;
			return [...current, event].sort((a, b) => a.sequence - b.sequence);
		});
		latestSequenceRef.current = Math.max(
			latestSequenceRef.current,
			event.sequence,
		);
		setLatestSequence(latestSequenceRef.current);
	}, []);

	const reset = useCallback(() => {
		setEvents([]);
		latestSequenceRef.current = 0;
		setLatestSequence(0);
		setConnection(runId ? "streaming" : "idle");
	}, [runId]);

	useEffect(() => {
		reset();
	}, [reset]);

	useEffect(() => {
		if (!runId || typeof window === "undefined") return;

		let closed = false;
		const source = new EventSource(
			`/api/runs/${runId}/events?after=${latestSequenceRef.current}`,
		);
		setConnection("streaming");

		const handleEvent = (message: MessageEvent<string>) => {
			if (!message.data || message.data === "[DONE]") return;
			try {
				appendEvent(JSON.parse(message.data) as RunEvent);
			} catch {
				setConnection("error");
			}
		};

		source.onmessage = handleEvent;
		source.addEventListener("run_event", handleEvent);
		source.onerror = () => {
			if (closed) return;
			source.close();
			setConnection("polling");
		};

		return () => {
			closed = true;
			source.close();
		};
	}, [runId, appendEvent]);

	const shouldPoll = Boolean(runId && connection !== "streaming");
	const polledEvents = api.run.listEvents.useQuery(
		{ runId: runId ?? "", after: latestSequence },
		{
			enabled: shouldPoll,
			refetchInterval: shouldPoll ? 1500 : false,
		},
	);

	useEffect(() => {
		const nextEvents = normalizeEvents(polledEvents.data);
		for (const event of nextEvents) appendEvent(event);
		if (polledEvents.error) setConnection("error");
	}, [polledEvents.data, polledEvents.error, appendEvent]);

	return useMemo(
		() => ({
			events,
			connection,
			latestSequence,
			appendEvent,
			reset,
		}),
		[events, connection, latestSequence, appendEvent, reset],
	);
}

function normalizeEvents(value: unknown): RunEvent[] {
	if (!value) return [];
	if (Array.isArray(value)) return value as RunEvent[];
	if (
		typeof value === "object" &&
		value !== null &&
		"events" in value &&
		Array.isArray((value as { events?: unknown }).events)
	) {
		return (value as { events: RunEvent[] }).events;
	}
	return [];
}
