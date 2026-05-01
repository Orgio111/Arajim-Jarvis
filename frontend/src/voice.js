/**
 * Browser voice loop:
 *  - press-and-hold (or toggle) to record from the mic
 *  - on release, POST the recording to /api/voice/converse
 *  - the response is the JARVIS reply audio; play it back
 *  - X-Transcript and X-Reply headers carry the text for the UI
 */
export class VoiceController {
  constructor({ onTranscript, onReply, onError, sessionId = 'voice' } = {}) {
    this.onTranscript = onTranscript || (() => {});
    this.onReply = onReply || (() => {});
    this.onError = onError || ((e) => console.error(e));
    this.sessionId = sessionId;
    this.recorder = null;
    this.chunks = [];
    this.stream = null;
    this.recording = false;
  }

  async start() {
    if (this.recording) return;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      this.onError(new Error('Microphone permission denied'));
      return;
    }
    const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : '';
    this.recorder = new MediaRecorder(this.stream, mime ? { mimeType: mime } : {});
    this.chunks = [];
    this.recorder.ondataavailable = (e) => { if (e.data.size > 0) this.chunks.push(e.data); };
    this.recorder.onstop = () => this._submit();
    this.recorder.start();
    this.recording = true;
  }

  stop() {
    if (!this.recording) return;
    this.recording = false;
    try { this.recorder?.stop(); } catch {}
    this.stream?.getTracks().forEach((t) => t.stop());
  }

  async _submit() {
    if (!this.chunks.length) return;
    const blob = new Blob(this.chunks, { type: this.recorder?.mimeType || 'audio/webm' });
    const fd = new FormData();
    fd.append('audio', blob, 'speech.webm');
    fd.append('session_id', this.sessionId);
    try {
      const res = await fetch('/api/voice/converse', { method: 'POST', body: fd });
      if (!res.ok) {
        this.onError(new Error(`voice converse ${res.status}`));
        return;
      }
      const transcript = decodeURIComponent(escape(res.headers.get('x-transcript') || ''));
      const reply = decodeURIComponent(escape(res.headers.get('x-reply') || ''));
      this.onTranscript(transcript);
      this.onReply(reply);
      const audio = await res.blob();
      const url = URL.createObjectURL(audio);
      const el = new Audio(url);
      el.play().catch(() => {});
      el.onended = () => URL.revokeObjectURL(url);
    } catch (e) {
      this.onError(e);
    }
  }
}

/** Speak a piece of text via /api/voice/speak (no STT needed). */
export async function speak(text, voice) {
  const res = await fetch('/api/voice/speak', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice }),
  });
  if (!res.ok) return;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const el = new Audio(url);
  el.play().catch(() => {});
  el.onended = () => URL.revokeObjectURL(url);
}
