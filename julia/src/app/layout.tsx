import "@/styles/globals.css";

import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { TRPCReactProvider } from "@/trpc/react";

export const metadata: Metadata = {
	title: "Julia",
	description: "Protein design workspace",
};

const geist = Geist({
	subsets: ["latin"],
	variable: "--font-geist-sans",
	display: "swap",
});

const geistMono = Geist_Mono({
	subsets: ["latin"],
	variable: "--font-geist-mono",
	display: "swap",
});

export default function RootLayout({
	children,
}: Readonly<{ children: React.ReactNode }>) {
	return (
		<html
			className={`${geist.variable} ${geistMono.variable}`}
			lang="en"
		>
			<body>
				<TRPCReactProvider>{children}</TRPCReactProvider>
			</body>
		</html>
	);
}
