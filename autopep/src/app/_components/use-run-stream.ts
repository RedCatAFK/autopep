import { useEffect, useState } from "react";

type UseRunStreamArgs = {
  url: string | null;
};

export function useRunStream({ url }: UseRunStreamArgs) {
  const [streamingText, setStreamingText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!url) {
      setStreamingText("");
      setIsStreaming(false);
      setError(null);
      return;
    }

    setStreamingText("");
    setError(null);
    setIsStreaming(true);

    const source = new EventSource(url);

    const onDelta = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as { text?: string };
        if (data.text) {
          setStreamingText((prev) => prev + data.text);
        }
      } catch {
        // ignore parse errors on individual deltas
      }
    };

    const onDone = () => {
      setIsStreaming(false);
      source.close();
    };

    const onError = (_event: Event) => {
      // Don't immediately bail — EventSource auto-retries; only surface a hard error
      // if the source can't reconnect (readyState === CLOSED).
      if (source.readyState === EventSource.CLOSED) {
        setError(new Error("Stream connection failed."));
        setIsStreaming(false);
      }
    };

    source.addEventListener("delta", onDelta as EventListener);
    source.addEventListener("done", onDone);
    source.onerror = onError;

    return () => {
      source.removeEventListener("delta", onDelta as EventListener);
      source.removeEventListener("done", onDone);
      source.onerror = null;
      source.close();
    };
  }, [url]);

  return { streamingText, isStreaming, error };
}
