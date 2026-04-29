"use client";

import {
	CircleNotch,
	Paperclip,
	PaperPlaneTilt,
	SlidersHorizontal,
	X,
} from "@phosphor-icons/react";
import {
	type ChangeEvent,
	type FormEvent,
	useMemo,
	useRef,
	useState,
} from "react";

import type { AttachmentChip } from "./use-attachment-upload";
import { ChatStream } from "./chat-stream";
import type { StreamItem } from "./chat-stream-item";

export type ChatContextReference = {
	id: string;
	label: string;
};

export type ChatRecipe = {
	enabledByDefault: boolean;
	id: string;
	name: string;
};

export type ChatPanelSendInput = {
	attachmentRefs: string[];
	contextRefs: string[];
	prompt: string;
	recipeRefs: string[];
};

type ChatPanelProps = {
	attachments?: AttachmentChip[];
	contextReferences: ChatContextReference[];
	isDisabled?: boolean;
	isSending: boolean;
	items: StreamItem[];
	onClearAttachments?: () => void;
	onOpenArtifact?: (artifactId: string) => void;
	onOpenCandidate?: (candidateId: string) => void;
	onRemoveAttachment?: (chipId: string) => void;
	onSend: (input: ChatPanelSendInput) => void;
	onUploadAttachments?: (files: File[]) => void;
	recipes: ChatRecipe[];
};

const examples = [
	"Generate a protein that binds to 3CL-protease",
	"Find and prepare a high-quality SARS-CoV-2 spike RBD structure",
	"Explain this part of the protein",
];

