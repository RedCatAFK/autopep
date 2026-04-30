// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
	archiveRecipeMutate: vi.fn(),
	archiveWorkspaceMutate: vi.fn(),
	confirmAttachmentMutateAsync: vi.fn(),
	createAttachmentMutateAsync: vi.fn(),
	createContextReferenceMutate: vi.fn(),
	createContextReferenceOptions: undefined as
		| { onSuccess?: (...args: unknown[]) => Promise<void> | void }
		| undefined,
	createRecipeMutate: vi.fn(),
	deleteAttachmentMutate: vi.fn(),
	deleteAttachmentOptions: undefined as
		| { onSuccess?: (...args: unknown[]) => Promise<void> | void }
		| undefined,
	deleteContextReferenceMutate: vi.fn(),
	deleteContextReferenceOptions: undefined as
		| { onSuccess?: (...args: unknown[]) => Promise<void> | void }
		| undefined,
	getLatestWorkspaceInvalidate: vi.fn().mockResolvedValue(undefined),
	getWorkspaceInvalidate: vi.fn().mockResolvedValue(undefined),
	listWorkspacesInvalidate: vi.fn().mockResolvedValue(undefined),
	renameWorkspaceMutate: vi.fn(),
	routerRefresh: vi.fn(),
	sendMessageMutate: vi.fn(),
	signOut: vi.fn(),
	updateRecipeMutate: vi.fn(),
}));

vi.mock("next/navigation", () => ({
	useRouter: () => ({ refresh: mocks.routerRefresh }),
}));

vi.mock("@/server/better-auth/client", () => ({
	authClient: { signOut: mocks.signOut },
}));

vi.mock("@/trpc/react", () => ({
	api: {
		useUtils: () => ({
			workspace: {
				getLatestWorkspace: { invalidate: mocks.getLatestWorkspaceInvalidate },
				getWorkspace: { invalidate: mocks.getWorkspaceInvalidate },
				listWorkspaces: { invalidate: mocks.listWorkspacesInvalidate },
			},
		}),
		workspace: {
			archiveRecipe: {
				useMutation: () => ({
					isPending: false,
					mutate: mocks.archiveRecipeMutate,
				}),
			},
			archiveWorkspace: {
				useMutation: () => ({
					isPending: false,
					mutate: mocks.archiveWorkspaceMutate,
				}),
			},
			confirmAttachment: {
				useMutation: () => ({
					isPending: false,
					mutateAsync: mocks.confirmAttachmentMutateAsync,
				}),
			},
			createAttachment: {
				useMutation: () => ({
					isPending: false,
					mutateAsync: mocks.createAttachmentMutateAsync,
				}),
			},
			createContextReference: {
				useMutation: (
					options?: { onSuccess?: (...args: unknown[]) => Promise<void> | void },
				) => {
					mocks.createContextReferenceOptions = options;
					return {
						isPending: false,
						mutate: mocks.createContextReferenceMutate,
					};
				},
			},
			createRecipe: {
				useMutation: () => ({
					isPending: false,
					mutate: mocks.createRecipeMutate,
				}),
			},
			deleteAttachment: {
				useMutation: (options?: {
					onSuccess?: (...args: unknown[]) => Promise<void> | void;
				}) => {
					mocks.deleteAttachmentOptions = options;
					return {
						isPending: false,
						mutate: mocks.deleteAttachmentMutate,
					};
				},
			},
			deleteContextReference: {
				useMutation: (
					options?: { onSuccess?: (...args: unknown[]) => Promise<void> | void },
				) => {
					mocks.deleteContextReferenceOptions = options;
					return {
						isPending: false,
						mutate: mocks.deleteContextReferenceMutate,
					};
				},
			},
			getLatestWorkspace: {
				useQuery: () => ({
					data: {
						activeRun: null,
						artifacts: [
							{
								byteSize: 512,
								candidateId: null,
								fileName: "spec.pdf",
								id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
								kind: "attachment",
								name: "spec.pdf",
								runId: null,
								signedUrl: "https://example.test/spec.pdf",
								sourceUrl: null,
								type: "attachment",
							},
						],
						candidateScores: [],
						candidates: [],
						contextReferences: [
							{
								id: "55555555-5555-4555-8555-555555555555",
								label: "6M0J chain A residue 145",
							},
						],
						events: [],
						messages: [],
						recipes: [],
						runs: [],
						workspace: {
							description: null,
							id: "22222222-2222-4222-8222-222222222222",
							name: "3CL workspace",
						},
					},
					isFetching: false,
					isLoading: false,
				}),
			},
			getWorkspace: {
				useQuery: () => ({
					data: undefined,
					isFetching: false,
					isLoading: false,
				}),
			},
			listWorkspaces: {
				useQuery: () => ({
					data: [
						{
							description: null,
							id: "22222222-2222-4222-8222-222222222222",
							name: "3CL workspace",
						},
					],
					isFetching: false,
					isLoading: false,
				}),
			},
			renameWorkspace: {
				useMutation: () => ({
					isPending: false,
					mutate: mocks.renameWorkspaceMutate,
				}),
			},
			sendMessage: {
				useMutation: () => ({
					isPending: false,
					mutate: mocks.sendMessageMutate,
				}),
			},
			updateRecipe: {
				useMutation: () => ({
					isPending: false,
					mutate: mocks.updateRecipeMutate,
				}),
			},
		},
	},
}));

