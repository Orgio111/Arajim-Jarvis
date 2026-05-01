import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api, streamChat } from './api.js';
import { useWebSocket } from './useWebSocket.js';
import { VoiceController } from './voice.js';

const MODES = [
  { id: 'full_auto',    label: 'AUTO' },
  { id: 'smart_assist', label: 'ASSIST' },
  { id: 'manual',       label: 'MANUAL' },
];

const AGENTS = ['planner', 'executor', 'coder', 'reviewer', 'optimizer'];

export default function App() {
  const { events, connected } = useWebSocket('/ws');
  const [health, setHealth] = useState(null);
  const [mode, setMode] = useState('smart_assist');
  const [chat, setChat] = useState([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [streaming, setStreaming] = useState(true);
  const [memories, setMemories] = useState([]);
  const [pending, setPending] = useState([]);
  const [versions, setVersions] = useState([]);
  const [voice, setVoice] = useState({ enabled: false, active: false, lang: 'en' });
  const [models, setModels] = useState({ registry: {}, scores: {} });
  const [cacheStats, setCacheStats] = useState({});
  const [learning, setLearning] = useState({});
  const [vectorSize, setVectorSize] = useState(0);
  const [lastIntent, setLastIntent] = useState(null);

  const chatRef = useRef(null);
  const voiceRef = useRef(null);

  useEffect(() => {
    voiceRef.current = new VoiceController({
      sessionId: 'default',
      onTranscript: (t) => t && setChat((c) => [...c, { role: 'user', content: `🎙 ${t}` }]),
      onReply: (r) => r && setChat((c) => [...c, { role: 'assistant', content: r }]),
      onError: (e) => setChat((c) => [...c, { role: 'system', content: `Voice error: ${e.message}` }]),
    });
  }, []);

  useEffect(() => { refreshAll(); const t = setInterval(refreshTelemetry, 5000); return () => clearInterval(t); }, []);
  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: 'smooth' });
  }, [chat]);

  // React to live events
  useEffect(() => {
    if (!events.length) return;
    const last = events[events.length - 1];
    if (last.channel === 'action' && last.type === 'pending') refreshPending();
    if (last.channel === 'upgrade')                          refreshVersions();
    if (last.channel === 'intent' && last.type === 'predicted') setLastIntent(last);
  }, [events]);

  async function refreshAll() {
    try {
      const [h, m, mem, p, v, vs, mo, cs, lr, vsz] = await Promise.all([
        api.health(), api.getMode(), api.listMemories(),
        api.pendingPermissions(), api.upgradeVersions(),
        api.voiceState(), api.models(),
        api.cacheStats(), api.learning(), api.vectorSize(),
      ]);
      setHealth(h); setMode(m.mode);
      setMemories(mem.memories); setPending(p.pending);
      setVersions(v.versions); setVoice(vs); setModels(mo);
      setCacheStats(cs); setLearning(lr); setVectorSize(vsz.size);
    } catch (e) { console.error(e); }
  }

  async function refreshTelemetry() {
    try {
      const [cs, lr, vsz] = await Promise.all([api.cacheStats(), api.learning(), api.vectorSize()]);
      setCacheStats(cs); setLearning(lr); setVectorSize(vsz.size);
    } catch {}
  }
  async function refreshPending() { try { setPending((await api.pendingPermissions()).pending); } catch {} }
  async function refreshVersions() { try { setVersions((await api.upgradeVersions()).versions); } catch {} }
  async function refreshMemories() { try { setMemories((await api.listMemories()).memories); } catch {} }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    setBusy(true);
    setChat((c) => [...c, { role: 'user', content: text }]);
    const i = chat.length + 1; // index of the assistant slot we'll fill
    try {
      if (streaming) {
        setChat((c) => [...c, { role: 'assistant', content: '' }]);
        await streamChat('default', text, (ev) => {
          if (ev.event === 'token' && ev.delta) {
            setChat((c) => {
              const next = [...c];
              if (next[i]) next[i] = { ...next[i], content: (next[i].content || '') + ev.delta };
              return next;
            });
          }
          if (ev.event === 'intent') setLastIntent({ ...ev.data, ts: Date.now() });
        });
      } else {
        const r = await api.chat('default', text);
        setChat((c) => [...c, { role: 'assistant', content: r.reply, plan: r.plan, intent: r.intent, strategy: r.strategy }]);
        if (r.upgrade) refreshVersions();
      }
      if (text.startsWith('remember') || text.startsWith('forget')) refreshMemories();
    } catch (e) {
      setChat((c) => [...c, { role: 'system', content: `Error: ${e.message}` }]);
    } finally {
      setBusy(false);
    }
  }

  async function changeMode(m) { setMode((await api.setMode(m)).mode); }
  async function approve(id) { await api.approve(id); refreshPending(); }
  async function deny(id)    { await api.deny(id);    refreshPending(); }
  async function forget(id)  { await api.deleteMemory(id); refreshMemories(); }
  async function toggleVoice() {
    const next = !voice.active;
    setVoice({ ...voice, active: next });
    try { await api.voiceToggle(next); } catch {}
    if (next) await voiceRef.current?.start();
    else      voiceRef.current?.stop();
  }

  async function triggerUpgrade() {
    const phrase = window.prompt(`Type the confirmation phrase to upgrade myself:`, '');
    if (!phrase) return;
    setChat((c) => [...c, { role: 'system', content: `Upgrade requested: ${phrase}` }]);
    try {
      const r = await api.upgrade(phrase);
      setChat((c) => [...c, { role: 'system', content: `Upgrade applied: v${r.version} — ${r.summary}` }]);
      refreshVersions();
    } catch (e) {
      setChat((c) => [...c, { role: 'system', content: `Upgrade failed: ${e.message}` }]);
    }
  }

  async function rollback(v) {
    if (!confirm(`Rollback to v${v}?`)) return;
    try { await api.rollback(v); refreshVersions(); } catch (e) { alert(e.message); }
  }

  // derive agent activity from events
  const agentState = useMemo(() => {
    const s = Object.fromEntries(AGENTS.map((a) => [a, 'idle']));
    for (let i = events.length - 1; i >= Math.max(0, events.length - 40); i--) {
      const e = events[i];
      if (e.channel === 'agent' && e.type === 'thinking' && s[e.agent] === 'idle') s[e.agent] = 'thinking';
      if (e.channel === 'agent' && e.type === 'reply' && s[e.agent] === 'thinking') s[e.agent] = 'done';
    }
    return s;
  }, [events]);

  const cacheHitRate = useMemo(() => {
    const total = (cacheStats.exact_hits || 0) + (cacheStats.semantic_hits || 0) + (cacheStats.misses || 0);
    if (!total) return 0;
    return ((cacheStats.exact_hits + cacheStats.semantic_hits) / total) * 100;
  }, [cacheStats]);

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">ARAJIM-JARVIS<span className="v">v{health?.version || 1}</span></div>
        <div className={`status-pill ${connected ? 'ok' : 'bad'}`}>{connected ? 'LINK ●' : 'OFFLINE'}</div>
        <div className={`status-pill ${health?.nvidia_configured ? 'ok' : 'warn'}`}>
          NVIDIA NIM {health?.nvidia_configured ? '●' : '○'}
        </div>
        <div className="status-pill">{mode.replace('_', ' ').toUpperCase()}</div>
        <div className="status-pill">CACHE {cacheHitRate.toFixed(0)}%</div>
        <div className="status-pill">VEC {vectorSize}</div>
        <div className="spacer" />
        <label style={{ fontSize: 10, color: 'var(--text-dim)', display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="checkbox" checked={streaming} onChange={(e) => setStreaming(e.target.checked)} />
          STREAM
        </label>
        <button
          className={`voice-btn ${voice.active ? 'active' : ''}`}
          title="Toggle JARVIS voice mode"
          onClick={toggleVoice}
        >🎙</button>
        <button className="primary" onClick={triggerUpgrade}>UPGRADE MYSELF</button>
      </div>

      <aside className="sidebar">
        <div className="panel">
          <h3>Mode</h3>
          <div className="mode-row">
            {MODES.map((m) => (
              <button key={m.id} className={mode === m.id ? 'active' : ''} onClick={() => changeMode(m.id)}>
                {m.label}
              </button>
            ))}
          </div>
        </div>

        <div className="panel">
          <h3>Last Intent</h3>
          {lastIntent ? (
            <div style={{ fontSize: 11, lineHeight: 1.6 }}>
              <div><span style={{ color: 'var(--accent-2)' }}>{lastIntent.intent}</span> · {(lastIntent.confidence * 100).toFixed(0)}%</div>
              <div style={{ color: 'var(--text-dim)' }}>strategy: {lastIntent.strategy}</div>
              {lastIntent.skill && <div style={{ color: 'var(--text-dim)' }}>skill: {lastIntent.skill}</div>}
            </div>
          ) : <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>—</div>}
        </div>

        <div className="panel">
          <h3>Agents</h3>
          {AGENTS.map((a) => (
            <div key={a} className="agent-row">
              <span className="agent-name">{a}</span>
              <span className={`agent-state ${agentState[a]}`}>{agentState[a]}</span>
            </div>
          ))}
        </div>

        <div className="panel">
          <h3>Pending Actions</h3>
          {pending.length === 0 && <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>No pending actions.</div>}
          {pending.map((p) => (
            <div key={p.id} className="confirm-card">
              <div className="desc">[{p.kind}] {p.description}</div>
              <div className="actions">
                <button onClick={() => approve(p.id)}>Approve</button>
                <button className="danger" onClick={() => deny(p.id)}>Deny</button>
              </div>
            </div>
          ))}
        </div>

        <div className="panel">
          <h3>Memory</h3>
          {memories.length === 0 && <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>Empty. Say "remember this: ..."</div>}
          {memories.slice(0, 30).map((m) => (
            <div key={m.id} className="mem-row">
              <span className="id">#{m.id}</span>
              <span>{m.content}</span>
              <span className="x" onClick={() => forget(m.id)}>✕</span>
            </div>
          ))}
        </div>
      </aside>

      <main className="main">
        <div className="chat-log" ref={chatRef}>
          {chat.length === 0 && (
            <div className="msg system">
              JARVIS online. NVIDIA NIM + cache + vector memory + deep search.<br/>
              Try: <em>"deep research recent NVIDIA NIM models"</em>, <em>"remember this: I prefer concise answers"</em>, or <em>"upgrade myself"</em>.
            </div>
          )}
          {chat.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              <div className="meta">{m.role}{m.intent ? ` · ${m.strategy || m.intent.intent}` : ''}</div>
              <div>{m.content}</div>
            </div>
          ))}
          {busy && !streaming && <div className="msg system">Thinking...</div>}
        </div>

        <div className="composer">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder="Talk to JARVIS..."
          />
          <button className="primary" onClick={send} disabled={busy}>Send</button>
        </div>
      </main>

      <aside className="rightbar">
        <div className="panel upgrade-panel">
          <h3>Versions</h3>
          <div className="version-list">
            {versions.length === 0 && <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>No versions yet.</div>}
            {versions.slice().reverse().map((v) => (
              <div key={v.version} className={`version-row ${v.status}`}>
                <span>v{v.version}</span>
                <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>{v.summary || '—'}</span>
                <span className="badge">{v.status}</span>
                {v.status === 'applied' && v.version > 1 && (
                  <button style={{ padding: '2px 6px', fontSize: 9 }} onClick={() => rollback(v.version - 1)}>↩</button>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="panel">
          <h3>Cache</h3>
          <div className="kv">
            <div><span>exact hits</span><b>{cacheStats.exact_hits || 0}</b></div>
            <div><span>semantic hits</span><b>{cacheStats.semantic_hits || 0}</b></div>
            <div><span>misses</span><b>{cacheStats.misses || 0}</b></div>
            <div><span>writes</span><b>{cacheStats.writes || 0}</b></div>
            <div><span>hit rate</span><b style={{ color: 'var(--ok)' }}>{cacheHitRate.toFixed(1)}%</b></div>
          </div>
        </div>

        <div className="panel">
          <h3>Learning</h3>
          <div style={{ fontSize: 10, color: 'var(--text-dim)' }}>{learning.samples || 0} samples</div>
          {Object.entries(learning.skill_weights || {}).slice(0, 6).map(([k, v]) => (
            <div key={k} className="kv-row"><span>{k}</span><b>{Number(v).toFixed(2)}</b></div>
          ))}
        </div>

        <div className="panel">
          <h3>NVIDIA Models</h3>
          {Object.values(models.registry || {}).slice(0, 8).map((m) => (
            <div key={m.id} className="model-row">
              <div className="id">{m.id}</div>
              <div className="tier">{m.tier} · {(m.context_window / 1000).toFixed(0)}K</div>
            </div>
          ))}
        </div>

        <div className="panel">
          <h3>Live Stream</h3>
          <div className="log-stream">
            {events.slice(-80).reverse().map((e, i) => (
              <div key={i} className="line">
                <span className="ch">[{e.channel}]</span>{' '}
                <span className="t">{e.type}</span>{' '}
                {e.content || e.desc || e.delta || e.text || e.kind || e.intent || ''}
              </div>
            ))}
          </div>
        </div>
      </aside>
    </div>
  );
}
