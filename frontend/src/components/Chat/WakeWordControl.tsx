import { useEffect, useState } from 'react';
import { Ear, Loader2, Mic } from 'lucide-react';
import { toast } from 'sonner';
import { setWakeWordEnabled, useWakeWordStore, wakeClientId } from '../../lib/wakeword';

export function WakeWordControl() {
  const { status, connected, recording, pending, desiredEnabled, telemetry, telemetryAt, connectionError } = useWakeWordStore();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, []);
  const owner = status.owner_id === wakeClientId;
  const backendActive = status.enabled && owner;
  const intendedActive = pending ? desiredEnabled ?? backendActive : backendActive;
  const active = backendActive && connected && desiredEnabled !== false;
  const nextEnabled = !intendedActive;
  const capturing = active && backendActive && !!telemetry && now - telemetryAt < 1800 && telemetry.frames > 0;
  const processing = capturing && !telemetry.paused_reason && telemetry.processed_frames > 0;
  const label = pending ? intendedActive ? 'Ativando…' : 'Desativando…' : !connected ? 'Sem conexão' : status.state === 'error' ? 'Falha no detector' : recording ? 'Ouvindo…' : status.state === 'starting' && owner ? 'Iniciando…'
    : active ? 'Ativada' : status.enabled && !owner ? 'Em outra aba' : 'Desativada';
  const volume = telemetry ? Math.max(0, Math.min(100, (telemetry.dbfs + 65) * 2)) : 0;
  const detail = capturing ? telemetry.paused_reason ? `Pausado: ${telemetry.paused_reason}`
    : telemetry.rms < 0.002 ? 'Sinal baixo / silêncio' : processing ? 'Vosk processando' : 'Capturando áudio'
    : active ? 'Sem áudio do microfone' : 'Microfone do detector desligado';
  return (
    <div className="flex flex-col gap-1 mr-2 min-w-0">
      <button
        type="button" role="switch" aria-checked={intendedActive}
        aria-label={`Escuta Contínua (Palavra de Ativação): ${label}`}
        onClick={() => void setWakeWordEnabled(nextEnabled).catch((error) => toast.error(error instanceof Error ? error.message : 'Não foi possível acessar o microfone.'))}
        className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs cursor-pointer disabled:opacity-50"
        style={{ color: active ? 'var(--color-accent)' : 'var(--color-text-tertiary)', border: '1px solid var(--color-border)' }}
        title={status.error || connectionError || 'Diga “computador” ou “computer”, aguarde o beep e faça seu pedido.'}
      >
        {pending ? <Loader2 size={14} className="animate-spin" /> : <Ear size={14} />}
        <span className="hidden sm:inline">Escuta Contínua (Palavra de Ativação): </span>
        <span aria-live="polite">{label}</span>
      </button>
      {active && (
        <div className="flex items-center gap-1.5 text-[10px] px-1" title={telemetry ? `RMS ${telemetry.rms.toFixed(5)} | ${telemetry.dbfs.toFixed(1)} dBFS | ${telemetry.frames} blocos recebidos | ${telemetry.processed_frames} processados` : detail}>
          <Mic size={12} className={processing ? 'animate-pulse' : ''} style={{ color: processing ? '#22c55e' : capturing ? '#eab308' : 'var(--color-text-tertiary)' }} aria-label={detail} />
          <div role="meter" aria-label="Nível do microfone do Vosk" aria-valuemin={-96} aria-valuemax={0} aria-valuenow={telemetry?.dbfs ?? -96} className="w-12 h-1.5 rounded overflow-hidden" style={{ background: 'var(--color-border)' }}>
            <div className="h-full transition-all duration-150" style={{ width: capturing ? `${volume}%` : '0%', background: '#22c55e' }} />
          </div>
          <span>{detail}</span>
          {capturing && <span>{telemetry.dbfs.toFixed(0)} dB</span>}
        </div>
      )}
      {active && telemetry?.last_text && <span className="text-[10px] truncate max-w-80 px-1" title={telemetry.last_text}>Vosk ({telemetry.language || 'pt'}): “{telemetry.last_text}” · chave: {telemetry.validation === 'partial_stable' ? 'parcial estável' : `${Math.round(telemetry.confidence * 100)}%`}</span>}
      {(status.error || connectionError) && <span role="alert" className="max-w-80 truncate text-xs" title={status.error || connectionError || ''}>{status.error || connectionError}</span>}
    </div>
  );
}
