import { useEffect, useRef, useCallback } from 'react';

export default function useDashboardChannel(tenantId, role, onInvalidation) {
  const wsRef = useRef(null);
  const reconnectTimeout = useRef(null);

  const connect = useCallback(() => {
    if (!tenantId || !role) return;

    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/dashboard/${tenantId}/${role}`;

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.widget_keys && onInvalidation) {
            onInvalidation(data.widget_keys);
          }
        } catch (err) {
          console.error('Dashboard channel message parse error:', err);
        }
      };

      ws.onclose = () => {
        // Reconnect after 5s
        reconnectTimeout.current = setTimeout(connect, 5000);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch (err) {
      console.error('Dashboard channel connection error:', err);
    }
  }, [tenantId, role, onInvalidation]);

  useEffect(() => {
    connect();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeout.current) {
        clearTimeout(reconnectTimeout.current);
      }
    };
  }, [connect]);

  return {
    isConnected: wsRef.current?.readyState === WebSocket.OPEN,
  };
}
