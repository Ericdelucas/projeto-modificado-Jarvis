import { afterEach, expect, it, vi } from 'vitest';
vi.mock('./api', () => ({ apiFetch: vi.fn() }));
import { apiFetch } from './api';
import { prepareStreamingSpeech } from './streaming-speech';
afterEach(() => vi.unstubAllGlobals());

it('makes the audio ready after the first MP3 chunk, before the response closes', async () => {
  class Buffer extends EventTarget {
    appendBuffer() { queueMicrotask(() => this.dispatchEvent(new Event('updateend'))); }
  }
  let media: Source;
  class Source extends EventTarget {
    static isTypeSupported() { return true; }
    readyState = 'open';
    constructor() { super(); media = this; }
    addSourceBuffer() { return new Buffer(); }
    endOfStream = vi.fn();
  }
  class AudioElement extends EventTarget {
    onended = null;
    onerror = null;
    preload = '';
    set src(value: string) { if (value) queueMicrotask(() => media.dispatchEvent(new Event('sourceopen'))); }
    pause = vi.fn();
  }
  vi.stubGlobal('MediaSource', Source);
  vi.stubGlobal('Audio', AudioElement);
  vi.stubGlobal('URL', { createObjectURL: () => 'blob:stream', revokeObjectURL: vi.fn() });
  let chunks!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start(controller) { chunks = controller; } });
  vi.mocked(apiFetch).mockResolvedValue(new Response(body));
  const controller = new AbortController();
  const ready = prepareStreamingSpeech('Olá, tudo bem?', controller.signal);
  chunks.enqueue(new Uint8Array([1, 2, 3]));
  const clip = await ready;
  expect(clip.audio).toBeInstanceOf(AudioElement);
  expect(media!.endOfStream).not.toHaveBeenCalled();
  chunks.close();
  await vi.waitFor(() => expect(media!.endOfStream).toHaveBeenCalledOnce());
  clip.dispose();
});
