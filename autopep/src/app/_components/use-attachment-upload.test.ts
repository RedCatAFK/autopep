// @vitest-environment jsdom
import { renderHook, waitFor, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { useAttachmentUpload } from "./use-attachment-upload";

const originalFetch = globalThis.fetch;

beforeEach(() => {
	globalThis.fetch = vi.fn(
		async () => new Response(null, { status: 200 }),
	) as typeof fetch;
});

afterEach(() => {
	globalThis.fetch = originalFetch;
});

describe("useAttachmentUpload", () => {
	it("transitions a file through pending → uploading → ready", async () => {
		const createAttachment = vi.fn(async () => ({
			artifactId: "a1",
			uploadUrl: "https://r2.test/put",
			storageKey: "key",
		}));
		const confirmAttachment = vi.fn(async () => ({ ok: true }));

		const { result } = renderHook(() =>
			useAttachmentUpload({
				confirmAttachment,
				createAttachment,
				workspaceId: "11111111-1111-4111-8111-111111111111",
			}),
		);

		const file = new File(["hello"], "ref.pdb", { type: "chemical/x-pdb" });
		await act(async () => {
			await result.current.upload([file]);
		});

		await waitFor(() => {
			expect(result.current.attachments.length).toBe(1);
			expect(result.current.attachments[0]!.status).toBe("ready");
		});
		expect(createAttachment).toHaveBeenCalledWith({
			workspaceId: "11111111-1111-4111-8111-111111111111",
			fileName: "ref.pdb",
			contentType: "chemical/x-pdb",
			byteSize: 5,
		});
		expect(confirmAttachment).toHaveBeenCalledWith({ artifactId: "a1" });
	});

	it("marks the chip as error if R2 PUT fails", async () => {
		globalThis.fetch = vi.fn(
			async () => new Response(null, { status: 500 }),
		) as typeof fetch;
		const createAttachment = vi.fn(async () => ({
			artifactId: "a2",
			uploadUrl: "https://r2.test/put",
			storageKey: "key",
		}));
		const confirmAttachment = vi.fn();

		const { result } = renderHook(() =>
			useAttachmentUpload({
				confirmAttachment,
				createAttachment,
				workspaceId: "11111111-1111-4111-8111-111111111111",
			}),
		);

		const file = new File(["x"], "f.pdb", { type: "" });
		await act(async () => {
			await result.current.upload([file]);
		});

		await waitFor(() => {
			expect(result.current.attachments[0]!.status).toBe("error");
		});
		expect(confirmAttachment).not.toHaveBeenCalled();
	});
});
