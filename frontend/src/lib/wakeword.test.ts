import { beforeEach, afterEach, expect, it, vi } from 'vitest';
vi.mock('./api', () => ({ apiFetch: vi.fn() }));
vi.mock('./tts', () => ({ useTtsStore: { getState: () => ({ stop: vi.fn() }) } }));
vi.mock('./store', () => ({ useAppStore: { getState: () => ({ activeId: null }) } }));
import { useInteractionMode } from './interaction-mode';
import { apiFetch } from './api';
import { receiveWakeEvents, restoreWakeWordIfNeeded, setWakeWordEnabled, useWakeWordStore, wakeClientId } from './wakeword';
beforeEach(() => {
  useInteractionMode.setState({ mode: 'voice' });
  useWakeWordStore.setState(useWakeWordStore.getInitialState());
  vi.mocked(apiFetch).mockReset();
  vi.stubGlobal('AudioContext', class { state = 'running'; resume = vi.fn(async () => {}); });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it('parses wake events split across network chunks without replaying events', async () => {
  const chunks = ['data: {"kind":"sta', 'tus","enabled":true}\n\n', ': ping\n\ndata: {"kind":"wake","id":1}\n\n'];
  const body = new ReadableStream({ start(controller) { for (const part of chunks) controller.enqueue(new TextEncoder().encode(part)); controller.close(); } });
  vi.mocked(apiFetch).mockResolvedValue(new Response(body));
  const receive = vi.fn();
  await receiveWakeEvents(new AbortController().signal, receive);
  expect(receive).toHaveBeenCalledTimes(2);
  expect(receive.mock.calls[1][0]).toEqual({ kind: 'wake', id: 1 });
});

it('can enable even if autoplay leaves AudioContext.resume pending', async () => {
  vi.stubGlobal('AudioContext', class { state = 'suspended'; resume = () => new Promise(() => {}); });
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(async () => ({ getTracks: () => [] })) } });
  vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({ enabled: true, state: 'listening' })));
  await setWakeWordEnabled(true);
  expect(useWakeWordStore.getState().pending).toBe(false);
  expect(useWakeWordStore.getState().status.enabled).toBe(true);
});

it('requests microphone permission once on enabling and releases the permission stream', async () => {
  const stop = vi.fn();
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop }] })) } });
  vi.stubGlobal('AudioContext', class { state = 'running'; resume = vi.fn(async () => {}); });
  vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({ enabled: true, state: 'listening' })));
  await setWakeWordEnabled(true);
  expect(stop).toHaveBeenCalledOnce();
  expect(useWakeWordStore.getState().status.enabled).toBe(true);
  expect(apiFetch).toHaveBeenCalledWith('/api/wakeword/control', expect.objectContaining({ method: 'POST' }));
});


it('does not let an aborted SSE connection mark its replacement as connected', async () => {
  useWakeWordStore.setState({ connected: false });
  const controller = new AbortController();
  controller.abort();
  vi.mocked(apiFetch).mockResolvedValue(new Response('data: {"kind":"status"}\n\n'));
  await expect(receiveWakeEvents(controller.signal, vi.fn())).rejects.toMatchObject({ name: 'AbortError' });
  expect(useWakeWordStore.getState().connected).toBe(false);
});

it('delivers RMS diagnostics as telemetry rather than activation events', async () => {
  vi.mocked(apiFetch).mockResolvedValue(new Response('data: {"kind":"telemetry","rms":0.02,"frames":42,"processed_frames":40}\n\n'));
  const receive = vi.fn();
  await receiveWakeEvents(new AbortController().signal, receive);
  expect(receive).toHaveBeenCalledExactlyOnceWith({ kind: 'telemetry', rms: 0.02, frames: 42, processed_frames: 40 });
});


function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
const disabledResponse = () => new Response(JSON.stringify({ enabled: false, state: 'disabled' }));

