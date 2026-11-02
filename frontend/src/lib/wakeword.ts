import { create } from 'zustand';
import { apiFetch } from './api';
import { useInteractionMode } from './interaction-mode';

export interface WakeTelemetry {
  rms: number;
  dbfs: number;
  frames: number;
  processed_frames: number;
  audio_bytes: number;
  last_text: string;
  confidence: number;
  paused_reason: string | null;
  detections: number;
  language?: string;
  validation?: string;
}
export interface WakeStatus {
  enabled: boolean;
  state: 'disabled' | 'starting' | 'listening' | 'error';
  owner_id: string | null;
  error: string | null;
  word: string;
  model_available: boolean;
  diagnostics?: WakeTelemetry;
  threshold?: number;
  aliases?: string[];
}
export const wakeClientId = `web-${Date.now()}-${Math.random().toString(36).slice(2)}`;
const WAKE_KEY = 'openjarvis-wakeword-enabled';
function savedWakeIntent(): boolean | null {
  try { const value = sessionStorage.getItem(WAKE_KEY); return value === null ? null : value === 'true'; }
  catch { return null; }
}
function saveWakeIntent(enabled: boolean) {
  try { sessionStorage.setItem(WAKE_KEY, String(enabled)); } catch { /* Keep in-memory preference. */ }
}
export const useWakeWordStore = create<{
  status: WakeStatus;
  connected: boolean;
  recording: boolean;
  pending: boolean;
  desiredEnabled: boolean | null;
  telemetry: WakeTelemetry | null;
  telemetryAt: number;
  connectionError: string | null;
}>()(() => ({
  status: { enabled: false, state: 'disabled', owner_id: null, error: null, word: 'computador', model_available: false },
  connected: false, recording: false, pending: false, desiredEnabled: savedWakeIntent(), telemetry: null, telemetryAt: 0, connectionError: null,
}));

let beepContext: AudioContext | null = null;
export async function prepareWakeAudio(): Promise<void> {
  if (!beepContext || beepContext.state === 'closed') beepContext = new AudioContext();
  await beepContext.resume();
}

export async function activationBeep(): Promise<void> {
  if (!beepContext || beepContext.state !== 'running') return;
  const oscillator = beepContext.createOscillator();
  const gain = beepContext.createGain();
  oscillator.type = 'sine';
  oscillator.frequency.value = 660;
  const now = beepContext.currentTime;
  gain.gain.setValueAtTime(0, now);
  gain.gain.linearRampToValueAtTime(0.07, now + 0.015);
  gain.gain.linearRampToValueAtTime(0, now + 0.11);
  oscillator.connect(gain);
  gain.connect(beepContext.destination);
  const ended = new Promise<void>((resolve) => {
    oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); resolve(); };
  });
  oscillator.start(now);
  oscillator.stop(now + 0.12);
  await ended;
}

let controlVersion = 0;
let controlAbort: AbortController | null = null;

/** Permission dialogs cannot be aborted, but their eventual streams must close. */
function abortable<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const cancel = () => reject(new DOMException('Cancelado', 'AbortError'));
    signal.addEventListener('abort', cancel, { once: true });
    if (signal.aborted) cancel();
    promise.then((value) => {
      signal.removeEventListener('abort', cancel);
      if (!signal.aborted) resolve(value);
    }, (error) => {
      signal.removeEventListener('abort', cancel);
      reject(error);
    });
  });
}

export async function setWakeWordEnabled(enabled: boolean): Promise<void> {
  const current = useWakeWordStore.getState();
  if (current.pending && current.desiredEnabled === enabled) return;
  const version = ++controlVersion;
  controlAbort?.abort();
  const controller = new AbortController();
  controlAbort = controller;
  useWakeWordStore.setState({ pending: true, desiredEnabled: enabled, connectionError: null });
  saveWakeIntent(enabled);
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    if (enabled) {
      // Set the mode before awaiting permission, never after a later Off click.
      useInteractionMode.getState().setMode('voice');
      // A blocked autoplay resume must not prevent the detector from starting.
      void prepareWakeAudio().catch(() => {});
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('O navegador não permite acesso ao microfone.');
      const permission = navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
        stream.getTracks().forEach((track) => track.stop());
      });
      await abortable(permission, controller.signal);
    }
    timeout = setTimeout(() => controller.abort(), 8000);
    const response = await abortable(apiFetch('/api/wakeword/control', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled, client_id: wakeClientId }), signal: controller.signal,
    }), controller.signal);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Não foi possível alterar a escuta contínua.');
    }
    const status = await abortable(response.json() as Promise<WakeStatus>, controller.signal);
    if (version === controlVersion) useWakeWordStore.setState({ status });
  } catch (error) {
    if (version !== controlVersion) return; // Replaced by a newer click.
    const message = controller.signal.aborted
      ? 'O detector demorou para responder. Tente novamente.'
      : error instanceof Error ? error.message : 'Falha na escuta contínua.';
    useWakeWordStore.setState({
      desiredEnabled: useInteractionMode.getState().mode === 'voice' ? null : false,
      connectionError: message,
    });
    saveWakeIntent(false);
    throw new Error(message);
  } finally {
    clearTimeout(timeout);
    if (version === controlVersion) {
      useWakeWordStore.setState({ pending: false });
      controlAbort = null;
    }
  }
}

export async function restoreWakeWordIfNeeded(status: WakeStatus): Promise<void> {
  const wake = useWakeWordStore.getState();
  if (wake.connected && !wake.pending && wake.desiredEnabled === true
    && useInteractionMode.getState().mode === 'voice'
    && !status.enabled && status.state === 'disabled' && !status.error) {
    await setWakeWordEnabled(true);
  }
}

// An Off/Text selection cancels pending permission and stops the backend even
// when it has not yet sent a status event claiming this browser as its owner.
const unsubscribeMode = useInteractionMode.subscribe((next, previous) => {
  if (next.mode === 'voice' || next.mode === previous.mode) return;
  const wake = useWakeWordStore.getState();
  if (wake.pending || wake.desiredEnabled === true || (wake.status.enabled && wake.status.owner_id === wakeClientId)) {
    void setWakeWordEnabled(false).catch(() => { /* Error is visible in the store. */ });
  }
});
if (import.meta.hot) import.meta.hot.dispose(unsubscribeMode);

export async function wakeHeartbeat(busy: boolean, signal?: AbortSignal, reason?: string): Promise<void> {
  const response = await apiFetch('/api/wakeword/heartbeat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ busy, reason, client_id: wakeClientId }), signal,
  });
  if (!response.ok) throw new Error('A conexão com a escuta contínua foi interrompida.');
}

export interface WakeEvent extends Partial<WakeStatus>, Partial<WakeTelemetry> { kind: 'status' | 'wake' | 'telemetry'; id?: number }
export async function receiveWakeEvents(signal: AbortSignal, onEvent: (event: WakeEvent) => void): Promise<void> {
  const response = await apiFetch(`/api/wakeword/events?client_id=${encodeURIComponent(wakeClientId)}`, { signal });
  if (!response.ok || !response.body) throw new Error('Não foi possível conectar à palavra de ativação.');
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
  useWakeWordStore.setState({ connected: true, connectionError: null });
  console.info('[wakeword] SSE conectado', wakeClientId);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (!signal.aborted) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let end: number;
      while ((end = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const line = frame.split('\n').find((item) => item.startsWith('data: '));
        if (line) onEvent(JSON.parse(line.slice(6)) as WakeEvent);
      }
    }
  } finally { reader.releaseLock(); }
}
