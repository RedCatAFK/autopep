const europePmcSearchUrl =
	"https://www.ebi.ac.uk/europepmc/webservices/rest/search";

type FetchImpl = typeof fetch;

type SearchBioRxivPreprintsInput = {
	query: string;
	limit: number;
	fetchImpl?: FetchImpl;
};

type EuropePmcResult = {
	authorString?: unknown;
	doi?: unknown;
	firstPublicationDate?: unknown;
	id?: unknown;
	journalTitle?: unknown;
	source?: unknown;
	title?: unknown;
};

type EuropePmcSearchResponse = {
	resultList?: {
		result?: unknown;
	};
};

export type BioRxivRef = {
	authors: string | null;
	doi: string | null;
	id: string;
	publishedAt: string | null;
	source: string;
	title: string;
	url: string;
};

const toStringOrNull = (value: unknown) =>
	typeof value === "string" && value.trim().length > 0 ? value.trim() : null;

const isBioRxivLike = (result: EuropePmcResult) => {
	const doi = toStringOrNull(result.doi);
	const journalTitle = toStringOrNull(result.journalTitle);

	return (
		(doi?.startsWith("10.1101/") ?? false) ||
		/biorxiv/iu.test(journalTitle ?? "")
	);
};

const getResultUrl = ({
	doi,
	id,
	source,
}: {
	doi: string | null;
	id: string;
	source: string;
}) => {
	if (doi) {
		return `https://doi.org/${encodeURIComponent(doi)}`;
	}

	return `https://europepmc.org/article/${encodeURIComponent(
		source,
	)}/${encodeURIComponent(id)}`;
};

export const searchBioRxivPreprints = async ({
	query,
	limit,
	fetchImpl = fetch,
}: SearchBioRxivPreprintsInput): Promise<BioRxivRef[]> => {
	const url = new URL(europePmcSearchUrl);
	url.searchParams.set("format", "json");
	url.searchParams.set("pageSize", String(Math.max(limit * 2, limit)));
	url.searchParams.set("query", `SRC:PPR (${query})`);
	url.searchParams.set("sort", "FIRST_PDATE_D desc");

	const response = await fetchImpl(url);

	if (!response.ok) {
		throw new Error(`bioRxiv preprint search failed with ${response.status}.`);
	}

	const payload = (await response.json()) as EuropePmcSearchResponse;
	const rawResults = Array.isArray(payload.resultList?.result)
		? payload.resultList.result
		: [];

	return rawResults
		.filter((result): result is EuropePmcResult => Boolean(result))
		.filter(isBioRxivLike)
		.map((result) => {
			const id = toStringOrNull(result.id);
			const title = toStringOrNull(result.title);
			const source = toStringOrNull(result.source) ?? "PPR";
			const doi = toStringOrNull(result.doi);

			if (!id || !title) {
				return null;
			}

			return {
				authors: toStringOrNull(result.authorString),
				doi,
				id,
				publishedAt: toStringOrNull(result.firstPublicationDate),
				source,
				title,
				url: getResultUrl({ doi, id, source }),
			};
		})
		.filter((result): result is BioRxivRef => Boolean(result))
		.slice(0, limit);
};
