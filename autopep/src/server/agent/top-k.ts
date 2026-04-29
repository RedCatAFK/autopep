export const defaultTopK = 5;

const getRecord = (value: unknown): Record<string, unknown> =>
	value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};

export const resolveRequestedTopK = (sdkStateJson: unknown): number => {
	const requestedTopK = getRecord(sdkStateJson).requestedTopK;

	if (
		typeof requestedTopK === "number" &&
		Number.isInteger(requestedTopK) &&
		requestedTopK > 0
	) {
		return requestedTopK;
	}

	return defaultTopK;
};
