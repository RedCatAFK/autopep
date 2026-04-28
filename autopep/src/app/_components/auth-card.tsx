"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { authClient } from "@/server/better-auth/client";

type AuthMode = "sign-in" | "sign-up";

type AuthCardProps = {
	userName?: string;
};

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

	const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		setError(null);
		setIsPending(true);

		try {
			if (mode === "sign-up") {
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
			<div className="flex flex-col items-center gap-4">
				<p className="text-center text-2xl text-white">
					Logged in as {userName}
				</p>
				<button
					className="rounded-full bg-white/10 px-10 py-3 font-semibold transition hover:bg-white/20 disabled:cursor-not-allowed disabled:opacity-60"
					disabled={isPending}
					onClick={handleSignOut}
					type="button"
				>
					{isPending ? "Signing out..." : "Sign out"}
				</button>
				{error ? <p className="text-red-200 text-sm">{error}</p> : null}
			</div>
		);
	}

	return (
		<div className="w-full max-w-sm rounded-2xl bg-white/10 p-6">
			<div className="mb-4 flex gap-2">
				<button
					className="rounded-full px-4 py-2 font-semibold text-sm transition hover:bg-white/10"
					onClick={() => {
						setMode("sign-in");
						setError(null);
					}}
					type="button"
				>
					Sign in
				</button>
				<button
					className="rounded-full px-4 py-2 font-semibold text-sm transition hover:bg-white/10"
					onClick={() => {
						setMode("sign-up");
						setError(null);
					}}
					type="button"
				>
					Create account
				</button>
			</div>
			<form className="flex flex-col gap-3" onSubmit={handleSubmit}>
				{mode === "sign-up" ? (
					<input
						autoComplete="name"
						className="rounded-full bg-white/10 px-4 py-2 text-white placeholder:text-white/60"
						onChange={(event) => setName(event.target.value)}
						placeholder="Name"
						required
						type="text"
						value={name}
					/>
				) : null}
				<input
					autoComplete="email"
					className="rounded-full bg-white/10 px-4 py-2 text-white placeholder:text-white/60"
					onChange={(event) => setEmail(event.target.value)}
					placeholder="Email"
					required
					type="email"
					value={email}
				/>
				<input
					autoComplete={
						mode === "sign-up" ? "new-password" : "current-password"
					}
					className="rounded-full bg-white/10 px-4 py-2 text-white placeholder:text-white/60"
					minLength={8}
					onChange={(event) => setPassword(event.target.value)}
					placeholder="Password"
					required
					type="password"
					value={password}
				/>
				<button
					className="rounded-full bg-white/10 px-10 py-3 font-semibold transition hover:bg-white/20 disabled:cursor-not-allowed disabled:opacity-60"
					disabled={isPending}
					type="submit"
				>
					{isPending
						? mode === "sign-up"
							? "Creating account..."
							: "Signing in..."
						: mode === "sign-up"
							? "Create account"
							: "Sign in"}
				</button>
			</form>
			{error ? <p className="mt-3 text-red-200 text-sm">{error}</p> : null}
		</div>
	);
}
