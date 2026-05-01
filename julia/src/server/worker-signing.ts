import { createHmac } from "node:crypto";

const DEFAULT_TOKEN_TTL_SECONDS = 60 * 60 * 6; // 6h

export function signWorkerPayload(rawJson: string, secret: string): string {
	return createHmac("sha256", secret).update(rawJson).digest("hex");
}

/**
 * Mint a token the browser passes to the Modal worker WebSocket.
 *
 * Format: `<runId>.<expiresAtUnix>.<hmacHex>`. Modal verifies the HMAC, the
 * exp, and that the runId in the token matches the URL path. Vercel checks
 * project ownership before minting, so the token is the ownership proof.
 */
export function mintWorkerWebSocketToken(
	runId: string,
	secret: string,
	ttlSeconds: number = DEFAULT_TOKEN_TTL_SECONDS,
): string {
	const expiresAt = Math.floor(Date.now() / 1000) + ttlSeconds;
	const payload = `${runId}.${expiresAt}`;
	const signature = createHmac("sha256", secret).update(payload).digest("hex");
	return `${payload}.${signature}`;
}

/**
 * Derive the WebSocket URL for a run from the configured worker start URL.
 *
 * The start URL is `https://.../runs/start`. The WS URL is at the same host on
 * `/runs/{runId}/events` with `wss://`.
 */
export function buildWorkerWebSocketUrl(
	startUrl: string,
	runId: string,
): string {
	const url = new URL(startUrl);
	url.protocol = url.protocol === "http:" ? "ws:" : "wss:";
	url.pathname = `/runs/${runId}/events`;
	url.search = "";
	return url.toString();
}

export function buildWorkerCancelUrl(startUrl: string): string {
	const url = new URL(startUrl);
	url.pathname = "/runs/cancel";
	url.search = "";
	return url.toString();
}
