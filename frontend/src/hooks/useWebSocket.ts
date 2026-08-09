import { useCallback, useEffect, useRef, useState } from "react";
import type { RuntimeEnvelope, WsEvent } from "../types";

// Matches the backend's actual route (backend/api.py: @app.websocket("/ws"))
// and vite.config.ts's dev proxy stanza ("/ws" -> ws:true) — this URL
// previously pointed at /ws/events, a path the backend never registered,
// so the dashboard's live websocket connection silently never connected
// (it fell back to polling via react-query, which masked the bug).
const WS_URL = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
const RECONNECT_MS = [1000, 2000, 4000, 8000, 16000];
const FLUSH_MS = 50;
const MAX_BATCH = 32;

function normalizeEvent(data: RuntimeEnvelope): WsEvent {
  if (data.payload && typeof data.payload === "object") {
    return {
      ...data.payload,
      event_id: data.event_id,
      replay_hash: data.replay_hash,
      sequence_id: data.sequence_id,
      source: data.source,
      event_version: data.event_version,
      correlation_id: data.correlation_id,
      type: String(data.type),
      ts: Number(data.ts ?? Date.now() / 1000),
    } as WsEvent;
  }

  return data as WsEvent;
}

export function useWebSocket(onMessage: (e: WsEvent) => void) {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const attemptsRef = useRef(0);
  const queueRef = useRef<WsEvent[]>([]);
  const flushTimerRef = useRef<number | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const flushQueue = useCallback(() => {
    const queued = queueRef.current.splice(0, MAX_BATCH);

    if (!queued.length) {
      return;
    }

    queued.sort((a, b) => {
      const sa = typeof (a as RuntimeEnvelope).sequence_id === "number"
        ? Number((a as RuntimeEnvelope).sequence_id)
        : Number.MAX_SAFE_INTEGER;

      const sb = typeof (b as RuntimeEnvelope).sequence_id === "number"
        ? Number((b as RuntimeEnvelope).sequence_id)
        : Number.MAX_SAFE_INTEGER;

      return sa - sb;
    });

    for (const event of queued) {
      onMessageRef.current(event);
    }
  }, []);

  const scheduleFlush = useCallback(() => {
    if (flushTimerRef.current !== null) {
      return;
    }

    flushTimerRef.current = window.setTimeout(() => {
      flushTimerRef.current = null;
      flushQueue();
    }, FLUSH_MS);
  }, [flushQueue]);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      attemptsRef.current = 0;
    };

    ws.onmessage = (ev) => {
      try {
        const raw = JSON.parse(ev.data) as RuntimeEnvelope;
        queueRef.current.push(normalizeEvent(raw));
        scheduleFlush();
      } catch {
        // malformed frames are ignored to preserve runtime continuity
      }
    };

    ws.onclose = () => {
      setConnected(false);
      const delay = RECONNECT_MS[Math.min(attemptsRef.current, RECONNECT_MS.length - 1)];
      attemptsRef.current += 1;
      setTimeout(connect, delay);
    };

    ws.onerror = () => ws.close();
  }, [scheduleFlush]);

  useEffect(() => {
    connect();

    return () => {
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current);
      }

      wsRef.current?.close();
    };
  }, [connect]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      flushQueue();
    }, FLUSH_MS);

    return () => window.clearInterval(interval);
  }, [flushQueue]);

  return { connected };
}
