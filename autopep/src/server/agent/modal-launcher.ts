import { env } from "@/env";

type StartModalRunInput = {
	fetchImpl?: typeof fetch;
	projectId: string;
	runId: string;
};

export const startModalRun = async ({
	fetchImpl = fetch,
	projectId,
	runId,
}: StartModalRunInput) => {
	if (!env.AUTOPEP_MODAL_START_URL) {
		throw new Error(
			"AUTOPEP_MODAL_START_URL is required when AUTOPEP_RUNNER_BACKEND=modal.",
		);
	}

	if (!env.AUTOPEP_MODAL_WEBHOOK_SECRET) {
		throw new Error(
			"AUTOPEP_MODAL_WEBHOOK_SECRET is required when AUTOPEP_RUNNER_BACKEND=modal.",
		);
	}

	const response = await fetchImpl(env.AUTOPEP_MODAL_START_URL, {
		body: JSON.stringify({ projectId, runId }),
		headers: {
			authorization: `Bearer ${env.AUTOPEP_MODAL_WEBHOOK_SECRET}`,
			"content-type": "application/json",
		},
		method: "POST",
	});

	if (!response.ok) {
		const body = await response.text().catch(() => "");
		throw new Error(
			`Modal launcher failed with ${response.status} ${response.statusText}: ${
				body || "(empty response)"
			}`,
		);
	}

	const contentType = response.headers.get("content-type") ?? "";
	if (contentType.includes("application/json")) {
		return response.json() as Promise<unknown>;
	}

	return null;
};
