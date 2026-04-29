"use client";

import { ChatStreamItem, type StreamItem } from "./chat-stream-item";

type ChatStreamProps = {
	emptyHint?: string;
	items: StreamItem[];
	onOpenArtifact?: (artifactId: string) => void;
	onOpenCandidate?: (candidateId: string) => void;
};

export function ChatStream({
	emptyHint = "No messages yet.",
	items,
	onOpenArtifact,
	onOpenCandidate,
}: ChatStreamProps) {
	if (items.length === 0) {
		return <p className="text-[#7a817a] text-sm">{emptyHint}</p>;
	}
	return (
		<div className="space-y-3">
			{items.map((item) => (
				<ChatStreamItem
					item={item}
					key={item.id}
					onOpenArtifact={onOpenArtifact}
					onOpenCandidate={onOpenCandidate}
				/>
			))}
		</div>
	);
}
