"use client";

import { WarningCircle } from "@phosphor-icons/react";
import type { PluginUIContext } from "molstar/lib/mol-plugin-ui/context";
import { useEffect, useRef, useState } from "react";

type MolstarViewerProps = {
	artifactId?: string | null;
	candidateId?: string | null;
	label: string;
	onProteinSelection?: (selection: {
		artifactId: string;
		candidateId: string | null;
		label: string;
		selector: Record<string, unknown>;
	}) => void;
	url: string | null;
};

const fitViewer = (plugin: PluginUIContext | null) => {
	if (!plugin) {
		return;
	}

	plugin.handleResize();
	plugin.canvas3d?.requestResize();
	plugin.canvas3d?.requestCameraReset({ durationMs: 0 });
	plugin.managers.camera.reset(undefined, 0);
};

export function MolstarViewer({
	artifactId = null,
	candidateId = null,
	label,
	onProteinSelection,
	url,
}: MolstarViewerProps) {
	const containerRef = useRef<HTMLDivElement>(null);
	const pluginRef = useRef<PluginUIContext | null>(null);
	const selectionRef = useRef({
		artifactId,
		candidateId,
		label,
		onProteinSelection,
	});
	const selectionSubscriptionRef = useRef<{ unsubscribe: () => void } | null>(
		null,
	);
	const loadIdRef = useRef(0);
	const loadQueueRef = useRef<Promise<void>>(Promise.resolve());
	const [error, setError] = useState<string | null>(null);
	const [isLoading, setIsLoading] = useState(false);

	useEffect(() => {
		selectionRef.current = {
			artifactId,
			candidateId,
			label,
			onProteinSelection,
		};
	}, [artifactId, candidateId, label, onProteinSelection]);

	useEffect(() => {
		return () => {
			selectionSubscriptionRef.current?.unsubscribe();
			selectionSubscriptionRef.current = null;
			pluginRef.current?.dispose();
			pluginRef.current = null;
		};
	}, []);

	useEffect(() => {
		const handleViewerAction = (event: Event) => {
			const action = (event as CustomEvent<{ action?: string }>).detail?.action;
			if (action === "Reset" || action === "View") {
				fitViewer(pluginRef.current);
			}
		};

		window.addEventListener("autopep:viewer-action", handleViewerAction);
		return () => {
			window.removeEventListener("autopep:viewer-action", handleViewerAction);
		};
	}, []);

	useEffect(() => {
		let cancelled = false;
		const loadId = loadIdRef.current + 1;
		loadIdRef.current = loadId;
		const isCurrentLoad = () => !cancelled && loadIdRef.current === loadId;

		const loadStructure = async () => {
			if (!url) {
				setError(null);
				setIsLoading(false);
				await pluginRef.current?.clear();
				return;
			}

			if (!containerRef.current) {
				return;
			}

			setError(null);
			setIsLoading(true);

			try {
				const { Asset } = await import("molstar/lib/mol-util/assets");
				const { created, plugin } = await getPlugin(
					containerRef.current,
					pluginRef,
				);
				if (created) {
					selectionSubscriptionRef.current =
						plugin.behaviors.interaction.click.subscribe((event) => {
							const {
								artifactId: currentArtifactId,
								candidateId: currentCandidateId,
								label: currentLabel,
								onProteinSelection: currentOnProteinSelection,
							} = selectionRef.current;
							const loci = event.current?.loci;
							if (!loci || !currentArtifactId || !currentOnProteinSelection) {
								return;
							}

							const selector = serializeLoci(loci);
							if (selector.kind === "empty-loci") {
								return;
							}

							currentOnProteinSelection({
								artifactId: currentArtifactId,
								candidateId: currentCandidateId,
								label: formatSelectionLabel(currentLabel, selector),
								selector,
							});
						});
				}

				if (!isCurrentLoad()) {
					return;
				}

				await plugin.clear();
				if (!isCurrentLoad()) return;

				const data = await plugin.builders.data.download(
					{ isBinary: false, label, url: Asset.Url(url) },
					{ state: { isGhost: true } },
				);
				if (!isCurrentLoad()) return;

				const trajectory = await plugin.builders.structure.parseTrajectory(
					data,
					"mmcif",
				);
				if (!isCurrentLoad()) return;

				await plugin.builders.structure.hierarchy.applyPreset(
					trajectory,
					"default",
					{
						representationPreset: "auto",
						structure: {
							name: "assembly",
							params: { id: "1" },
						},
						showUnitcell: false,
					},
				);
				if (!isCurrentLoad()) return;
				fitViewer(plugin);
				requestAnimationFrame(() => {
					if (isCurrentLoad()) {
						fitViewer(plugin);
					}
				});
			} catch (cause) {
				if (isCurrentLoad()) {
					setError(cause instanceof Error ? cause.message : String(cause));
				}
			} finally {
				if (isCurrentLoad()) {
					setIsLoading(false);
				}
			}
		};

		const queuedLoad = loadQueueRef.current
			.catch(() => undefined)
			.then(loadStructure);
		loadQueueRef.current = queuedLoad.catch(() => undefined);
		void queuedLoad;

		return () => {
			cancelled = true;
		};
	}, [label, url]);

	return (
		<div className="autopep-molstar relative h-full min-h-[430px] overflow-hidden bg-[#f9f8f3] lg:min-h-0">
			<div
				aria-hidden={!url}
				className={`absolute inset-0 transition-opacity duration-300 ${
					url ? "opacity-100" : "opacity-0"
				}`}
				ref={containerRef}
			/>

			{!url ? (
				<div className="flex h-full items-center justify-center text-sm text-[#7a817a]">
					Select a candidate or open a structure file.
				</div>
			) : null}

			{url ? (
				<div className="pointer-events-none absolute top-4 left-4 z-[70] rounded-md border border-[#dfe4d7] bg-[#fffffb]/90 px-3 py-1.5 text-[#38443f] text-xs shadow-[0_10px_30px_-24px_rgba(20,43,35,0.8)] backdrop-blur">
					{label}
				</div>
			) : null}

			{isLoading ? (
				<div className="absolute inset-x-6 bottom-6 z-[3] overflow-hidden rounded-lg border border-[#dfe4d7] bg-[#fffffb]/95 p-3 shadow-[0_16px_44px_-30px_rgba(20,43,35,0.7)]">
					<div className="h-1.5 overflow-hidden rounded-full bg-[#e5eadc]">
						<div className="molstar-loading-bar h-full w-1/2 rounded-full bg-[#dce846]" />
					</div>
					<p className="mt-2 text-[#40504a] text-xs">Loading mmCIF in Mol*</p>
				</div>
			) : null}

			{error ? (
				<div className="absolute right-5 bottom-5 left-5 z-[4] rounded-lg border border-[#f0c5bd] bg-[#fff7f4] p-4 text-[#7b2c20] shadow-[0_18px_50px_-32px_rgba(123,44,32,0.55)]">
					<div className="flex items-start gap-3">
						<WarningCircle className="mt-0.5 shrink-0" size={18} />
						<div>
							<p className="font-semibold text-sm">
								Mol* could not load this CIF
							</p>
							<p className="mt-1 text-xs leading-5">{error}</p>
						</div>
					</div>
				</div>
			) : null}
		</div>
	);
}

