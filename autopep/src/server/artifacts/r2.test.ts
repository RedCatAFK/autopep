import { GetObjectCommand, PutObjectCommand } from "@aws-sdk/client-s3";
import { describe, expect, it, vi } from "vitest";

import { createR2ArtifactStore } from "./r2";

describe("createR2ArtifactStore", () => {
	it("uploads objects with the configured bucket and metadata", async () => {
		const sentCommands: unknown[] = [];
		const store = createR2ArtifactStore({
			bucket: "autopep-test",
			client: {
				send: async (command) => {
					sentCommands.push(command);
					return {};
				},
			},
			presigner: vi.fn(),
		});

		await store.upload({
			key: "projects/project-1/runs/run-1/source.cif",
			body: "data_autopep",
			contentType: "chemical/x-cif",
		});

		expect(sentCommands).toHaveLength(1);
		const command = sentCommands[0];
		expect(command).toBeInstanceOf(PutObjectCommand);
		expect((command as PutObjectCommand).input).toMatchObject({
			Bucket: "autopep-test",
			Key: "projects/project-1/runs/run-1/source.cif",
			Body: "data_autopep",
			ContentType: "chemical/x-cif",
		});
	});

	it("signs read URLs with a default 900 second expiry", async () => {
		const presigner = vi
			.fn()
			.mockResolvedValue("https://signed.example/read-url");
		const store = createR2ArtifactStore({
			bucket: "autopep-test",
			client: {
				send: async () => ({}),
			},
			presigner,
			publicBaseUrl: null,
		});

		await expect(
			store.getReadUrl({ key: "projects/project-1/runs/run-1/source.cif" }),
		).resolves.toBe("https://signed.example/read-url");

		expect(presigner).toHaveBeenCalledTimes(1);
		expect(presigner.mock.calls[0]?.[2]).toEqual({ expiresIn: 900 });
	});

	it("uses the configured public base URL without signing", async () => {
		const presigner = vi.fn();
		const store = createR2ArtifactStore({
			bucket: "autopep-test",
			client: {
				send: async () => ({}),
			},
			presigner,
			publicBaseUrl: "https://artifacts.example/base/",
		});

		await expect(
			store.getReadUrl({
				key: "projects/project 1/runs/run-1/source file.cif",
				expiresInSeconds: 60,
			}),
		).resolves.toBe(
			"https://artifacts.example/base/projects/project%201/runs/run-1/source%20file.cif",
		);

		expect(presigner).not.toHaveBeenCalled();
	});

	it("reads object bodies as UTF-8 text", async () => {
		const sentCommands: unknown[] = [];
		const store = createR2ArtifactStore({
			bucket: "autopep-test",
			client: {
				send: async (command) => {
					sentCommands.push(command);
					return {
						Body: {
							transformToString: async () => "data_autopep\n",
						},
					};
				},
			},
			presigner: vi.fn(),
		});

		await expect(
			store.readObjectText({
				key: "projects/project-1/runs/run-1/source.cif",
			}),
		).resolves.toBe("data_autopep\n");

		expect(sentCommands).toHaveLength(1);
		const command = sentCommands[0];
		expect(command).toBeInstanceOf(GetObjectCommand);
		expect((command as GetObjectCommand).input).toMatchObject({
			Bucket: "autopep-test",
			Key: "projects/project-1/runs/run-1/source.cif",
		});
	});

	it("throws a clear error when an object body cannot be read", async () => {
		const missingBodyStore = createR2ArtifactStore({
			bucket: "autopep-test",
			client: {
				send: async () => ({}),
			},
			presigner: vi.fn(),
		});

		await expect(
			missingBodyStore.readObjectText({ key: "missing-body.cif" }),
		).rejects.toThrow(
			'Unable to read R2 object "missing-body.cif": response body is missing.',
		);

		const unreadableBodyStore = createR2ArtifactStore({
			bucket: "autopep-test",
			client: {
				send: async () => ({
					Body: {},
				}),
			},
			presigner: vi.fn(),
		});

		await expect(
			unreadableBodyStore.readObjectText({ key: "unreadable-body.cif" }),
		).rejects.toThrow(
			'Unable to read R2 object "unreadable-body.cif": response body cannot be converted to text.',
		);

		const invalidTextStore = createR2ArtifactStore({
			bucket: "autopep-test",
			client: {
				send: async () => ({
					Body: {
						transformToString: async () => undefined,
					},
				}),
			},
			presigner: vi.fn(),
		});

		await expect(
			invalidTextStore.readObjectText({ key: "invalid-text.cif" }),
		).rejects.toThrow(
			'Unable to read R2 object "invalid-text.cif": response body cannot be converted to text.',
		);
	});
});
