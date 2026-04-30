"use client";

import { X } from "lucide-react";

export type WorkspaceContextReference = {
	id: string;
	label: string;
	artifactId?: string | null;
	metadata?: Record<string, unknown> | null;
};

type ContextPillsProps = {
	references: WorkspaceContextReference[];
	onRemove?: (referenceId: string) => void;
	disabled?: boolean;
};

export function ContextPills({
	references,
	onRemove,
	disabled,
}: ContextPillsProps) {
	if (references.length === 0) return null;

	return (
		<fieldset className="context-pills">
			<legend className="sr-only">Selected workspace context</legend>
			{references.map((reference) => (
				<span className="context-pill" key={reference.id}>
					<span className="truncate">{reference.label}</span>
					{onRemove ? (
						<button
							aria-label={`Remove ${reference.label}`}
							className="icon-button small"
							disabled={disabled}
							onClick={() => onRemove(reference.id)}
							type="button"
						>
							<X aria-hidden="true" size={14} />
						</button>
					) : null}
				</span>
			))}
		</fieldset>
	);
}
