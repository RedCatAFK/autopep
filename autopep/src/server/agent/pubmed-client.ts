const pubmedSearchUrl =
	"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi";

type FetchImpl = typeof fetch;

type SearchPubMedInput = {
	query: string;
	retmax: number;
	fetchImpl?: FetchImpl;
};

type PubMedSearchResponse = {
	esearchresult?: {
		idlist?: unknown;
	};
};

export type PubMedRef = {
	id: string;
	title: string;
	url: string;
};

export const searchPubMed = async ({
	query,
	retmax,
	fetchImpl = fetch,
}: SearchPubMedInput): Promise<PubMedRef[]> => {
	const url = new URL(pubmedSearchUrl);
	url.searchParams.set("db", "pubmed");
	url.searchParams.set("retmode", "json");
	url.searchParams.set("retmax", String(retmax));
	url.searchParams.set("term", query);

	const response = await fetchImpl(url);

	if (!response.ok) {
		throw new Error(`PubMed search request failed with ${response.status}.`);
	}

	const payload = (await response.json()) as PubMedSearchResponse;
	const ids = Array.isArray(payload.esearchresult?.idlist)
		? payload.esearchresult.idlist
		: [];

	return ids
		.filter((id): id is string => typeof id === "string" && id.length > 0)
		.map((id) => ({
			id,
			title: `PubMed result ${id}`,
			url: `https://pubmed.ncbi.nlm.nih.gov/${id}/`,
		}));
};
