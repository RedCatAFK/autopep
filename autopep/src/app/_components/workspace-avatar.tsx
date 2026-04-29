"use client";

const PALETTE = [
	"#cbd736",
	"#9bb24a",
	"#3f7967",
	"#758236",
	"#a87b3b",
	"#5c8c79",
	"#7e6f37",
	"#4a6b59",
] as const;

export const initial = (name: string) => {
	const trimmed = name.trim();
	if (!trimmed) {
		return "?";
	}
	return trimmed.charAt(0).toUpperCase();
};

export const hashColor = (id: string) => {
	let hash = 0;
	for (let i = 0; i < id.length; i += 1) {
		hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
	}
	return PALETTE[hash % PALETTE.length] ?? PALETTE[0];
};

type WorkspaceAvatarProps = {
	active?: boolean;
	id: string;
	name: string;
};

export function WorkspaceAvatar({
	active = false,
	id,
	name,
}: WorkspaceAvatarProps) {
	return (
		<span
			aria-hidden="true"
			className={`flex size-9 items-center justify-center rounded-md font-semibold text-[15px] text-[#1d342e] ${
				active ? "ring-2 ring-[#cbd736] ring-offset-1 ring-offset-[#fbfaf6]" : ""
			}`}
			style={{ backgroundColor: hashColor(id) }}
		>
			{initial(name)}
		</span>
	);
}