vi.mock("./workspace-shell", () => ({
	WorkspaceShell: (props: {
		onDeleteAttachment?: (artifactId: string) => void;
		onProteinSelection?: (selection: {
			artifactId: string;
			candidateId: string | null;
			label: string;
			selector: Record<string, unknown>;
		}) => void;
		onRemoveContextReference?: (referenceId: string) => void;
	}) => (
		<>
			<button
				onClick={() =>
					props.onDeleteAttachment?.("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
				}
				type="button"
			>
				Delete attachment
			</button>
			<button
				onClick={() =>
					props.onProteinSelection?.({
						artifactId: "11111111-1111-4111-8111-111111111111",
						candidateId: "33333333-3333-4333-8333-333333333333",
						label: "6M0J chain A residue 145",
						selector: {
							authAsymId: "A",
							residueRanges: [{ end: 145, start: 145 }],
						},
					})
				}
				type="button"
			>
				Select protein region
			</button>
			<button
				onClick={() =>
					props.onRemoveContextReference?.(
						"55555555-5555-4555-8555-555555555555",
					)
				}
				type="button"
			>
				Remove context
			</button>
		</>
	),
}));

import {
	AutopepWorkspace,
	computeIsLoadingWorkspace,
} from "./autopep-workspace";

describe("computeIsLoadingWorkspace", () => {
	it("returns true on the very first mount", () => {
		expect(
			computeIsLoadingWorkspace({
				latestIsLoading: true,
				latestIsFetching: true,
				selectedIsLoading: false,
				selectedIsFetching: false,
			}),
		).toBe(true);
	});

	it("returns false during background polling", () => {
		expect(
			computeIsLoadingWorkspace({
				latestIsLoading: false,
				latestIsFetching: true,
				selectedIsLoading: false,
				selectedIsFetching: true,
			}),
		).toBe(false);
	});
});

describe("AutopepWorkspace", () => {
	beforeEach(() => {
		mocks.archiveRecipeMutate.mockClear();
		mocks.archiveWorkspaceMutate.mockClear();
		mocks.confirmAttachmentMutateAsync.mockClear();
		mocks.createAttachmentMutateAsync.mockClear();
		mocks.createContextReferenceMutate.mockClear();
		mocks.createContextReferenceOptions = undefined;
		mocks.createRecipeMutate.mockClear();
		mocks.deleteAttachmentMutate.mockClear();
		mocks.deleteAttachmentOptions = undefined;
		mocks.deleteContextReferenceMutate.mockClear();
		mocks.deleteContextReferenceOptions = undefined;
		mocks.getLatestWorkspaceInvalidate.mockClear();
		mocks.getWorkspaceInvalidate.mockClear();
		mocks.listWorkspacesInvalidate.mockClear();
		mocks.renameWorkspaceMutate.mockClear();
		mocks.routerRefresh.mockClear();
		mocks.sendMessageMutate.mockClear();
		mocks.signOut.mockClear();
		mocks.updateRecipeMutate.mockClear();
	});

	it("deletes attachment artifacts and refreshes workspace data", async () => {
		render(<AutopepWorkspace />);

		fireEvent.click(screen.getByRole("button", { name: "Delete attachment" }));

		expect(mocks.deleteAttachmentMutate).toHaveBeenCalledWith({
			artifactId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
		});

		await mocks.deleteAttachmentOptions?.onSuccess?.();

		expect(mocks.listWorkspacesInvalidate).toHaveBeenCalledOnce();
		expect(mocks.getLatestWorkspaceInvalidate).toHaveBeenCalledOnce();
		expect(mocks.getWorkspaceInvalidate).toHaveBeenCalledWith({
			workspaceId: "22222222-2222-4222-8222-222222222222",
		});
	});

	it("persists protein viewer selections as context references", async () => {
		render(<AutopepWorkspace />);

		fireEvent.click(screen.getByRole("button", { name: "Select protein region" }));

		expect(mocks.createContextReferenceMutate).toHaveBeenCalledWith({
			artifactId: "11111111-1111-4111-8111-111111111111",
			candidateId: "33333333-3333-4333-8333-333333333333",
			kind: "protein_selection",
			label: "6M0J chain A residue 145",
			selector: {
				authAsymId: "A",
				residueRanges: [{ end: 145, start: 145 }],
			},
			workspaceId: "22222222-2222-4222-8222-222222222222",
		});

		await mocks.createContextReferenceOptions?.onSuccess?.();

		expect(mocks.listWorkspacesInvalidate).toHaveBeenCalledOnce();
		expect(mocks.getLatestWorkspaceInvalidate).toHaveBeenCalledOnce();
		expect(mocks.getWorkspaceInvalidate).toHaveBeenCalledWith({
			workspaceId: "22222222-2222-4222-8222-222222222222",
		});
	});

	it("removes selected context references", async () => {
		render(<AutopepWorkspace />);

		fireEvent.click(screen.getByRole("button", { name: "Remove context" }));

		expect(mocks.deleteContextReferenceMutate).toHaveBeenCalledWith({
			contextReferenceId: "55555555-5555-4555-8555-555555555555",
		});

		await mocks.deleteContextReferenceOptions?.onSuccess?.();

		expect(mocks.listWorkspacesInvalidate).toHaveBeenCalledOnce();
		expect(mocks.getLatestWorkspaceInvalidate).toHaveBeenCalledOnce();
		expect(mocks.getWorkspaceInvalidate).toHaveBeenCalledWith({
			workspaceId: "22222222-2222-4222-8222-222222222222",
		});
	});
});