const formatBytes = (bytes: number): string => {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const chipClassNameFor = (status: AttachmentChip["status"]) => {
	switch (status) {
		case "ready":
			return "bg-[#eaf4cf] text-[#315419] border-[#cbd736]";
		case "error":
			return "bg-[#fcebe6] text-[#7a2a16] border-[#e7b5a3]";
		case "uploading":
		case "pending":
		default:
			return "bg-[#f0efe8] text-[#52605a] border-[#ddd9cf]";
	}
};

export function ChatPanel({
	attachments = [],
	contextReferences,
	isDisabled = false,
	isSending,
	items,
	onClearAttachments,
	onOpenArtifact,
	onOpenCandidate,
	onRemoveAttachment,
	onSend,
	onUploadAttachments,
	recipes,
}: ChatPanelProps) {
	const [draft, setDraft] = useState("");
	const fileInputRef = useRef<HTMLInputElement | null>(null);
	const selectedRecipeIds = useMemo(
		() =>
			recipes
				.filter((recipe) => recipe.enabledByDefault)
				.map((recipe) => recipe.id),
		[recipes],
	);
	const hasItems = items.length > 0;
	const hasUploading = attachments.some(
		(chip) => chip.status === "pending" || chip.status === "uploading",
	);
	const readyAttachmentRefs = useMemo(
		() =>
			attachments
				.filter((chip) => chip.status === "ready" && chip.artifactId)
				.map((chip) => chip.artifactId as string),
		[attachments],
	);
	const canSend =
		draft.trim().length > 0 && !isSending && !isDisabled && !hasUploading;

	const handlePaperclipClick = () => {
		if (isDisabled) return;
		fileInputRef.current?.click();
	};

	const handleFiles = (event: ChangeEvent<HTMLInputElement>) => {
		const files = event.target.files;
		if (!files || files.length === 0) return;
		const filesArray = Array.from(files);
		// Reset input so re-selecting the same file fires onChange.
		event.target.value = "";
		onUploadAttachments?.(filesArray);
	};

	const submit = (event: FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		const prompt = draft.trim();
		if (!prompt || isSending || isDisabled || hasUploading) {
			return;
		}

		setDraft("");
		onSend({
			attachmentRefs: readyAttachmentRefs,
			contextRefs: contextReferences.map((reference) => reference.id),
			prompt,
			recipeRefs: selectedRecipeIds,
		});
		onClearAttachments?.();
	};

	return (
		<aside className="flex min-h-0 flex-col border-[#e5e2d9] border-r bg-[#fbfaf6]">
			<div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
				{hasItems ? (
					<>
						<ChatStream
							emptyHint="Tool calls, sandbox output, artifacts, and score events will appear here when a run starts."
							items={items}
							onOpenArtifact={onOpenArtifact}
							onOpenCandidate={onOpenCandidate}
						/>
						{isSending ? (
							<div
								aria-live="polite"
								className="mt-3 mr-8 rounded-md border border-[#e1ded4] bg-[#fffef9] px-3 py-2 text-[#4e5953] text-sm"
							>
								<CircleNotch
									aria-hidden="true"
									className="mr-1.5 inline animate-spin"
									size={14}
								/>
								Writing…
							</div>
						) : null}
					</>
				) : (
					<div className="space-y-2" data-testid="chat-empty-state">
						<p className="mb-3 text-[#7a817a] text-xs">Start With A Goal</p>
						{examples.map((example) => (
							<button
								className="w-full rounded-md border border-[#ddd9cf] bg-[#fffef9] px-3 py-3 text-left text-[#26332e] text-sm leading-5 transition-colors duration-200 hover:border-[#c6d335] hover:bg-[#fefff1] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-55"
								disabled={isDisabled}
								key={example}
								onClick={() => setDraft(example)}
								type="button"
							>
								{example}
							</button>
						))}
					</div>
				)}
			</div>

			<form
				className="border-[#e5e2d9] border-t bg-[#fffef9] p-3"
				onSubmit={submit}
			>
				{contextReferences.length > 0 || selectedRecipeIds.length > 0 ? (
					<div className="mb-3 flex flex-wrap gap-1.5">
						{contextReferences.map((reference) => (
							<span
								className="max-w-full truncate rounded-md bg-[#eaf4cf] px-2 py-1 text-[#315419] text-xs"
								key={reference.id}
								title={reference.label}
							>
								{reference.label}
							</span>
						))}
						{recipes
							.filter((recipe) => recipe.enabledByDefault)
							.map((recipe) => (
								<span
									className="max-w-full truncate rounded-md bg-[#f0efe8] px-2 py-1 text-[#52605a] text-xs"
									key={recipe.id}
									title={recipe.name}
								>
									{recipe.name}
								</span>
							))}
					</div>
				) : null}
				{attachments.length > 0 ? (
					<div
						className="mb-3 flex flex-wrap gap-1.5"
						data-testid="chat-attachments"
					>
						{attachments.map((chip) => {
							const showSpinner =
								chip.status === "pending" || chip.status === "uploading";
							const tooltip =
								chip.status === "error"
									? (chip.errorMessage ?? "Upload failed.")
									: `${chip.fileName} · ${formatBytes(chip.byteSize)}`;
							return (
								<span
									className={`flex max-w-full items-center gap-1.5 truncate rounded-md border px-2 py-1 text-xs ${chipClassNameFor(chip.status)}`}
									data-status={chip.status}
									data-testid="chat-attachment-chip"
									key={chip.id}
									title={tooltip}
								>
									{showSpinner ? (
										<CircleNotch
											aria-hidden="true"
											className="animate-spin"
											size={12}
										/>
									) : null}
									<span className="truncate">{chip.fileName}</span>
									<span className="text-[10px] opacity-70">
										{chip.status === "error"
											? "failed"
											: chip.status === "ready"
												? formatBytes(chip.byteSize)
												: chip.status}
									</span>
									{onRemoveAttachment ? (
										<button
											aria-label={`Remove ${chip.fileName}`}
											className="ml-0.5 rounded-sm p-0.5 hover:bg-black/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-1"
											onClick={() => onRemoveAttachment(chip.id)}
											type="button"
										>
											<X aria-hidden="true" size={11} />
										</button>
									) : null}
								</span>
							);
						})}
					</div>
				) : null}
				<input
					accept="*/*"
					className="hidden"
					data-testid="chat-file-input"
					multiple
					onChange={handleFiles}
					ref={fileInputRef}
					type="file"
				/>
				<label
					className="mb-2 block font-medium text-[#49524d] text-xs"
					htmlFor="autopep-chat-input"
				>
					Message Autopep
				</label>
				<textarea
					autoComplete="off"
					className="min-h-24 w-full resize-none rounded-md border border-[#ddd9cf] bg-[#fbfaf6] px-3 py-2 text-[#27322f] text-sm leading-6 outline-none transition-colors duration-200 placeholder:text-[#9ba39c] focus:border-[#cbd736] focus-visible:ring-2 focus-visible:ring-[#dfe94c]/50 disabled:cursor-not-allowed disabled:bg-[#f0efe8] disabled:text-[#747b74]"
					disabled={isDisabled}
					id="autopep-chat-input"
					name="autopep-message"
					onChange={(event) => setDraft(event.target.value)}
					placeholder={
						isDisabled
							? "Create a workspace to send a prompt…"
							: "Describe a target, structure, constraint, or selected region…"
					}
					value={draft}
				/>
				<div className="mt-2 flex items-center justify-between">
					<div className="flex gap-1 text-[#52605a]">
						<button
							aria-label="Attach files"
							className="flex size-9 items-center justify-center rounded-md transition-colors duration-200 hover:bg-[#f0efe8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-40"
							disabled={isDisabled}
							onClick={handlePaperclipClick}
							type="button"
						>
							<Paperclip aria-hidden="true" size={18} />
						</button>
						<button
							aria-label="Run settings"
							className="flex size-9 items-center justify-center rounded-md transition-colors duration-200 hover:bg-[#f0efe8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-40"
							disabled={isDisabled}
							type="button"
						>
							<SlidersHorizontal aria-hidden="true" size={18} />
						</button>
					</div>
					<button
						aria-label="Send message"
						className="flex size-10 items-center justify-center rounded-md bg-[#dfe94c] text-[#1d342e] transition-colors duration-200 hover:bg-[#d4e337] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#a5b51f] focus-visible:outline-offset-2 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50"
						disabled={!canSend}
						type="submit"
					>
						{isSending ? (
							<CircleNotch
								aria-hidden="true"
								className="animate-spin"
								size={18}
							/>
						) : (
							<PaperPlaneTilt aria-hidden="true" size={20} weight="fill" />
						)}
					</button>
				</div>
			</form>
		</aside>
	);
}
