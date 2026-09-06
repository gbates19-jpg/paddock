import { buildDemoStream } from "../data/demoEvents";
import { useEventStore } from "../store/eventStore";
import type { WireMessage } from "./events";

const API_WS_URL = (import.meta.env.VITE_API_WS_URL as string | undefined) ?? "ws://localhost:8000/events";

export function isDemoMode(): boolean {
  return new URLSearchParams(window.location.search).get("demo") === "1";
}

function runDemo(): () => void {
  const store = useEventStore.getState();
  store.setConnection("demo");

  let cancelled = false;
  let timeouts: ReturnType<typeof setTimeout>[] = [];

  const play = () => {
    if (cancelled) return;
    const stream = buildDemoStream();
    for (const { offsetMs, event } of stream) {
      const handle = setTimeout(() => {
        if (cancelled) return;
        useEventStore.getState().applyEvent({ ...event, ts_ms: Date.now() });
      }, offsetMs);
      timeouts.push(handle);
    }
    const last = stream[stream.length - 1]?.offsetMs ?? 0;
    const loopHandle = setTimeout(play, last + 1500);
    timeouts.push(loopHandle);
  };
  play();

  return () => {
    cancelled = true;
    timeouts.forEach(clearTimeout);
    timeouts = [];
  };
}

function runLive(): () => void {
  const store = useEventStore.getState();
  let socket: WebSocket | null = null;
  let retryHandle: ReturnType<typeof setTimeout> | null = null;
  let closed = false;

  const connect = () => {
    if (closed) return;
    store.setConnection("connecting");
    socket = new WebSocket(API_WS_URL);

    socket.onopen = () => useEventStore.getState().setConnection("connected");

    socket.onmessage = (msg) => {
      const parsed = JSON.parse(msg.data) as WireMessage;
      if (parsed.type === "snapshot") {
        useEventStore.getState().applySnapshot(parsed);
      } else {
        useEventStore.getState().applyEvent(parsed);
      }
    };

    socket.onclose = () => {
      useEventStore.getState().setConnection("disconnected");
      if (!closed) retryHandle = setTimeout(connect, 2000);
    };

    socket.onerror = () => socket?.close();
  };

  connect();

  return () => {
    closed = true;
    if (retryHandle) clearTimeout(retryHandle);
    socket?.close();
  };
}

export function startConnection(): () => void {
  return isDemoMode() ? runDemo() : runLive();
}
