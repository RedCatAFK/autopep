import { afterEach, describe, expect, it, vi } from "vitest";

type ModalLauncherModule = typeof import("./modal-launcher");

const importModalLauncher = async ({
	secret = "secret-token",
	startUrl = "https://autopep--start-run.modal.run",
}: {
	secret?: string | undefined;
	startUrl?: string | undefined;
} = {}): Promise<ModalLauncherModule> => {
	vi.resetModules();
	vi.doMock("@/env", () => ({
		env: {
			AUTOPEP_MODAL_START_URL: startUrl,
			AUTOPEP_MODAL_WEBHOOK_SECRET: secret,
		},
	}));

	return import("./modal-launcher");
};

describe("startModalRun", () => {
	afterEach(() => {
		vi.doUnmock("@/env");
		vi.resetModules();
	});

	it("sends workspace, thread, and run identifiers to Modal with bearer auth", async () => {
		const fetchImpl = vi.fn().mockResolvedValue(
			new Response(JSON.stringify({ accepted: true, functionCallId: "fc-1" }), {
				headers: { "content-type": "application/json" },
				status: 202,
			}),
		);
		const { startModalRun } = await importModalLauncher();

		await startModalRun({
			fetchImpl,
			runId: "11111111-1111-4111-8111-111111111111",
			threadId: "33333333-3333-4333-8333-333333333333",
			workspaceId: "22222222-2222-4222-8222-222222222222",
		});

		expect(fetchImpl).toHaveBeenCalledWith(
			"https://autopep--start-run.modal.run",
			expect.objectContaining({
				body: JSON.stringify({
					runId: "11111111-1111-4111-8111-111111111111",
					threadId: "33333333-3333-4333-8333-333333333333",
					workspaceId: "22222222-2222-4222-8222-222222222222",
				}),
				headers: expect.objectContaining({
					authorization: "Bearer secret-token",
					"content-type": "application/json",
				}),
				method: "POST",
			}),
		);
	});

	it("throws with Modal response details when the launcher rejects the request", async () => {
		const fetchImpl = vi.fn().mockResolvedValue(
			new Response("bad token", {
				status: 401,
				statusText: "Unauthorized",
			}),
		);
		const { startModalRun } = await importModalLauncher();

		await expect(
			startModalRun({
				fetchImpl,
				runId: "11111111-1111-4111-8111-111111111111",
				threadId: "33333333-3333-4333-8333-333333333333",
				workspaceId: "22222222-2222-4222-8222-222222222222",
			}),
		).rejects.toThrow("Modal launcher failed with 401 Unauthorized: bad token");
	});
});
