type Field = readonly [string, string];

export type ToolRender = {
  fields: Field[];
  summary: string;
};

const countItems = (value: unknown) =>
  Array.isArray(value) ? String(value.length) : "";

const joinItems = (value: unknown) =>
  Array.isArray(value) ? value.map(String).join(", ") : "";

const KNOWN: Record<string, (display: Record<string, unknown>) => ToolRender> = {
  search_pubmed_literature: (display) => ({
    summary: String(display.query ?? "PubMed literature"),
    fields: [
      ["query", String(display.query ?? "")],
      ["maxResults", String(display.maxResults ?? display.max_results ?? "")],
    ],
  }),
  search_europe_pmc_literature: (display) => ({
    summary: String(display.query ?? "Europe PMC literature"),
    fields: [
      ["query", String(display.query ?? "")],
      ["maxResults", String(display.maxResults ?? display.max_results ?? "")],
    ],
  }),
  generate_binder_candidates: (display) => ({
    summary: String(display.target_filename ?? "generate binders"),
    fields: [
      ["target", String(display.target_filename ?? "")],
      ["hotspots", joinItems(display.hotspot_residues)],
    ],
  }),
  fold_sequences_with_chai: (display) => ({
    summary: String(display.target_name ?? "fold with Chai"),
    fields: [
      ["target", String(display.target_name ?? "")],
      ["candidates", countItems(display.sequence_candidates)],
    ],
  }),
  score_candidate_interactions: (display) => ({
    summary: String(display.target_name ?? "score interactions"),
    fields: [
      ["target", String(display.target_name ?? "")],
      ["candidates", countItems(display.candidates)],
    ],
  }),
  // Legacy event names retained so existing workspaces still render cleanly.
  rcsb_structure_search: (display) => {
    const query = String(display.query ?? "");
    const maxResults = display.maxResults ?? display.max_results ?? "?";
    return {
      summary: query || "rcsb structure search",
      fields: [
        ["query", query],
        ["maxResults", String(maxResults)],
      ],
    };
  },
  pubmed_search: (display) => ({
    summary: String(display.query ?? "pubmed"),
    fields: [["query", String(display.query ?? "")]],
  }),
  biorxiv_search: (display) => ({
    summary: String(display.query ?? "biorxiv"),
    fields: [["query", String(display.query ?? "")]],
  }),
  prepare_structure: (display) => ({
    summary: String(display.candidateId ?? "prepare structure"),
    fields: [["candidateId", String(display.candidateId ?? "")]],
  }),
  fold_structure: (display) => ({
    summary: String(display.method ?? "fold"),
    fields: [["method", String(display.method ?? "")]],
  }),
  score_interaction: (display) => ({
    summary: String(display.scorer ?? "score"),
    fields: [["scorer", String(display.scorer ?? "")]],
  }),
};

const truncate = (value: string, max = 80) =>
  value.length > max ? `${value.slice(0, max - 1)}…` : value;

const fallbackFields = (display: Record<string, unknown>): Field[] =>
  Object.entries(display)
    .slice(0, 8)
    .map(([key, value]) => [key, truncate(JSON.stringify(value))] as const);

export const renderToolDisplay = (
  toolName: string,
  display: Record<string, unknown>,
): ToolRender => {
  const known = KNOWN[toolName];
  if (known) {
    return known(display ?? {});
  }
  return {
    summary: toolName,
    fields: fallbackFields(display ?? {}),
  };
};
