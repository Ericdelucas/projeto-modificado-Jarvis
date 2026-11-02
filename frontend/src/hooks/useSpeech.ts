import { useState, useCallback, useRef, useEffect } from 'react';
import { transcribeAudio, fetchSpeechHealth } from '../lib/api';
import { SpeechEndDetector } from '../lib/speech-vad';
import { useVoiceActivity } from '../lib/voice-activity';

export type SpeechState = 'idle' | 'recording' | 'transcribing';

export function useSpeech(onTranscript?: (text: string) => void) {
  const [state, setState] = useState<SpeechState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [available, setAvailable] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const onTranscriptRef = useRef(onTranscript);
  const monitorRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const completionRef = useRef<Promise<string> | null>(null);
  const mountedRef = useRef(true);
  const startingRef = useRef(false);
  const generationRef = useRef(0);

  useEffect(() => { onTranscriptRef.current = onTranscript; }, [onTranscript]);

  // Mirror the mic state globally so the HUD core can react to it.
  useEffect(() => {
    useVoiceActivity.getState().setMic(state);
    return () => useVoiceActivity.getState().setMic('idle');
  }, [state]);

  const releaseMicrophone = useCallback(() => {
    if (monitorRef.current !== null) clearInterval(monitorRef.current);
    monitorRef.current = null;
    const context = contextRef.current;
    contextRef.current = null;
    if (context && context.state !== 'closed') void context.close().catch(() => {});
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const recorder = mediaRecorderRef.current;
      if (recorder) {
        recorder.onstop = null;
        recorder.ondataavailable = null;
        if (recorder.state === 'recording') recorder.stop();
      }
      releaseMicrophone();
    };
  }, [releaseMicrophone]);

  // Recover when the UI mounts before a restarted speech server is ready.
  useEffect(() => {
    let cancelled = false;
    let retry: ReturnType<typeof setTimeout>;
    const probe = async () => {
      let ready = false;
      try { ready = (await fetchSpeechHealth()).available; } catch { /* Retry below. */ }
      if (cancelled) return;
      setAvailable(ready);
      if (!ready) retry = setTimeout(() => void probe(), 5000);
    };
    void probe();
    return () => { cancelled = true; clearTimeout(retry); };
  }, []);

  const startRecording = useCallback(async (): Promise<void> => {
    if (startingRef.current || mediaRecorderRef.current || streamRef.current) return;
    setError(null);

    if (!navigator.mediaDevices?.getUserMedia) {
      setError('O microfone não é compatível com este navegador.');
      return;
    }

    const generation = ++generationRef.current;
    startingRef.current = true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: {
        echoCancellation: true, noiseSuppression: true, autoGainControl: true,
      } });
      if (!mountedRef.current || generation !== generationRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;

      const mimeType = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus']
        .find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      completionRef.current = new Promise<string>((resolve) => {
        recorder.onstop = async () => {
          releaseMicrophone();
          if (!mountedRef.current || generation !== generationRef.current) {
            if (mediaRecorderRef.current === recorder) mediaRecorderRef.current = null;
            resolve(''); return;
          }
          setState('transcribing');
          const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
          chunksRef.current = [];
          const extension = blob.type.includes('ogg') ? 'ogg' : blob.type.includes('mp4') ? 'm4a' : 'webm';
          try {
            console.info('[speech] Enviando gravação', { bytes: blob.size, format: blob.type });
            const result = await transcribeAudio(blob, `gravacao.${extension}`);
            console.info('[speech] Transcrição concluída', { characters: result.text.trim().length, duration: result.duration_seconds });
            if (!result.text.trim()) {
              throw new Error('Não consegui entender a fala. Verifique o microfone selecionado no navegador, fale após o sinal e tente novamente.');
            }
            if (mountedRef.current && generation === generationRef.current) onTranscriptRef.current?.(result.text);
            resolve(result.text);
          } catch (err) {
            if (mountedRef.current && generation === generationRef.current) setError(err instanceof Error ? err.message : 'Falha na transcrição.');
            resolve('');
          } finally {
            if (mediaRecorderRef.current === recorder) mediaRecorderRef.current = null;
            if (mountedRef.current && generation === generationRef.current) setState('idle');
          }
        };
      });
      recorder.start(100);
      console.info('[speech] Microfone capturando', {
        device: stream.getAudioTracks()[0]?.label,
        settings: stream.getAudioTracks()[0]?.getSettings(),
      });
      mediaRecorderRef.current = recorder;
      setState('recording');
      // Browser-side endpoint detection reduces the delay BEFORE uploading.
      // Silero VAD in Whisper separately removes silence after upload.
      try {
        const context = new AudioContext();
        contextRef.current = context;
        await context.resume();
        if (!mountedRef.current || recorder.state !== 'recording') {
          releaseMicrophone();
          return;
        }
        const source = context.createMediaStreamSource(stream);
        const analyser = context.createAnalyser();
        analyser.fftSize = 2048;
        source.connect(analyser);
        const samples = new Uint8Array(analyser.fftSize);
        const detector = new SpeechEndDetector(1100);
        const started = performance.now();
        monitorRef.current = setInterval(() => {
          if (recorder.state !== 'recording') return;
          analyser.getByteTimeDomainData(samples);
          const rms = Math.sqrt(samples.reduce((sum, value) => sum + ((value - 128) / 128) ** 2, 0) / samples.length);
          const now = performance.now();
          if (detector.update(rms, now) || now - started >= 60_000) recorder.stop();
        }, 50);
      } catch {
        // Recording still works with the manual stop button if Web Audio fails.
      }
    } catch (err) {
      releaseMicrophone();
      mediaRecorderRef.current = null;
      setError('Não foi possível acessar o microfone. Verifique a permissão do navegador.');
      setState('idle');
    } finally {
      startingRef.current = false;
    }
  }, [releaseMicrophone]);

  const stopRecording = useCallback(async (): Promise<string> => {
    const recorder = mediaRecorderRef.current;
    if (recorder?.state === 'recording') recorder.stop();
    return completionRef.current ?? '';
  }, []);

  const cancelRecording = useCallback(() => {
    generationRef.current += 1;
    const recorder = mediaRecorderRef.current;
    if (recorder?.state === 'recording') recorder.stop();
    releaseMicrophone();
    setState('idle');
  }, [releaseMicrophone]);

  return {
    cancelRecording,
    state,
    error,
    available,
    startRecording,
    stopRecording,
    isRecording: state === 'recording',
    isTranscribing: state === 'transcribing',
  };
}
