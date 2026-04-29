"use client";

import { useState, type ReactNode } from "react";

type HoverTooltipProps = {
	children: ReactNode;
	label: string;
	side?: "right" | "top" | "bottom";
};

export function HoverTooltip({ children, label, side = "right" }: HoverTooltipProps) {
	const [open, setOpen] = useState(false);

	return (
		<span
			className="relative"
			onMouseEnter={() => setOpen(true)}
			onMouseLeave={() => setOpen(false)}
			onFocus={() => setOpen(true)}
			onBlur={() => setOpen(false)}
		>
			{children}
			{open ? (
				<span
					className={`pointer-events-none absolute z-20 whitespace-nowrap rounded-md bg-[#17211e] px-2 py-1 text-[#fffef9] text-xs shadow-lg ${
						side === "right" ? "left-full top-1/2 ml-2 -translate-y-1/2" : ""
					} ${side === "top" ? "left-1/2 bottom-full mb-2 -translate-x-1/2" : ""} ${
						side === "bottom" ? "left-1/2 top-full mt-2 -translate-x-1/2" : ""
					}`}
					role="tooltip"
				>
					{label}
				</span>
			) : null}
		</span>
	);
}
