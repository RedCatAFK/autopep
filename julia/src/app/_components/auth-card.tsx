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
	const pendingLabel = isSignUp ? "Creating account…" : "Signing in…";

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
			<div className="auth-signed-card">
				<div>
					<p className="auth-card-title">Signed in as {userName}</p>
				</div>
				<button
					className="auth-submit"
					disabled={isPending}
					onClick={handleSignOut}
					type="button"
				>
					{isPending ? "Signing out…" : "Sign out"}
				</button>
				{error ? <AuthError message={error} /> : null}
			</div>
		);
	}

	return (
		<div className="auth-card">
			<header className="auth-card-header">
				<h2 className="auth-card-title">
					{isSignUp ? "Create your account" : "Sign in"}
				</h2>
			</header>
			<div className="auth-modes" role="tablist">
				{modes.map((authMode) => {
					const isActive = mode === authMode.value;

					return (
						<button
							aria-pressed={isActive}
							className={`auth-mode ${isActive ? "active" : ""}`}
							key={authMode.value}
							onClick={() => handleModeChange(authMode.value)}
							role="tab"
							type="button"
						>
							{authMode.label}
						</button>
					);
				})}
			</div>

			<form className="auth-form" onSubmit={handleSubmit}>
				{isSignUp ? (
					<AuthField
						autoComplete="name"
						id="julia-auth-name"
						label="Name"
						onChange={(event) => setName(event.target.value)}
						placeholder="Rosalind Franklin"
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
					placeholder="you@lab.org"
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
					placeholder="At least 8 characters"
					required
					type="password"
					value={password}
				/>
				{error ? <AuthError message={error} /> : null}
				<button className="auth-submit" disabled={isPending} type="submit">
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
		<div className="auth-field">
			<label htmlFor={id}>{label}</label>
			<input id={id} {...props} />
		</div>
	);
}

function AuthError({ message }: { message: string }) {
	return (
		<p className="auth-error" role="alert">
			{message}
		</p>
	);
}
