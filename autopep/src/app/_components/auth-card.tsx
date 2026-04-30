"use client";

import { useRouter } from "next/navigation";
import type { FormEvent, InputHTMLAttributes } from "react";
import { useState } from "react";

import { authClient } from "@/server/better-auth/client";

type AuthMode = "sign-in" | "sign-up";

type AuthCardProps = {
	userName?: string;
};

const authModes: Array<{ label: string; value: AuthMode }> = [
	{ label: "Sign in", value: "sign-in" },
	{ label: "Create account", value: "sign-up" },
];

export function AuthCard({ userName }: AuthCardProps) {
	const router = useRouter();
	const [mode, setMode] = useState<AuthMode>("sign-in");
	const [name, setName] = useState("");
	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const [error, setError] = useState<string | null>(null);
	const [isPending, setIsPending] = useState(false);

	const resetForm = () => {
		setName("");
		setEmail("");
		setPassword("");
	};

	const isSignUp = mode === "sign-up";
	const submitLabel = isSignUp ? "Create account" : "Sign in";
	const pendingLabel = isSignUp ? "Creating account..." : "Signing in...";

	const handleModeChange = (nextMode: AuthMode) => {
		setMode(nextMode);
		setError(null);
	};

	const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		setError(null);
		setIsPending(true);

		try {
			if (isSignUp) {
				const { error: signUpError } = await authClient.signUp.email({
					name,
					email,
					password,
				});

				if (signUpError) {
					setError(signUpError.message ?? "Unable to create account.");
					return;
				}
			} else {
				const { error: signInError } = await authClient.signIn.email({
					email,
					password,
				});

				if (signInError) {
					setError(signInError.message ?? "Unable to sign in.");
					return;
				}
			}

			resetForm();
			router.refresh();
		} finally {
			setIsPending(false);
		}
	};

	const handleSignOut = async () => {
		setError(null);
		setIsPending(true);

		try {
			const { error: signOutError } = await authClient.signOut();

			if (signOutError) {
				setError(signOutError.message ?? "Unable to sign out.");
				return;
			}

			router.refresh();
		} finally {
			setIsPending(false);
		}
	};

	if (userName) {
		return (
			<div className="rounded-lg border border-white/10 bg-white/[0.07] p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
				<div className="grid gap-1">
					<p className="font-medium text-[#dbe3d9] text-sm">
						Workspace unlocked
					</p>
					<p className="font-semibold text-2xl text-white tracking-[-0.03em]">
						{userName}
					</p>
				</div>
				<button
					className="mt-5 w-full rounded-md bg-[#e1e95a] px-4 py-3 font-semibold text-[#17211e] text-sm transition duration-300 hover:bg-[#edf47a] active:translate-y-px disabled:cursor-not-allowed disabled:opacity-60"
					disabled={isPending}
					onClick={handleSignOut}
					type="button"
				>
					{isPending ? "Signing out..." : "Sign out"}
				</button>
				{error ? (
					<p className="mt-3 rounded-md border border-[#f2b8a8]/30 bg-[#4c211e]/50 px-3 py-2 text-[#ffd5cd] text-sm">
						{error}
					</p>
				) : null}
			</div>
		);
	}

	return (
		<div className="w-full rounded-lg border border-white/10 bg-[#28322f] p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
			<fieldset className="grid grid-cols-2 gap-1 rounded-md border border-white/10 bg-[#17211e]/70 p-1">
				<legend className="sr-only">Authentication mode</legend>
				{authModes.map((authMode) => {
					const isActive = mode === authMode.value;

					return (
						<button
							aria-pressed={isActive}
							className={`min-w-0 whitespace-nowrap rounded-[6px] px-2.5 py-2.5 text-center font-semibold text-[13px] transition duration-300 focus-visible:outline-0 focus-visible:ring-2 focus-visible:ring-[#e1e95a]/60 active:translate-y-px sm:px-3 sm:text-sm ${
								isActive
									? "bg-[#eef1e6] text-[#17211e] shadow-[0_10px_24px_-20px_rgba(223,233,76,0.75)]"
									: "text-[#b8c2bd] hover:bg-white/[0.06] hover:text-white"
							}`}
							key={authMode.value}
							onClick={() => handleModeChange(authMode.value)}
							type="button"
						>
							{authMode.label}
						</button>
					);
				})}
			</fieldset>
			<form className="mt-5 grid gap-4" onSubmit={handleSubmit}>
				{isSignUp ? (
					<AuthField
						autoComplete="name"
						id="autopep-auth-name"
						label="Name"
						onChange={(event) => setName(event.target.value)}
						placeholder="Your name"
						required
						type="text"
						value={name}
					/>
				) : null}
				<AuthField
					autoComplete="email"
					id="autopep-auth-email"
					label="Email"
					onChange={(event) => setEmail(event.target.value)}
					placeholder="you@lab.org"
					required
					type="email"
					value={email}
				/>
				<AuthField
					autoComplete={isSignUp ? "new-password" : "current-password"}
					helper={isSignUp ? "Use at least 8 characters." : undefined}
					id="autopep-auth-password"
					label="Password"
					minLength={8}
					onChange={(event) => setPassword(event.target.value)}
					placeholder="8+ characters"
					required
					type="password"
					value={password}
				/>
				{error ? (
					<p
						className="rounded-md border border-[#f2b8a8]/30 bg-[#4c211e]/50 px-3 py-2 text-[#ffd5cd] text-sm"
						role="alert"
					>
						{error}
					</p>
				) : null}
				<button
					className="mt-1 rounded-md bg-[#e1e95a] px-4 py-3 font-semibold text-[#17211e] text-sm transition duration-300 hover:bg-[#edf47a] active:translate-y-px disabled:cursor-not-allowed disabled:opacity-60"
					disabled={isPending}
					type="submit"
				>
					{isPending ? pendingLabel : submitLabel}
				</button>
			</form>
		</div>
	);
}

type AuthFieldProps = {
	helper?: string;
	id: string;
	label: string;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "id">;

function AuthField({ helper, id, label, ...props }: AuthFieldProps) {
	const helperId = helper ? `${id}-helper` : undefined;

	return (
		<div className="grid gap-1.5">
			<label
				className="font-medium text-[#d7dfd8] text-[13px] tracking-[-0.01em]"
				htmlFor={id}
			>
				{label}
			</label>
			<input
				aria-describedby={helperId}
				className="h-11 rounded-md border border-white/10 bg-[#17211e]/60 px-3.5 text-sm text-white outline-0 transition duration-300 placeholder:text-[#8f9c95] hover:border-white/20 focus:border-[#e1e95a]/60 focus:bg-[#17211e]/75 focus:ring-2 focus:ring-[#e1e95a]/20"
				id={id}
				{...props}
			/>
			{helper ? (
				<p className="text-[#98a59e] text-xs" id={helperId}>
					{helper}
				</p>
			) : null}
		</div>
	);
}
