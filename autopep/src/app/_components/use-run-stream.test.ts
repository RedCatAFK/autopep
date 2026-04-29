// @vitest-environment jsdom
import { renderHook, waitFor, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useRunStream } from "./use-run-stream";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  listeners: Record<string, ((event: MessageEvent) => void)[]> = {};
  closed = false;
  onerror: ((event: Event) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(name: string, fn: (event: MessageEvent) => void) {
    this.listeners[name] = this.listeners[name] ?? [];
    this.listeners[name]!.push(fn);
  }

  removeEventListener() {
    /* no-op for test */
  }

  emit(name: string, data: unknown) {
    const event = new MessageEvent(name, {
      data: typeof data === "string" ? data : JSON.stringify(data),
    });
    this.listeners[name]?.forEach((fn) => fn(event));
  }

  emitError() {
    this.onerror?.(new Event("error"));
  }

  close() {
    this.closed = true;
  }
}

beforeEach(() => {
  FakeEventSource.instances = [];
  // @ts-expect-error - mocking EventSource
  globalThis.EventSource = FakeEventSource;
});

afterEach(() => {
  // @ts-expect-error - restore
  delete globalThis.EventSource;
});

describe("useRunStream", () => {
  it("accumulates delta text and stops on done", async () => {
    const { result } = renderHook(() =>
      useRunStream({ url: "https://example.com/stream?token=abc" }),
    );

    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1));
    const source = FakeEventSource.instances[0]!;

    act(() => {
      source.emit("delta", { text: "Hello " });
      source.emit("delta", { text: "world" });
    });

    expect(result.current.streamingText).toBe("Hello world");
    expect(result.current.isStreaming).toBe(true);

    act(() => {
      source.emit("done", "{}");
    });

    expect(result.current.isStreaming).toBe(false);
    expect(source.closed).toBe(true);
  });

  it("does nothing when url is null", () => {
    const { result } = renderHook(() => useRunStream({ url: null }));
    expect(FakeEventSource.instances.length).toBe(0);
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.streamingText).toBe("");
  });

  it("clears state when url changes", async () => {
    const { result, rerender } = renderHook(
      ({ url }: { url: string | null }) => useRunStream({ url }),
      { initialProps: { url: "https://example.com/stream?token=abc" } },
    );

    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1));
    const first = FakeEventSource.instances[0]!;
    act(() => {
      first.emit("delta", { text: "old" });
    });
    expect(result.current.streamingText).toBe("old");

    rerender({ url: "https://example.com/stream?token=xyz" });
    await waitFor(() => expect(FakeEventSource.instances.length).toBe(2));
    expect(result.current.streamingText).toBe("");
    expect(first.closed).toBe(true);
  });
});
