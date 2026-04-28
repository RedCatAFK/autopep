import { PutObjectCommand } from "@aws-sdk/client-s3";
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
});
