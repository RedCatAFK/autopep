import {
	GetObjectCommand,
	PutObjectCommand,
	type PutObjectCommandInput,
	S3Client,
} from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

import { env } from "@/env";

type ArtifactBody = NonNullable<PutObjectCommandInput["Body"]>;
type SignedUrlOptions = {
	expiresIn: number;
};

type ArtifactStoreCommand = GetObjectCommand | PutObjectCommand;

type ArtifactStoreClient = {
	send(command: ArtifactStoreCommand): Promise<unknown>;
};

type ArtifactStorePresigner = (
	client: ArtifactStoreClient,
	command: GetObjectCommand,
	options: SignedUrlOptions,
) => Promise<string>;

type R2ArtifactStoreConfig = {
	bucket: string;
	client: ArtifactStoreClient;
	presigner?: ArtifactStorePresigner;
	publicBaseUrl?: string | null;
};

type UploadInput = {
	key: string;
	body: ArtifactBody;
	contentType: string;
};

type GetReadUrlInput = {
	key: string;
	expiresInSeconds?: number;
};

type ReadObjectTextInput = {
	key: string;
};

type TransformableBody = {
	transformToString: () => Promise<unknown>;
};

const defaultReadUrlExpirySeconds = 900;

const encodeObjectKey = (key: string) =>
	key.split("/").map(encodeURIComponent).join("/");

const buildPublicReadUrl = (baseUrl: string, key: string) =>
	`${baseUrl.replace(/\/+$/u, "")}/${encodeObjectKey(key)}`;

const getObjectBody = (response: unknown) =>
	response && typeof response === "object" && "Body" in response
		? response.Body
		: undefined;

const isTransformableBody = (body: unknown): body is TransformableBody => {
	if (!body || typeof body !== "object") {
		return false;
	}

	const transformToString = (body as { transformToString?: unknown })
		.transformToString;
	return typeof transformToString === "function";
};

const defaultPresigner: ArtifactStorePresigner = (client, command, options) =>
	getSignedUrl(client as S3Client, command, options);

export const createR2Client = () =>
	new S3Client({
		credentials: {
			accessKeyId: env.R2_ACCESS_KEY_ID,
			secretAccessKey: env.R2_SECRET_ACCESS_KEY,
		},
		endpoint: `https://${env.R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
		region: "auto",
	});

export const createR2ArtifactStore = ({
	bucket,
	client,
	presigner = defaultPresigner,
	publicBaseUrl = env.R2_PUBLIC_BASE_URL,
}: R2ArtifactStoreConfig) => ({
	upload: async ({ key, body, contentType }: UploadInput) => {
		await client.send(
			new PutObjectCommand({
				Body: body,
				Bucket: bucket,
				ContentType: contentType,
				Key: key,
			}),
		);
	},
	getReadUrl: async ({
		key,
		expiresInSeconds = defaultReadUrlExpirySeconds,
	}: GetReadUrlInput) => {
		if (publicBaseUrl) {
			return buildPublicReadUrl(publicBaseUrl, key);
		}

		return presigner(
			client,
			new GetObjectCommand({
				Bucket: bucket,
				Key: key,
			}),
			{ expiresIn: expiresInSeconds },
		);
	},
	readObjectText: async ({ key }: ReadObjectTextInput) => {
		const response = await client.send(
			new GetObjectCommand({
				Bucket: bucket,
				Key: key,
			}),
		);
		const body = getObjectBody(response);

		if (!body) {
			throw new Error(
				`Unable to read R2 object "${key}": response body is missing.`,
			);
		}

		if (!isTransformableBody(body)) {
			throw new Error(
				`Unable to read R2 object "${key}": response body cannot be converted to text.`,
			);
		}

		try {
			const text = await body.transformToString();
			if (typeof text !== "string") {
				throw new TypeError("R2 body transform did not return text.");
			}
			return text;
		} catch (error) {
			throw new Error(
				`Unable to read R2 object "${key}": response body cannot be converted to text.`,
				{ cause: error },
			);
		}
	},
});

const r2Client = createR2Client();

export const r2ArtifactStore = createR2ArtifactStore({
	bucket: env.R2_BUCKET,
	client: r2Client,
});
