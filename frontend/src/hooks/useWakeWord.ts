import { useEffect, useRef } from 'react';
import { toast } from 'sonner';
import { useInteractionMode } from '../lib/interaction-mode';
import { receiveWakeEvents, restoreWakeWordIfNeeded, setWakeWordEnabled, useWakeWordStore, wakeClientId, wakeHeartbeat, type WakeStatus, type WakeTelemetry } from '../lib/wakeword';

/** One SSE receiver per chat, with a lease that closes an abandoned microphone. */
export function useWakeWord(onWake: () => Promise<void>, busy: boolean, recording: boolean, busyReason?: string, onDisabled?: () => void) {
  const callback = useRef(onWake);
  callback.current = onWake;
  const mode = useInteractionMode((s) => s.mode);
  const status = useWakeWordStore((s) => s.status);
  const desiredEnabled = useWakeWordStore((s) => s.desiredEnabled);
  const owner = status.owner_id === wakeClientId && status.enabled;
  useEffect(() => {
    if (desiredEnabled === false) onDisabled?.();
  }, [desiredEnabled, onDisabled]);
  const lastEvent = useRef<number | undefined>(undefined);
  const activating = useRef(false);

  useEffect(() => {
    useWakeWordStore.setState({ recording });
    return () => useWakeWordStore.setState({ recording: false });
  }, [recording]);

  useEffect(() => {
    const controller = new AbortController();
    let retry: ReturnType<typeof setTimeout>;
    const connect = async () => {
      try {
        await receiveWakeEvents(controller.signal, (event) => {
          if (event.kind === 'status') {
            console.info('[wakeword] Estado do backend', event.state, { enabled: event.enabled, owner: event.owner_id });
            useWakeWordStore.setState({ status: event as WakeStatus });
            void restoreWakeWordIfNeeded(event as WakeStatus).catch(error => toast.error(String(error)));
            return;
          }
          if (event.kind === 'telemetry') {
            useWakeWordStore.setState({ telemetry: event as WakeTelemetry, telemetryAt: Date.now() });
            return;
          }
          if (event.kind !== 'wake') return;
          console.info('[wakeword] Ativação recebida', event);
          const current = useWakeWordStore.getState();
          if (event.id === lastEvent.current || activating.current || !current.status.enabled || current.desiredEnabled === false || useInteractionMode.getState().mode !== 'voice' || current.status.owner_id !== wakeClientId) {
            console.info('[wakeword] Evento ignorado: duplicado, ativação em curso ou outra aba');
            return;
          }
          lastEvent.current = event.id;
          activating.current = true;
          void wakeHeartbeat(true, undefined, 'ativando').then(() => callback.current())
            .catch((error) => toast.error(error instanceof Error ? error.message : 'Falha na ativação por voz.'))
            .finally(() => { activating.current = false; });
        });
      } catch (error) {
        if (!controller.signal.aborted) {
          console.warn('[wakeword] SSE desconectado', error);
          useWakeWordStore.setState({ connectionError: error instanceof Error ? error.message : 'Conexão com o detector perdida.' });
        }
      }
      // A StrictMode/HMR cleanup must not disconnect the replacement stream.
      if (controller.signal.aborted) return;
      useWakeWordStore.setState({ connected: false });
      if (!controller.signal.aborted) retry = setTimeout(() => void connect(), 2000);
    };
    void connect();
    return () => { controller.abort(); clearTimeout(retry); };
  }, []);

  useEffect(() => {
    if (!owner || desiredEnabled === false) return;
    if (mode !== 'voice') {
      void setWakeWordEnabled(false).catch((error) => toast.error(String(error)));
      return;
    }
    const controller = new AbortController();
    const heartbeat = () => void wakeHeartbeat(busy, controller.signal, busyReason).catch(() => {});
    heartbeat();
    const timer = setInterval(heartbeat, 1500);
    return () => { clearInterval(timer); controller.abort(); };
  }, [owner, mode, busy, busyReason, desiredEnabled]);
}
