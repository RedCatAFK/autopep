import { AuthCard } from "@/app/_components/auth-card";
import { WorkspaceShell } from "@/app/_components/workspace/workspace-shell";
import { getSession } from "@/server/better-auth/server";

export default async function Home() {
	const session = await getSession();

	if (!session) {
		return (
			<main className="grid min-h-dvh place-items-center bg-slate-50 px-4 py-10 text-slate-950">
				<section className="grid w-full max-w-4xl gap-8 md:grid-cols-[minmax(0,1fr)_380px] md:items-center">
					<div>
						<p className="font-semibold text-slate-500 text-sm uppercase tracking-[0.16em]">
							Julia
						</p>
						<h1 className="mt-4 max-w-xl font-semibold text-4xl tracking-tight md:text-5xl">
							Workspace for protein design.
						</h1>
						<p className="mt-4 max-w-lg text-lg text-slate-600">
							Sign in to open your Julia workspace. The full workspace shell is
							coming in the next milestone.
						</p>
					</div>
					<AuthCard />
				</section>
			</main>
		);
	}

	return (
		<WorkspaceShell
			user={{
				email: session.user.email,
				image: session.user.image,
				name: session.user.name,
			}}
		/>
	);
}
