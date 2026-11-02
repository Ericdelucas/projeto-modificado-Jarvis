import { beforeEach, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { WakeTelemetry } from '../../lib/wakeword';
const fixture = vi.hoisted(() => ({ enabled: true, telemetry: null as WakeTelemetry | null, telemetryAt: 0, pending: false, desiredEnabled: null as boolean | null, connected: true }));
vi.mock('../../lib/wakeword', () => ({
  wakeClientId: 'owner', setWakeWordEnabled: vi.fn(),
  useWakeWordStore: () => ({ status: { enabled: fixture.enabled, owner_id: 'owner', state: fixture.enabled ? 'listening' : 'disabled' }, recording: false, ...fixture }),
}));
import { WakeWordControl } from './WakeWordControl';
beforeEach(() => { fixture.enabled = true; fixture.telemetry = null; fixture.telemetryAt = Date.now(); fixture.pending = false; fixture.desiredEnabled = null; fixture.connected = true; });
it('does not indicate capture merely because the detector is enabled', () => {
  const html = renderToStaticMarkup(<WakeWordControl />);
  expect(html).toContain('Sem áudio do microfone');
  expect(html).not.toContain('animate-pulse');
});
it('shows a pulsing microphone only with fresh processed audio', () => {
  fixture.telemetry = { rms: 0.02, dbfs: -34, frames: 12, processed_frames: 11, audio_bytes: 30720, last_text: 'computador', confidence: 0.9, paused_reason: null, detections: 1 };
  const live = renderToStaticMarkup(<WakeWordControl />);
  expect(live).toContain('Vosk processando');
  expect(live).toContain('animate-pulse');
  expect(live).toContain('aria-valuenow="-34"');
  fixture.telemetryAt = Date.now() - 5000;
  const stale = renderToStaticMarkup(<WakeWordControl />);
  expect(stale).not.toContain('animate-pulse');
  expect(stale).toContain('Sem áudio do microfone');
});


it('keeps the switch clickable to cancel a pending activation', () => {
  fixture.pending = true;
  fixture.desiredEnabled = true;
  const html = renderToStaticMarkup(<WakeWordControl />);
  expect(html).toContain('Ativando…');
  expect(html).toContain('aria-checked="true"');
  expect(html).not.toContain('disabled=""');
});

it('allows switching off when the SSE connection is lost', () => {
  fixture.connected = false;
  const html = renderToStaticMarkup(<WakeWordControl />);
  expect(html).toContain('Sem conexão');
  expect(html).not.toContain('disabled=""');
});

it('reflects an Off click immediately while the backend is still reporting On', () => {
  fixture.pending = true;
  fixture.desiredEnabled = false;
  const html = renderToStaticMarkup(<WakeWordControl />);
  expect(html).toContain('Desativando…');
  expect(html).toContain('aria-checked="false"');
});

it('does not claim activation when backend stopped but the old intent is On', () => {
  fixture.enabled = false;
  fixture.desiredEnabled = true;
  const html = renderToStaticMarkup(<WakeWordControl />);
  expect(html).toContain('aria-checked="false"');
  expect(html).toContain('Desativada');
  expect(html).not.toContain('>Ativada<');
});
