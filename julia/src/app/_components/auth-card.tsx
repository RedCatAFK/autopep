"use client";

import { useRouter } from "next/navigation";
import type { FormEvent, InputHTMLAttributes } from "react";
import { useState } from "react";

import { authClient } from "@/server/better-auth/client";

type AuthMode = "sign-in" | "sign-up";

type AuthCardProps = {
	userName?: string | null;
};

const modes: Array<{ label: string; value: AuthMode }> = [
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

			setName("");
			setEmail("");
			setPassword("");
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
			<div className="grid gap-4 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
				<div>
					<p className="font-medium text-slate-500 text-sm">Signed in as</p>
					<p className="mt-1 font-semibold text-lg text-slate-950">
						{userName}
					</p>
				</div>
				<button
					className="rounded-md bg-slate-950 px-4 py-2.5 font-medium text-sm text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
					disabled={isPending}
					onClick={handleSignOut}
					type="button"
				>
					{isPending ? "Signing out..." : "Sign out"}
				</button>
				{error ? <AuthError message={error} /> : null}
			</div>
		);
	}

	return (
		<div className="w-full rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
			<div className="grid grid-cols-2 gap-1 rounded-md bg-slate-100 p-1">
				{modes.map((authMode) => {
					const isActive = mode === authMode.value;

					return (
						<button
							aria-pressed={isActive}
							className={`rounded px-3 py-2 font-medium text-sm transition ${
								isActive
									? "bg-white text-slate-950 shadow-sm"
									: "text-slate-600 hover:text-slate-950"
							}`}
							key={authMode.value}
							onClick={() => handleModeChange(authMode.value)}
							type="button"
						>
							{authMode.label}
						</button>
					);
				})}
			</div>

			<form className="mt-5 grid gap-4" onSubmit={handleSubmit}>
				{isSignUp ? (
					<AuthField
						autoComplete="name"
						id="julia-auth-name"
						label="Name"
						onChange={(event) => setName(event.target.value)}
						required
						type="text"
						value={name}
					/>
				) : null}
				<AuthField
					autoComplete="email"
					id="julia-auth-email"
					label="Email"
					onChange={(event) => setEmail(event.target.value)}
					required
					type="email"
					value={email}
				/>
				<AuthField
					autoComplete={isSignUp ? "new-password" : "current-password"}
					id="julia-auth-password"
					label="Password"
					minLength={8}
					onChange={(event) => setPassword(event.target.value)}
					required
					type="password"
					value={password}
				/>
				{error ? <AuthError message={error} /> : null}
				<button
					className="rounded-md bg-slate-950 px-4 py-2.5 font-medium text-sm text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
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
	id: string;
	label: string;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "id">;

function AuthField({ id, label, ...props }: AuthFieldProps) {
	return (
		<div className="grid gap-1.5">
			<label className="font-medium text-slate-700 text-sm" htmlFor={id}>
				{label}
			</label>
			<input
				className="h-10 rounded-md border border-slate-300 bg-white px-3 text-slate-950 text-sm outline-none transition placeholder:text-slate-400 focus:border-slate-950 focus:ring-2 focus:ring-slate-950/10"
				id={id}
				{...props}
			/>
		</div>
	);
}

function AuthError({ message }: { message: string }) {
	return (
		<p
			className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-red-700 text-sm"
			role="alert"
		>
			{message}
		</p>
	);
}
