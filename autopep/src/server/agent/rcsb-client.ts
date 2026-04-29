const rcsbSearchUrl = "https://search.rcsb.org/rcsbsearch/v2/query";
const rcsbDownloadBaseUrl = "https://files.rcsb.org/download";
const rcsbDataBaseUrl = "https://data.rcsb.org/rest/v1/core/entry";

type FetchImpl = typeof fetch;

type SearchRcsbEntriesInput = {
	query: string;
	rows: number;
	fetchImpl?: FetchImpl;
};

type DownloadRcsbCifInput = {
	entryId: string;
	fetchImpl?: FetchImpl;
};

type GetRcsbEntryMetadataInput = {
	entryId: string;
	fetchImpl?: FetchImpl;
};

type RcsbSearchResult = {
	identifier?: unknown;
};

type RcsbSearchResponse = {
	result_set?: RcsbSearchResult[];
};

export type RcsbEntryMetadata = {
	rcsbId: string;
	title: string | null;
	method: string | null;
	resolutionAngstrom: number | null;
};

const normalizeEntryId = (entryId: string) => entryId.trim().toUpperCase();

const assertOkResponse = async (response: Response, source: string) => {
	if (!response.ok) {
		const body = await response.text().catch(() => "");
		throw new Error(
			`${source} request failed with ${response.status}.${
				body ? ` ${body.slice(0, 500)}` : ""
			}`,
		);
	}
};

export const searchRcsbEntries = async ({
	query,
	rows,
	fetchImpl = fetch,
}: SearchRcsbEntriesInput): Promise<string[]> => {
	const response = await fetchImpl(rcsbSearchUrl, {
		body: JSON.stringify({
			query: {
				type: "terminal",
				service: "full_text",
				parameters: {
					value: query,
				},
			},
			request_options: {
				paginate: {
					start: 0,
					rows,
				},
			},
			return_type: "entry",
		}),
		headers: {
			"content-type": "application/json",
		},
		method: "POST",
	});

	await assertOkResponse(response, "RCSB search");

	const payload = (await response.json()) as RcsbSearchResponse;

	return (payload.result_set ?? [])
		.map((result) =>
			typeof result.identifier === "string" ? result.identifier : null,
		)
		.filter((identifier): identifier is string => Boolean(identifier));
};

export const downloadRcsbCif = async ({
	entryId,
	fetchImpl = fetch,
}: DownloadRcsbCifInput): Promise<string> => {
	const normalizedEntryId = normalizeEntryId(entryId);
	const response = await fetchImpl(
		`${rcsbDownloadBaseUrl}/${encodeURIComponent(normalizedEntryId)}.cif`,
	);

	await assertOkResponse(response, "RCSB CIF download");

	const cifText = await response.text();

	if (!/^data_[^\s#]+/mu.test(cifText)) {
		throw new Error(`Downloaded RCSB CIF for ${normalizedEntryId} is invalid.`);
	}

	return cifText;
};

export const getRcsbEntryMetadata = async ({
	entryId,
	fetchImpl = fetch,
}: GetRcsbEntryMetadataInput): Promise<RcsbEntryMetadata> => {
	const normalizedEntryId = normalizeEntryId(entryId);
	const response = await fetchImpl(
		`${rcsbDataBaseUrl}/${encodeURIComponent(normalizedEntryId)}`,
	);

	await assertOkResponse(response, "RCSB metadata");

	const payload = (await response.json()) as {
		struct?: { title?: unknown };
		exptl?: Array<{ method?: unknown }>;
		rcsb_entry_info?: { resolution_combined?: unknown };
	};
	const firstResolution = Array.isArray(
		payload.rcsb_entry_info?.resolution_combined,
	)
		? payload.rcsb_entry_info.resolution_combined[0]
		: null;

	return {
		method:
			typeof payload.exptl?.[0]?.method === "string"
				? payload.exptl[0].method
				: null,
		rcsbId: normalizedEntryId,
		resolutionAngstrom:
			typeof firstResolution === "number" ? firstResolution : null,
		title:
			typeof payload.struct?.title === "string" ? payload.struct.title : null,
	};
};

export const getRcsbCifUrl = (entryId: string) =>
	`${rcsbDownloadBaseUrl}/${encodeURIComponent(normalizeEntryId(entryId))}.cif`;
