import { apiFetch } from './api';

export interface PreparedSpeech {
  audio: HTMLAudioElement;
  dispose: () => void;
}

/** Feed MP3 bytes to the audio decoder as soon as they arrive. */
export async function prepareStreamingSpeech(text: string, signal: AbortSignal): Promise<PreparedSpeech> {
  const response = await apiFetch('/api/tts/stream', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }), signal,
  });
  if (!response.ok) throw new Error('Não foi possível gerar a voz neural.');
  let url: string;
  const audio = new Audio();
  const dispose = () => {
    audio.onended = null;
    audio.onerror = null;
    audio.pause();
    audio.src = '';
    if (url) URL.revokeObjectURL(url);
  };
  // Safari/older webviews may require a complete clip. They still receive
  // sentence-sized clips while the model is generating, rather than a full reply.
  if (typeof MediaSource === 'undefined' || !MediaSource.isTypeSupported('audio/mpeg')) {
    const blob = await response.blob();
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    url = URL.createObjectURL(blob);
    audio.src = url;
    signal.addEventListener('abort', dispose, { once: true });
    return { audio, dispose };
  }
  const source = new MediaSource();
  url = URL.createObjectURL(source);
  signal.addEventListener('abort', dispose, { once: true });
  return new Promise<PreparedSpeech>((resolve, reject) => {
    let ready = false;
    audio.onerror = () => { if (!ready) { dispose(); reject(new Error('O navegador não conseguiu decodificar o MP3.')); } };
    source.addEventListener('sourceopen', async () => {
      const reader = response.body!.getReader();
      try {
        const buffer = source.addSourceBuffer('audio/mpeg');
        while (!signal.aborted) {
          const { value, done } = await reader.read();
          if (done) break;
          await new Promise<void>((appended, failed) => {
            const cleanup = () => {
              buffer.removeEventListener('updateend', onEnd);
              buffer.removeEventListener('error', onError);
              signal.removeEventListener('abort', onAbort);
            };
            const onEnd = () => { cleanup(); appended(); };
            const onError = () => { cleanup(); failed(new Error('Falha ao decodificar o áudio.')); };
            const onAbort = () => { cleanup(); failed(new DOMException('Aborted', 'AbortError')); };
            buffer.addEventListener('updateend', onEnd, { once: true });
            buffer.addEventListener('error', onError, { once: true });
            signal.addEventListener('abort', onAbort, { once: true });
            try { buffer.appendBuffer(value); } catch (error) { cleanup(); failed(error); }
          });
          if (!ready) { ready = true; resolve({ audio, dispose }); }
        }
        if (!signal.aborted && source.readyState === 'open') source.endOfStream();
        if (!ready) reject(new Error('O serviço de voz não retornou áudio.'));
      } catch (error) {
        if (!ready) { dispose(); reject(error); }
        else if (!signal.aborted) audio.dispatchEvent(new Event('error'));
      } finally { reader.releaseLock(); }
    }, { once: true });
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
    audio.src = url;
    audio.preload = 'auto';
  });
}
