"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export type RunEvent = {
	id?: string;
	runId?: string | null;
	type: string;
	message?: string | null;
	sequence: number;
	metadata?: Record<string, unknown> | null;
	createdAt?: string | Date | null;
};

export type RunEventConnectionState =
	| "idle"
	| "connecting"
	| "open"
	| "closed"
	| "error";

export type RunEventSource = {
	runId: string;
	wsUrl: string;
	wsToken: string;
};

type UseRunEventsResult = {
	events: RunEvent[];
	connection: RunEventConnectionState;
	latestSequence: number;
	reset: () => void;
};

const RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 15000;

/**
 * Live event subscription via WebSocket directly to the Modal worker.
 *
 * The browser-to-Modal connection bypasses Vercel's 60s function ceiling, so
 * one connection lasts for the full duration of a 30+ minute protein run. On
 * disconnect (network blip, browser tab sleep) the hook reconnects with
 * `?after=<lastSequence>` so Modal replays missed events from Neon.
 */
export function useRunEvents(
	source: RunEventSource | null,
): UseRunEventsResult {
	const [events, setEvents] = useState<RunEvent[]>([]);
	const [connection, setConnection] = useState<RunEventConnectionState>("idle");
	const [latestSequence, setLatestSequence] = useState(0);
	const latestSequenceRef = useRef(0);
	const closedRef = useRef(false);
	const reconnectAttemptRef = useRef(0);
	const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

	const reset = useCallback(() => {
		setEvents([]);
		setLatestSequence(0);
		latestSequenceRef.current = 0;
		reconnectAttemptRef.current = 0;
	}, []);

	useEffect(() => {
		reset();
	}, [reset]);

	useEffect(() => {
		if (!source || typeof window === "undefined") {
			setConnection("idle");
			return;
		}

		closedRef.current = false;
		let socket: WebSocket | null = null;

		const clearReconnectTimer = () => {
			if (reconnectTimerRef.current) {
				clearTimeout(reconnectTimerRef.current);
				reconnectTimerRef.current = null;
			}
		};

		const scheduleReconnect = () => {
			if (closedRef.current) return;
			const attempt = reconnectAttemptRef.current;
			const delay = Math.min(
				MAX_RECONNECT_DELAY_MS,
				RECONNECT_DELAY_MS * 2 ** attempt,
			);
			reconnectAttemptRef.current = attempt + 1;
			reconnectTimerRef.current = setTimeout(connect, delay);
		};

		const connect = () => {
			if (closedRef.current) return;
			setConnection("connecting");
			const url = `${source.wsUrl}?token=${encodeURIComponent(source.wsToken)}&after=${latestSequenceRef.current}`;
			try {
				socket = new WebSocket(url);
			} catch {
				setConnection("error");
				scheduleReconnect();
				return;
			}

			socket.onopen = () => {
				reconnectAttemptRef.current = 0;
				setConnection("open");
			};

			socket.onmessage = (message) => {
				if (typeof message.data !== "string") return;
				let payload: RunEvent | { type?: string };
				try {
					payload = JSON.parse(message.data) as RunEvent;
				} catch {
					return;
				}
				if (
					payload &&
					typeof payload === "object" &&
					"type" in payload &&
					payload.type === "heartbeat"
				) {
					return;
				}
				const event = payload as RunEvent;
				if (typeof event.sequence !== "number") return;
				latestSequenceRef.current = Math.max(
					latestSequenceRef.current,
					event.sequence,
				);
				setLatestSequence(latestSequenceRef.current);
				setEvents((current) => {
					if (event.id && current.some((row) => row.id === event.id))
						return current;
					return [...current, event].sort((a, b) => a.sequence - b.sequence);
				});
			};

			socket.onerror = () => {
				setConnection("error");
			};

			socket.onclose = (closeEvent) => {
				if (closedRef.current) {
					setConnection("closed");
					return;
				}
				if (closeEvent.code === 4401 || closeEvent.code === 4503) {
					setConnection("error");
					return;
				}
				setConnection("closed");
				scheduleReconnect();
			};
		};

		connect();

		return () => {
			closedRef.current = true;
			clearReconnectTimer();
			if (socket && socket.readyState <= WebSocket.OPEN) {
				socket.close(1000, "client unmount");
			}
		};
	}, [source]);

	return useMemo(
		() => ({ events, connection, latestSequence, reset }),
		[events, connection, latestSequence, reset],
	);
}
