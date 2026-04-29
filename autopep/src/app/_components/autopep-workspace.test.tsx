import { describe, expect, it } from "vitest";

import { computeIsLoadingWorkspace } from "./autopep-workspace";

describe("computeIsLoadingWorkspace", () => {
	it("returns true on the very first mount", () => {
		expect(
			computeIsLoadingWorkspace({
				latestIsLoading: true,
				latestIsFetching: true,
				selectedIsLoading: false,
				selectedIsFetching: false,
			}),
		).toBe(true);
	});

	it("returns false during background polling", () => {
		expect(
			computeIsLoadingWorkspace({
				latestIsLoading: false,
				latestIsFetching: true,
				selectedIsLoading: false,
				selectedIsFetching: true,
			}),
		).toBe(false);
	});
});
