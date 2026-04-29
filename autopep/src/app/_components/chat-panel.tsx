"use client";

import {
	CircleNotch,
	Paperclip,
	PaperPlaneTilt,
	SlidersHorizontal,
} from "@phosphor-icons/react";
import { type FormEvent, useMemo, useState } from "react";

import { type TraceEvent, TraceEventCard } from "./trace-event-card";

export type ChatMessage = {
	content: string;
	id: string;
	role: "assistant" | "system" | "user";
};

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
	contextRefs: string[];
	prompt: string;
	recipeRefs: string[];
};

type ChatPanelProps = {
	contextReferences: ChatContextReference[];
	events: TraceEvent[];
	isDisabled?: boolean;
	isSending: boolean;
	messages: ChatMessage[];
	onSend: (input: ChatPanelSendInput) => void;
	recipes: ChatRecipe[];
};

const examples = [
	"Generate a protein that binds to 3CL-protease",
	"Find and prepare a high-quality SARS-CoV-2 spike RBD structure",
	"Explain this part of the protein",
];

export function ChatPanel({
	contextReferences,
	events,
	isDisabled = false,
	isSending,
	messages,
	onSend,
	recipes,
}: ChatPanelProps) {
	const [draft, setDraft] = useState("");
	const selectedRecipeIds = useMemo(
		() =>
			recipes
				.filter((recipe) => recipe.enabledByDefault)
				.map((recipe) => recipe.id),
		[recipes],
	);
	const hasMessages = messages.length > 0;
	const canSend = draft.trim().length > 0 && !isSending && !isDisabled;

	const submit = (event: FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		const prompt = draft.trim();
		if (!prompt || isSending || isDisabled) {
			return;
		}

		setDraft("");
		onSend({
			contextRefs: contextReferences.map((reference) => reference.id),
			prompt,
			recipeRefs: selectedRecipeIds,
		});
	};

	return (
		<aside className="flex min-h-0 flex-col border-[#e5e2d9] border-r bg-[#fbfaf6]">
			<div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
				<header className="mb-5">
					<p className="text-[#7a817a] text-xs uppercase">Agent Workspace</p>
					<h2 className="mt-2 font-semibold text-[#17211e] text-xl">
						Ask Autopep
					</h2>
					<p className="mt-2 text-[#68726c] text-sm leading-6">
						Use the chat as the control surface. Runs, tools, artifacts, and
						scores stay attached to the same ledger.
					</p>
				</header>

				{hasMessages ? (
					<div className="space-y-3">
						{messages.map((message) => (
							<MessageBubble key={message.id} message={message} />
						))}
						{isSending ? (
							<div
								aria-live="polite"
								className="mr-8 rounded-md border border-[#e1ded4] bg-[#fffef9] px-3 py-2 text-[#4e5953] text-sm"
							>
								<CircleNotch
									aria-hidden="true"
									className="mr-1.5 inline animate-spin"
									size={14}
								/>
								Writing…
							</div>
						) : null}
					</div>
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

				<div className="mt-6">
					<div className="mb-2 flex items-center justify-between gap-3">
						<p className="font-medium text-[#3c4741] text-sm">Run Trace</p>
						<p className="font-mono text-[#747b74] text-xs tabular-nums">
							{events.length} event{events.length === 1 ? "" : "s"}
						</p>
					</div>
					{events.length > 0 ? (
						<div className="border-[#e5e2d9] border-t">
							{events.map((event) => (
								<TraceEventCard event={event} key={event.id} />
							))}
						</div>
					) : (
						<div className="rounded-md border border-[#d7d4c9] border-dashed bg-[#fffef9] px-3 py-4 text-[#69716b] text-sm leading-6">
							Tool calls, sandbox output, artifacts, and score events will
							appear here when a run starts.
						</div>
					)}
				</div>
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

function MessageBubble({ message }: { message: ChatMessage }) {
	const isUser = message.role === "user";
	return (
		<div
			className={`break-words rounded-md px-3 py-2 text-sm leading-6 ${
				isUser
					? "ml-8 bg-[#edf4ed] text-[#24302b]"
					: "mr-8 border border-[#e1ded4] bg-[#fffef9] text-[#4e5953]"
			}`}
		>
			{message.content}
		</div>
	);
}
