"use client";

import { useCallback, useState } from "react";

type AttachmentStatus = "pending" | "uploading" | "ready" | "error";

export type AttachmentChip = {
	id: string;
	artifactId?: string;
	fileName: string;
	byteSize: number;
	status: AttachmentStatus;
	errorMessage?: string;
};

type CreateAttachmentInput = {
	workspaceId: string;
	fileName: string;
	contentType: string;
	byteSize: number;
};

type CreateAttachmentResult = {
	artifactId: string;
	uploadUrl: string;
	storageKey: string;
};

type UseAttachmentUploadArgs = {
	confirmAttachment: (input: { artifactId: string }) => Promise<{ ok: boolean }>;
	createAttachment: (
		input: CreateAttachmentInput,
	) => Promise<CreateAttachmentResult>;
	workspaceId: string | null;
};

export function useAttachmentUpload({
	confirmAttachment,
	createAttachment,
	workspaceId,
}: UseAttachmentUploadArgs) {
	const [attachments, setAttachments] = useState<AttachmentChip[]>([]);

	const updateChip = useCallback(
		(id: string, patch: Partial<AttachmentChip>) => {
			setAttachments((prev) =>
				prev.map((chip) => (chip.id === id ? { ...chip, ...patch } : chip)),
			);
		},
		[],
	);

	const remove = useCallback((id: string) => {
		setAttachments((prev) => prev.filter((chip) => chip.id !== id));
	}, []);

	const clear = useCallback(() => {
		setAttachments([]);
	}, []);

	const upload = useCallback(
		async (files: File[]) => {
			if (!workspaceId) return;
			const newChips = files.map((file) => ({
				id: crypto.randomUUID(),
				fileName: file.name,
				byteSize: file.size,
				status: "pending" as const,
			}));
			setAttachments((prev) => [...prev, ...newChips]);

			await Promise.all(
				newChips.map(async (chip, index) => {
					const file = files[index]!;
					updateChip(chip.id, { status: "uploading" });
					try {
						const created = await createAttachment({
							workspaceId,
							fileName: file.name,
							contentType: file.type || "application/octet-stream",
							byteSize: file.size,
						});
						const putResponse = await fetch(created.uploadUrl, {
							method: "PUT",
							body: file,
							headers: file.type ? { "Content-Type": file.type } : {},
						});
						if (!putResponse.ok) {
							throw new Error(`Upload failed (${putResponse.status})`);
						}
						await confirmAttachment({ artifactId: created.artifactId });
						updateChip(chip.id, {
							status: "ready",
							artifactId: created.artifactId,
						});
					} catch (error) {
						updateChip(chip.id, {
							status: "error",
							errorMessage:
								error instanceof Error ? error.message : "Upload failed.",
						});
					}
				}),
			);
		},
		[workspaceId, createAttachment, confirmAttachment, updateChip],
	);

	return { attachments, upload, remove, clear };
}
