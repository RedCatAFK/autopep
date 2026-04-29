"use client";

import { CaretRight, Code, WarningCircle } from "@phosphor-icons/react";
import { useState } from "react";

export type TraceEvent = {
	displayJson: Record<string, unknown>;
	id: string;
	rawJson: Record<string, unknown>;
	sequence: number;
	summary: string | null;
	title: string;
	type: string;
};

type TraceEventCardProps = {
	event: TraceEvent;
};

const eventTone: Record<string, { dot: string; label: string }> = {
	artifact_created: { dot: "bg-[#758236]", label: "Artifact" },
	candidate_ranked: { dot: "bg-[#3f7967]", label: "Candidate" },
	run_completed: { dot: "bg-[#2f7c54]", label: "Complete" },
	run_failed: { dot: "bg-[#a34c39]", label: "Failed" },
	sandbox_stderr_delta: { dot: "bg-[#a34c39]", label: "stderr" },
	sandbox_stdout_delta: { dot: "bg-[#626b62]", label: "stdout" },
	tool_call_completed: { dot: "bg-[#3f7967]", label: "Tool" },
	tool_call_failed: { dot: "bg-[#a34c39]", label: "Tool" },
	tool_call_started: { dot: "bg-[#758236]", label: "Tool" },
};

export function TraceEventCard({ event }: TraceEventCardProps) {
	const [open, setOpen] = useState(false);
	const tone = eventTone[event.type] ?? { dot: "bg-[#8b9187]", label: "Trace" };
	const isFailure =
		event.type.includes("failed") || event.type.includes("stderr");

	return (
		<article className="group border-[#e5e2d9] border-b py-3">
			<button
				aria-expanded={open}
				className="grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 text-left text-[#26332e] transition-colors duration-200 hover:text-[#102c25] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#cbd736] focus-visible:outline-offset-2 active:translate-y-px"
				onClick={() => setOpen((value) => !value)}
				type="button"
			>
				<span className="flex size-7 items-center justify-center rounded-md border border-[#dfddd4] bg-[#fffef9]">
					<CaretRight
						aria-hidden="true"
						className={`transition-transform duration-200 ${open ? "rotate-90" : ""}`}
						size={14}
						weight="bold"
					/>
				</span>
				<span className="min-w-0">
					<span className="flex min-w-0 items-center gap-2">
						<span
							aria-hidden="true"
							className={`size-1.5 shrink-0 rounded-full ${tone.dot}`}
						/>
						<span className="truncate font-medium text-sm">{event.title}</span>
					</span>
					<span className="mt-1 flex items-center gap-2 text-[#747b74] text-xs">
						<span>{tone.label}</span>
						<span aria-hidden="true">/</span>
						<span className="truncate">{event.type}</span>
					</span>
				</span>
				<span className="font-mono text-[#7a817a] text-xs tabular-nums">
					#{event.sequence.toString().padStart(2, "0")}
				</span>
			</button>

			{event.summary ? (
				<p className="mt-2 pl-9 text-[#66706a] text-xs leading-5">
					{event.summary}
				</p>
			) : null}

			{open ? (
				<div className="mt-3 ml-9 rounded-md border border-[#dedbd2] bg-[#f2f1ea]">
					<div className="flex items-center justify-between border-[#dedbd2] border-b px-3 py-2 text-[#535d57] text-xs">
						<span className="flex items-center gap-1.5">
							{isFailure ? (
								<WarningCircle aria-hidden="true" size={14} />
							) : (
								<Code aria-hidden="true" size={14} />
							)}
							Event Payload
						</span>
						<span className="font-mono tabular-nums">
							{event.id.slice(0, 8)}
						</span>
					</div>
					<pre className="max-h-72 overflow-auto p-3 font-mono text-[#27322f] text-[11px] leading-5">
						{JSON.stringify(
							{ display: event.displayJson, raw: event.rawJson },
							null,
							2,
						)}
					</pre>
				</div>
			) : null}
		</article>
	);
}
