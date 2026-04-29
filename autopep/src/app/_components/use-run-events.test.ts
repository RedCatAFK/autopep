// @vitest-environment jsdom
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useRunEvents } from "./use-run-events";

describe("useRunEvents", () => {
	it("polls until run reaches a terminal status", async () => {
		const fetcher = vi
			.fn()
			.mockResolvedValueOnce({
				events: [
					{
						createdAt: "2026-04-30T10:00:01Z",
						displayJson: { callId: "c1", name: "rcsb" },
						id: "e1",
						sequence: 1,
						type: "tool_call_started",
					},
				],
				runStatus: "running",
			})
			.mockResolvedValueOnce({ events: [], runStatus: "completed" });

		const { result } = renderHook(() =>
			useRunEvents({ fetcher, intervalMs: 5, runId: "run-1" }),
		);

		await waitFor(() => {
			expect(result.current.runStatus).toBe("completed");
		});
		expect(result.current.events).toHaveLength(1);
		expect(result.current.isPolling).toBe(false);
		expect(fetcher).toHaveBeenCalledTimes(2);
	});

	it("returns empty state when runId is null", () => {
		const fetcher = vi.fn();
		const { result } = renderHook(() =>
			useRunEvents({ fetcher, intervalMs: 5, runId: null }),
		);
		expect(result.current.events).toEqual([]);
		expect(result.current.isPolling).toBe(false);
		expect(fetcher).not.toHaveBeenCalled();
	});

	it("advances the cursor so duplicate events are not re-fetched", async () => {
		const fetcher = vi
			.fn()
			.mockResolvedValueOnce({
				events: [
					{
						createdAt: "2026-04-30T10:00:01Z",
						displayJson: {},
						id: "e1",
						sequence: 1,
						type: "tool_call_started",
					},
					{
						createdAt: "2026-04-30T10:00:02Z",
						displayJson: {},
						id: "e2",
						sequence: 2,
						type: "tool_call_completed",
					},
				],
				runStatus: "running",
			})
			.mockResolvedValueOnce({
				events: [
					{
						createdAt: "2026-04-30T10:00:03Z",
						displayJson: {},
						id: "e3",
						sequence: 3,
						type: "run_completed",
					},
				],
				runStatus: "completed",
			});

		const { result } = renderHook(() =>
			useRunEvents({ fetcher, intervalMs: 5, runId: "run-1" }),
		);

		await waitFor(() => {
			expect(result.current.runStatus).toBe("completed");
		});

		expect(result.current.events.map((event) => event.sequence)).toEqual([
			1, 2, 3,
		]);
		expect(fetcher).toHaveBeenNthCalledWith(1, {
			runId: "run-1",
			sinceSequence: 0,
		});
		expect(fetcher).toHaveBeenNthCalledWith(2, {
			runId: "run-1",
			sinceSequence: 2,
		});
	});

	it("resets state when runId changes", async () => {
		const fetcher = vi
			.fn()
			.mockResolvedValueOnce({
				events: [
					{
						createdAt: "2026-04-30T10:00:01Z",
						displayJson: {},
						id: "e1",
						sequence: 1,
						type: "tool_call_started",
					},
				],
				runStatus: "completed",
			})
			.mockResolvedValueOnce({
				events: [
					{
						createdAt: "2026-04-30T10:00:02Z",
						displayJson: {},
						id: "e9",
						sequence: 1,
						type: "tool_call_started",
					},
				],
				runStatus: "completed",
			});

		const { result, rerender } = renderHook(
			({ runId }: { runId: string | null }) =>
				useRunEvents({ fetcher, intervalMs: 5, runId }),
			{ initialProps: { runId: "run-1" as string | null } },
		);

		await waitFor(() => {
			expect(result.current.runStatus).toBe("completed");
		});
		expect(result.current.events.map((e) => e.id)).toEqual(["e1"]);

		rerender({ runId: "run-2" });

		await waitFor(() => {
			expect(result.current.events.map((e) => e.id)).toEqual(["e9"]);
		});
		expect(result.current.runStatus).toBe("completed");
	});
});
