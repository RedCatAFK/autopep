import { createHmac } from "node:crypto";

export function signWorkerPayload(rawJson: string, secret: string): string {
	return createHmac("sha256", secret).update(rawJson).digest("hex");
}
