import { GetObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

import { env } from "@/env";

const SIGNED_URL_TTL_SECONDS = 60 * 10;

export function getR2Client(): S3Client {
	if (
		!env.R2_ACCOUNT_ID ||
		!env.R2_ACCESS_KEY_ID ||
		!env.R2_SECRET_ACCESS_KEY
	) {
		throw new Error("R2 credentials are not configured");
	}

	return new S3Client({
		credentials: {
			accessKeyId: env.R2_ACCESS_KEY_ID,
			secretAccessKey: env.R2_SECRET_ACCESS_KEY,
		},
		endpoint: `https://${env.R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
		region: "auto",
	});
}

export async function createSignedArtifactUrl(key: string): Promise<string> {
	if (env.R2_PUBLIC_BASE_URL) {
		const baseUrl = env.R2_PUBLIC_BASE_URL.replace(/\/+$/, "");
		return `${baseUrl}/${encodeR2Key(key)}`;
	}

	const command = new GetObjectCommand({
		Bucket: env.R2_BUCKET,
		Key: key,
	});

	return getSignedUrl(getR2Client(), command, {
		expiresIn: SIGNED_URL_TTL_SECONDS,
	});
}

function encodeR2Key(key: string): string {
	return key
		.split("/")
		.map((part) => encodeURIComponent(part))
		.join("/");
}
