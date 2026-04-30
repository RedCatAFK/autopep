"use client";

import { useEffect, useRef, useState } from "react";

import { TextViewer } from "./text-viewer";

export type ViewerArtifact = {
	id: string;
	filename: string;
	contentType?: string | null;
	kind?: string | null;
	viewerUrl?: string | null;
};

type MolstarViewerProps = {
	artifact: ViewerArtifact | null;
};

type MolstarPluginContext = {
	clear: () => Promise<void> | void;
	dispose: () => void;
	builders: {
		data: {
			download: (
				params: { url: unknown; isBinary: boolean },
				options?: Record<string, unknown>,
			) => Promise<unknown>;
		};
		structure: {
			parseTrajectory: (data: unknown, format: string) => Promise<unknown>;
			hierarchy: {
				applyPreset: (
					trajectory: unknown,
					preset: string,
					params?: Record<string, unknown>,
				) => Promise<unknown>;
			};
		};
	};
};

export function MolstarViewer({ artifact }: MolstarViewerProps) {
	const containerRef = useRef<HTMLDivElement | null>(null);
	const pluginRef = useRef<MolstarPluginContext | null>(null);
	const [state, setState] = useState<"empty" | "loading" | "ready" | "error">(
		artifact ? "loading" : "empty",
	);
	const [error, setError] = useState<string | null>(null);
	const isStructure = artifact ? isStructureFilename(artifact.filename) : false;

	useEffect(() => {
		let canceled = false;

		async function loadStructure() {
			if (!artifact?.viewerUrl || !containerRef.current) {
				setState("empty");
				return;
			}

			if (!isStructure) {
				setState("empty");
				setError(null);
				return;
			}

			setState("loading");
			setError(null);

			try {
				const molstar = await import("molstar/lib/mol-plugin-ui");
				const react18 = await import("molstar/lib/mol-plugin-ui/react18");
				const spec = await import("molstar/lib/mol-plugin/spec");
				const assets = await import("molstar/lib/mol-util/assets");
				const format = artifact.filename.toLowerCase().endsWith(".pdb")
					? "pdb"
					: "mmcif";

				if (!pluginRef.current) {
					pluginRef.current = (await molstar.createPluginUI({
						target: containerRef.current,
						render: react18.renderReact18,
						spec: {
							...spec.DefaultPluginSpec(),
							layout: {
								initial: {
									isExpanded: false,
									showControls: false,
								},
							},
							components: {
								remoteState: "none",
							},
						},
					})) as MolstarPluginContext;
				}

				const plugin = pluginRef.current;
				await plugin.clear();
				const data = await plugin.builders.data.download(
					{
						url: assets.Asset.Url(artifact.viewerUrl),
						isBinary: artifact.filename.toLowerCase().endsWith(".bcif"),
					},
					{ state: { isGhost: true } },
				);
				const trajectory = await plugin.builders.structure.parseTrajectory(
					data,
					format,
				);
				await plugin.builders.structure.hierarchy.applyPreset(
					trajectory,
					"default",
					{
						representationPreset: "auto",
						showUnitcell: false,
						structure: { name: "model", params: {} },
					},
				);

				if (!canceled) setState("ready");
			} catch (caught) {
				if (!canceled) {
					setState("error");
					setError(
						caught instanceof Error ? caught.message : "Unable to load Mol*.",
					);
				}
			}
		}

		void loadStructure();

		return () => {
			canceled = true;
		};
	}, [artifact?.viewerUrl, artifact?.filename, isStructure]);

	useEffect(
		() => () => {
			pluginRef.current?.dispose();
			pluginRef.current = null;
		},
		[],
	);

	return (
		<section aria-label="Structure viewer" className="viewer-panel">
			<div className="viewer-toolbar">
				<div>
					<p className="eyebrow">Viewer</p>
					<h2>{artifact?.filename ?? "No artifact selected"}</h2>
				</div>
				{artifact?.viewerUrl ? (
					<a
						className="secondary-button"
						href={artifact.viewerUrl}
						rel="noreferrer"
						target="_blank"
					>
						Open file
					</a>
				) : null}
			</div>
			<div className="molstar-frame">
				<div
					className="molstar-host"
					hidden={!isStructure || state !== "ready"}
					ref={containerRef}
				/>
				{!artifact ? (
					<div className="viewer-state">
						<strong>No artifact selected</strong>
						<p>Choose a file from the artifacts panel.</p>
					</div>
				) : !isStructure ? (
					<TextViewer artifact={artifact} />
				) : state === "loading" ? (
					<div className="viewer-state">
						<strong>Loading structure</strong>
						<p>{artifact.filename}</p>
					</div>
				) : state === "error" ? (
					<div className="viewer-state error">
						<strong>Viewer unavailable</strong>
						<p>{error ?? "Failed to render structure."}</p>
					</div>
				) : null}
			</div>
		</section>
	);
}

function isStructureFilename(filename: string): boolean {
	return /\.(cif|mmcif|pdb|bcif)$/i.test(filename);
}
