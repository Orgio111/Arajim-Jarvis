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
};
