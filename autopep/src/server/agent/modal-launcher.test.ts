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

	it("sends the run payload to Modal with bearer auth", async () => {
		const fetchImpl = vi.fn().mockResolvedValue(
			new Response(JSON.stringify({ accepted: true }), {
				headers: { "content-type": "application/json" },
				status: 202,
			}),
		);
		const { startModalRun } = await importModalLauncher();

		await startModalRun({
			fetchImpl,
			projectId: "22222222-2222-4222-8222-222222222222",
			runId: "11111111-1111-4111-8111-111111111111",
		});

		expect(fetchImpl).toHaveBeenCalledWith(
			"https://autopep--start-run.modal.run",
			expect.objectContaining({
				body: JSON.stringify({
					projectId: "22222222-2222-4222-8222-222222222222",
					runId: "11111111-1111-4111-8111-111111111111",
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
				projectId: "22222222-2222-4222-8222-222222222222",
				runId: "11111111-1111-4111-8111-111111111111",
			}),
		).rejects.toThrow("Modal launcher failed with 401 Unauthorized: bad token");
	});
});
