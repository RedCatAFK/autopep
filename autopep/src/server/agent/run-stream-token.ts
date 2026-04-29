import { createHmac, timingSafeEqual } from "node:crypto";

const HEADER = Buffer.from(
	JSON.stringify({ alg: "HS256", typ: "JWT" }),
).toString("base64url");

type Payload = {
	runId: string;
	userId: string;
};

type SignArgs = {
	payload: Payload;
	secret: string;
	expiresInSeconds: number;
};

export const signRunStreamToken = ({
	payload,
	secret,
	expiresInSeconds,
}: SignArgs) => {
	const exp = Math.floor(Date.now() / 1000) + expiresInSeconds;
	const body = Buffer.from(JSON.stringify({ ...payload, exp })).toString(
		"base64url",
	);
	const message = `${HEADER}.${body}`;
	const signature = createHmac("sha256", secret)
		.update(message)
		.digest("base64url");
	return `${message}.${signature}`;
};

type VerifyArgs = {
	token: string;
	secret: string;
};

export const verifyRunStreamToken = ({
	token,
	secret,
}: VerifyArgs): Payload & { exp: number } => {
	const parts = token.split(".");
	if (parts.length !== 3) {
		throw new Error("Invalid token format.");
	}
	const [header, body, signature] = parts;
	if (!header || !body || !signature) {
		throw new Error("Invalid token format.");
	}

	const message = `${header}.${body}`;
	const expected = createHmac("sha256", secret)
		.update(message)
		.digest("base64url");

	const expectedBuf = Buffer.from(expected);
	const actualBuf = Buffer.from(signature);
	if (
		expectedBuf.length !== actualBuf.length ||
		!timingSafeEqual(expectedBuf, actualBuf)
	) {
		throw new Error("Invalid token signature.");
	}

	const decoded = JSON.parse(
		Buffer.from(body, "base64url").toString("utf8"),
	) as Payload & { exp: number };
	if (
		typeof decoded.exp !== "number" ||
		decoded.exp < Math.floor(Date.now() / 1000)
	) {
		throw new Error("Token expired.");
	}

	return decoded;
};
