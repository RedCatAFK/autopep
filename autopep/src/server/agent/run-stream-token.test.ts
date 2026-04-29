import { describe, expect, it } from "vitest";

import {
	signRunStreamToken,
	verifyRunStreamToken,
} from "./run-stream-token";

const SECRET = "test-secret-32-chars-or-more-for-hmac";

describe("run-stream-token", () => {
	it("round-trips a payload", () => {
		const token = signRunStreamToken({
			payload: {
				runId: "11111111-1111-4111-8111-111111111111",
				userId: "user-1",
			},
			secret: SECRET,
			expiresInSeconds: 3600,
		});
		const decoded = verifyRunStreamToken({ token, secret: SECRET });
		expect(decoded.runId).toBe("11111111-1111-4111-8111-111111111111");
		expect(decoded.userId).toBe("user-1");
	});

	it("rejects a token signed with a different secret", () => {
		const token = signRunStreamToken({
			payload: { runId: "r", userId: "u" },
			secret: SECRET,
			expiresInSeconds: 3600,
		});
		expect(() =>
			verifyRunStreamToken({ token, secret: "wrong" }),
		).toThrow();
	});

	it("rejects an expired token", () => {
		const token = signRunStreamToken({
			payload: { runId: "r", userId: "u" },
			secret: SECRET,
			expiresInSeconds: -10, // past
		});
		expect(() =>
			verifyRunStreamToken({ token, secret: SECRET }),
		).toThrow(/expired/i);
	});
});