function serializeLoci(loci: unknown): Record<string, unknown> {
	const seen = new WeakSet<object>();
	try {
		const raw = JSON.parse(
			JSON.stringify(loci, (_key, value) => {
				if (typeof value === "bigint") {
					return value.toString();
				}
				if (value && typeof value === "object") {
					if (seen.has(value)) {
						return "[Circular]";
					}
					seen.add(value);
				}
				return value;
			}),
		) as Record<string, unknown>;

		return {
			kind: typeof raw.kind === "string" ? raw.kind : "molstar_loci",
			raw,
		};
	} catch (cause) {
		return {
			error: cause instanceof Error ? cause.message : String(cause),
			kind: "molstar_loci",
		};
	}
}

function formatSelectionLabel(
	artifactLabel: string,
	selector: Record<string, unknown>,
) {
	if (typeof selector.kind === "string" && selector.kind !== "molstar_loci") {
		return `${artifactLabel} ${selector.kind.replaceAll("-", " ")}`;
	}

	return `${artifactLabel} selection`;
}

async function getPlugin(
	target: HTMLElement,
	pluginRef: React.MutableRefObject<PluginUIContext | null>,
) {
	if (pluginRef.current) {
		return { created: false, plugin: pluginRef.current };
	}

	const [{ createPluginUI }, { renderReact18 }, { DefaultPluginUISpec }] =
		await Promise.all([
			import("molstar/lib/mol-plugin-ui/index"),
			import("molstar/lib/mol-plugin-ui/react18"),
			import("molstar/lib/mol-plugin-ui/spec"),
		]);
	const baseSpec = DefaultPluginUISpec();
	const plugin = await createPluginUI({
		render: renderReact18,
		spec: {
			...baseSpec,
			components: {
				...baseSpec.components,
				remoteState: "none",
			},
			layout: {
				initial: {
					isExpanded: false,
					showControls: false,
				},
			},
		},
		target,
	});

	pluginRef.current = plugin;
	return { created: true, plugin };
}
