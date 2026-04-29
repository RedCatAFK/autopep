type Field = readonly [string, string];

export type ToolRender = {
  fields: Field[];
  summary: string;
};

const KNOWN: Record<string, (display: Record<string, unknown>) => ToolRender> = {
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
