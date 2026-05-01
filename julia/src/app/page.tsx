import { AuthCard } from "@/app/_components/auth-card";
import { WorkspaceShell } from "@/app/_components/workspace/workspace-shell";
import { getSession } from "@/server/better-auth/server";

export default async function Home() {
	const session = await getSession();

	if (!session) {
		return (
			<main className="auth-shell">
				<section className="auth-frame">
					<div>
						<p className="auth-brand">
							{/* eslint-disable-next-line @next/next/no-img-element */}
							<img src="/icon.svg" alt="" width={28} height={28} />
							<span>Julia</span>
						</p>
						<h1 className="auth-title">
							Design proteins with an agent at your <em>side</em>.
						</h1>
						<p className="auth-lede">
							Describe a target in plain English. Julia searches the
							literature, assembles candidate structures, and refines binders.
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