it('can turn off while microphone permission is pending and closes a late permission stream', async () => {
  const permission = deferred<MediaStream>();
  const getUserMedia = vi.fn(() => permission.promise);
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } });
  vi.mocked(apiFetch).mockResolvedValue(disabledResponse());
  const enabling = setWakeWordEnabled(true);
  await vi.waitFor(() => expect(getUserMedia).toHaveBeenCalledOnce());
  await setWakeWordEnabled(false);
  await enabling;
  const stop = vi.fn();
  permission.resolve({ getTracks: () => [{ stop }] } as unknown as MediaStream);
  await vi.waitFor(() => expect(stop).toHaveBeenCalledOnce());
  expect(useWakeWordStore.getState().pending).toBe(false);
  expect(useWakeWordStore.getState().desiredEnabled).toBe(false);
  expect(JSON.parse(vi.mocked(apiFetch).mock.calls[0][1]!.body as string).enabled).toBe(false);
});

it('an Off mode click cancels activation and cannot be overwritten by permission arriving later', async () => {
  const permission = deferred<MediaStream>();
  const getUserMedia = vi.fn(() => permission.promise);
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } });
  vi.mocked(apiFetch).mockResolvedValue(disabledResponse());
  const enabling = setWakeWordEnabled(true);
  await vi.waitFor(() => expect(getUserMedia).toHaveBeenCalledOnce());
  useInteractionMode.getState().setMode('off');
  await enabling;
  await vi.waitFor(() => expect(useWakeWordStore.getState().pending).toBe(false));
  permission.resolve({ getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream);
  await Promise.resolve();
  expect(useInteractionMode.getState().mode).toBe('off');
  expect(useWakeWordStore.getState().desiredEnabled).toBe(false);
});

it('a slow older enable response cannot overwrite a more recent disable click', async () => {
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(async () => ({ getTracks: () => [] })) } });
  const oldResponse = deferred<Response>();
  vi.mocked(apiFetch).mockReturnValueOnce(oldResponse.promise).mockResolvedValueOnce(disabledResponse());
  const enabling = setWakeWordEnabled(true);
  await vi.waitFor(() => expect(apiFetch).toHaveBeenCalledOnce());
  await setWakeWordEnabled(false);
  await enabling;
  oldResponse.resolve(new Response(JSON.stringify({ enabled: true, state: 'listening' })));
  await Promise.resolve();
  expect(useWakeWordStore.getState().status.enabled).toBe(false);
  expect(useWakeWordStore.getState().pending).toBe(false);
});

it('network timeouts release the control instead of leaving it pending forever', async () => {
  vi.useFakeTimers();
  vi.mocked(apiFetch).mockReturnValue(new Promise(() => {}));
  const pending = setWakeWordEnabled(false);
  const rejected = expect(pending).rejects.toThrow('demorou');
  await vi.advanceTimersByTimeAsync(8000);
  await rejected;
  expect(useWakeWordStore.getState().pending).toBe(false);
});

it('restores an enabled session after backend disconnection', async () => {
  useWakeWordStore.setState({ connected: true, desiredEnabled: true });
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(async () => ({ getTracks: () => [] })) } });
  const setItem = vi.fn();
  vi.stubGlobal('sessionStorage', { setItem });
  vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({ enabled: true, state: 'listening', owner_id: wakeClientId })));
  await restoreWakeWordIfNeeded(useWakeWordStore.getState().status);
  expect(useWakeWordStore.getState().status.enabled).toBe(true);
  expect(setItem).toHaveBeenCalledWith('openjarvis-wakeword-enabled', 'true');
});

it('never restores after Off or while another tab owns the detector', async () => {
  vi.mocked(apiFetch).mockResolvedValue(disabledResponse());
  useWakeWordStore.setState({ connected: true, desiredEnabled: false });
  await restoreWakeWordIfNeeded(useWakeWordStore.getState().status);
  useWakeWordStore.setState({ desiredEnabled: true });
  await restoreWakeWordIfNeeded({ ...useWakeWordStore.getState().status, enabled: true, owner_id: 'other' });
  useInteractionMode.setState({ mode: 'off' });
  await restoreWakeWordIfNeeded(useWakeWordStore.getState().status);
  expect(vi.mocked(apiFetch).mock.calls.every(([, init]) => JSON.parse(init!.body as string).enabled === false)).toBe(true);
});
