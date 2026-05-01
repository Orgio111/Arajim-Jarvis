// Tiny REST client.
const base = '/api';

async function req(path, opts = {}) {
  const res = await fetch(`${base}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export const api = {
  health: () => req('/health'),
  chat: (session_id, message) => req('/chat', { method: 'POST', body: { session_id, message } }),
  getMode: () => req('/mode'),
  setMode: (mode) => req('/mode', { method: 'POST', body: { mode } }),
  listMemories: () => req('/memory'),
  addMemory: (content) => req('/memory', { method: 'POST', body: { content } }),
  deleteMemory: (id) => req(`/memory/${id}`, { method: 'DELETE' }),
  pendingPermissions: () => req('/permissions/pending'),
  approve: (id) => req(`/permissions/${id}/approve`, { method: 'POST' }),
  deny: (id) => req(`/permissions/${id}/deny`, { method: 'POST' }),
  models: () => req('/models'),
  benchmark: () => req('/benchmark', { method: 'POST' }),
  skills: () => req('/skills'),
  invokeSkill: (name, args) => req('/skills/invoke', { method: 'POST', body: { name, args } }),
  upgradeVersions: () => req('/upgrade/versions'),
  upgrade: (phrase) => req('/upgrade', { method: 'POST', body: { phrase } }),
  rollback: (version) => req('/upgrade/rollback', { method: 'POST', body: { version } }),
  voiceState: () => req('/voice/state'),
  voiceToggle: (on) => req('/voice/toggle', { method: 'POST', body: { on } }),
  voiceSpeak: (text) => req('/voice/speak', { method: 'POST', body: { text } }),
  cacheStats: () => req('/cache/stats'),
  learning: () => req('/learning'),
  vectorSize: () => req('/vector/size'),
  vectorSearch: (query, k = 6) => req('/vector/search', { method: 'POST', body: { query, k } }),
  webSearch: (query, k = 6) => req('/search/web', { method: 'POST', body: { query, k } }),
  deepSearch: (question, max_steps) => req('/search/deep', { method: 'POST', body: { question, max_steps } }),
  predictIntent: (message) => req('/intent', { method: 'POST', body: { message } }),
  debate: (task, language = 'python', max_rounds = 3) =>
    req('/agents/debate', { method: 'POST', body: { task, language, max_rounds } }),
};

/**
 * Streaming chat via SSE-over-fetch.
 * Calls onEvent({event, ...}) for every chunk, returns the final reply.
 */
export async function streamChat(session_id, message, onEvent) {
  const res = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id, message }),
  });
  if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let reply = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const line = block.split('\n').find((l) => l.startsWith('data: '));
      if (!line) continue;
      try {
        const ev = JSON.parse(line.slice(6));
        if (ev.event === 'token' && ev.delta) reply += ev.delta;
        onEvent && onEvent(ev);
      } catch {}
    }
  }
  return reply;
}
