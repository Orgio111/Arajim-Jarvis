import { useEffect, useRef, useState } from 'react';

export function useWebSocket(path = '/ws', max = 500) {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);

  useEffect(() => {
    let stopped = false;
    function connect() {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${proto}//${window.location.host}${path}`);
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!stopped) setTimeout(connect, 2000);
      };
      ws.onmessage = (e) => {
        try {
          const ev = JSON.parse(e.data);
          setEvents((prev) => {
            const next = [...prev, ev];
            return next.length > max ? next.slice(-max) : next;
          });
        } catch {}
      };
    }
    connect();
    return () => {
      stopped = true;
      wsRef.current?.close();
    };
  }, [path, max]);

  return { events, connected, send: (d) => wsRef.current?.send(JSON.stringify(d)) };
}
