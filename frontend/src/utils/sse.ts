export interface SseConnection {
  readonly readyState: number;
  onerror: ((event: Event) => void) | null;
  addEventListener(type: string, listener: (event: MessageEvent) => void): void;
  close(): void;
}

export const SSE_CONNECTING = 0;
export const SSE_OPEN = 1;
export const SSE_CLOSED = 2;

interface SseOptions {
  url: string;
  headers?: HeadersInit;
}

/** Authenticated SSE transport; native EventSource cannot set Authorization headers. */
export function openAuthenticatedSse({ url, headers }: SseOptions): SseConnection {
  let state = SSE_CONNECTING;
  let controller: AbortController | null = new AbortController();
  const listeners = new Map<string, Array<(event: MessageEvent) => void>>();
  const connection: SseConnection = {
    get readyState() {
      return state;
    },
    onerror: null,
    addEventListener(type, listener) {
      const current = listeners.get(type) ?? [];
      current.push(listener);
      listeners.set(type, current);
    },
    close() {
      if (state === SSE_CLOSED) return;
      state = SSE_CLOSED;
      controller?.abort();
      controller = null;
    },
  };

  const dispatch = (eventType: string, data: string, id: string | undefined) => {
    if (state === SSE_CLOSED) return;
    const event = new MessageEvent(eventType || "message", { data, lastEventId: id ?? "" });
    for (const listener of listeners.get(event.type) ?? []) listener(event);
  };

  const fail = () => {
    if (state === SSE_CLOSED) return;
    state = SSE_CLOSED;
    controller = null;
    connection.onerror?.(new Event("error"));
  };

  const run = async () => {
    try {
      const response = await fetch(url, { method: "GET", headers, signal: controller?.signal });
      if (!response.ok || !response.body) {
        fail();
        return;
      }
      state = SSE_OPEN;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let eventType = "message";
      let eventId: string | undefined;
      let dataLines: string[] = [];
      const dispatchBuffered = () => {
        if (dataLines.length === 0) return;
        dispatch(eventType, dataLines.join("\n"), eventId);
        eventType = "message";
        eventId = undefined;
        dataLines = [];
      };
      const consumeLine = (line: string) => {
        if (line === "") {
          dispatchBuffered();
          return;
        }
        if (line.startsWith(":")) return;
        const separator = line.indexOf(":");
        const field = separator >= 0 ? line.slice(0, separator) : line;
        const value = separator >= 0 ? line.slice(separator + 1).replace(/^ /, "") : "";
        if (field === "event") eventType = value;
        else if (field === "id") eventId = value;
        else if (field === "data") dataLines.push(value);
      };
      while (state !== SSE_CLOSED) {
        const { value, done } = await reader.read();
        if (done) {
          buffer += decoder.decode();
          if (buffer) consumeLine(buffer);
          dispatchBuffered();
          fail();
          return;
        }
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split(/\r?\n/);
        buffer = lines.pop() ?? "";
        for (const line of lines) consumeLine(line);
      }
    } catch (error) {
      if (state !== SSE_CLOSED && !(error instanceof DOMException && error.name === "AbortError")) fail();
    }
  };

  void run();
  return connection;
}
