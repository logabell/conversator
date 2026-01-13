import { useEffect, useRef, useCallback } from 'react';

export type WebSocketEventType =
  | 'conversation_entry'
  | 'task_update'
  | 'inbox_item'
  | 'builder_status';

export interface WebSocketMessage {
  type: WebSocketEventType;
  data: unknown;
}

interface UseWebSocketOptions {
  onMessage?: (msg: WebSocketMessage) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  reconnectInterval?: number;
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const {
    onMessage,
    onConnect,
    onDisconnect,
    reconnectInterval = 3000
  } = options;

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // In development, API is on different port (8080) than Vite dev server (5173)
    const apiHost = import.meta.env.DEV ? 'localhost:8080' : window.location.host;
    const wsUrl = `${protocol}//${apiHost}/ws/events`;

    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('[WS] Connected');
      onConnect?.();
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WebSocketMessage;
        onMessage?.(msg);
      } catch (e) {
        console.error('[WS] Parse error:', e);
      }
    };

    ws.onclose = () => {
      console.log('[WS] Disconnected');
      onDisconnect?.();

      // Reconnect after delay
      reconnectTimeoutRef.current = window.setTimeout(() => {
        connect();
      }, reconnectInterval);
    };

    ws.onerror = (error) => {
      console.error('[WS] Error:', error);
    };

    wsRef.current = ws;
  }, [onMessage, onConnect, onDisconnect, reconnectInterval]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return {
    isConnected: wsRef.current?.readyState === WebSocket.OPEN,
    disconnect,
    reconnect: connect
  };
}
