import { env } from "@/env.js";

const SYSTEM_PROMPT =
	"Return a concise 3-6 word title for this protein-design task. " +
	"No quotes, no punctuation. Title only, no preamble.";

const MAX_WORDS = 6;
const MAX_CHARS = 60;
const TIMEOUT_MS = 5000;

const fallbackName = (prompt: string) => {
	const firstLine = prompt.trim().split(/\r?\n/u)[0]?.trim() ?? "";
	if (!firstLine) {
		return "Untitled workspace";
	}
	return firstLine.length > MAX_CHARS
		? firstLine.slice(0, MAX_CHARS)
		: firstLine;
};

const cleanTitle = (raw: string) => {
	let title = raw.trim();
	// Remove surrounding quotes (straight, smart).
	title = title.replace(/^["'“”‘’]+|["'“”‘’]+$/g, "");
	// Remove trailing punctuation.
	title = title.replace(/[.!?,;:]+$/g, "");
	// Cap to 6 words.
	const words = title.split(/\s+/u).slice(0, MAX_WORDS);
	return words.join(" ").slice(0, MAX_CHARS);
};

type OpenAiCompletion = {
	choices: { message: { content: string | null } }[];
};

type OpenAiClient = (args: {
	messages: { role: string; content: string }[];
	model: string;
	temperature: number;
}) => Promise<OpenAiCompletion>;

const defaultOpenAiClient: OpenAiClient = async ({
	messages,
	model,
	temperature,
}) => {
	const apiKey = env.OPENAI_API_KEY;
	if (!apiKey) {
		throw new Error("OPENAI_API_KEY not configured.");
	}
	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
	try {
		const response = await fetch("https://api.openai.com/v1/chat/completions", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${apiKey}`,
			},
			body: JSON.stringify({ messages, model, temperature }),
			signal: controller.signal,
		});
		if (!response.ok) {
			throw new Error(`OpenAI HTTP ${response.status}`);
		}
		return (await response.json()) as OpenAiCompletion;
	} finally {
		clearTimeout(timeout);
	}
};

type InferArgs = {
	openaiClient?: OpenAiClient;
	prompt: string;
};

export const inferWorkspaceNameWithAi = async ({
	openaiClient = defaultOpenAiClient,
	prompt,
}: InferArgs): Promise<string> => {
	try {
		const completion = await openaiClient({
			model: "gpt-5.4-mini",
			messages: [
				{ role: "system", content: SYSTEM_PROMPT },
				{ role: "user", content: `Task: ${prompt}` },
			],
			temperature: 0.3,
		});
		const raw = completion.choices?.[0]?.message?.content?.trim();
		if (!raw) {
			return fallbackName(prompt);
		}
		const cleaned = cleanTitle(raw);
		return cleaned || fallbackName(prompt);
	} catch (_error) {
		return fallbackName(prompt);
	}
};
