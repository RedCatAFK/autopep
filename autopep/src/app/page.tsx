import Image from "next/image";

import { AuthCard } from "@/app/_components/auth-card";
import { AutopepWorkspace } from "@/app/_components/autopep-workspace";
import { proteinTargetPreview } from "@/app/_components/protein-preview-image";
import { getSession } from "@/server/better-auth/server";
import { api, HydrateClient } from "@/trpc/server";

export default async function Home() {
	const session = await getSession();

	if (session) {
		void api.workspace.getLatestWorkspace.prefetch();
	}

	if (!session) {
		return (
			<main className="grid min-h-[100dvh] place-items-center bg-[#f8f7f2] px-4 py-8 text-[#17211e]">
				<div className="grid w-full max-w-5xl overflow-hidden rounded-lg border border-[#ddd9ce] bg-[#fffef9] shadow-[0_28px_90px_-66px_rgba(25,39,33,0.82)] md:grid-cols-[minmax(0,1fr)_420px]">
					<section className="relative min-h-[430px] overflow-hidden p-8 md:p-10">
						<div className="flex items-center gap-3">
							<div className="relative size-8 rounded-md border border-[#cfd8cc] bg-[#fffef9]">
								<div className="absolute inset-[6px] bg-[#0b715f] [clip-path:polygon(25%_5%,75%_5%,100%_50%,75%_95%,25%_95%,0_50%)]" />
								<div className="absolute inset-[9px] bg-[#fffef9] [clip-path:polygon(25%_5%,75%_5%,100%_50%,75%_95%,25%_95%,0_50%)]" />
								<div className="absolute right-[5px] bottom-[5px] size-2 rounded-full bg-[#dfe94c]" />
							</div>
							<p className="font-semibold text-[21px] tracking-[-0.02em]">
								Julia
							</p>
						</div>
						<div className="relative mt-14 max-w-[390px]">
							<h1 className="font-semibold text-4xl text-[#17211e] leading-[1.05] tracking-[-0.04em]">
								A molecular studio for protein design.
							</h1>
							<p className="mt-4 text-[#646d66] leading-7">
								Sign in to search RCSB and literature, rank target structures,
								and stage CIF files for downstream binder design.
							</p>
						</div>
						<Image
							alt="Generated protein structure preview"
							className="mt-8 ml-auto h-auto w-[285px] rounded-[34px] object-contain opacity-[0.88] mix-blend-multiply shadow-[0_26px_70px_-48px_rgba(14,64,52,0.75)] md:absolute md:right-[-72px] md:bottom-[-40px] md:mt-0 md:w-[350px]"
							priority
							sizes="(min-width: 768px) 350px, 285px"
							src={proteinTargetPreview}
						/>
					</section>
					<section className="flex bg-[#17211e] p-6 text-white md:p-8">
						<div className="mx-auto flex w-full max-w-sm flex-col justify-center">
							<p className="mb-5 font-medium text-[#dbe3d9] text-sm tracking-[-0.01em]">
								Open your Julia workspace.
							</p>
							<AuthCard />
						</div>
					</section>
				</div>
			</main>
		);
	}

	return (
		<HydrateClient>
			<AutopepWorkspace
				account={{
					email: session.user.email,
					name: session.user.name,
				}}
			/>
		</HydrateClient>
	);
}
