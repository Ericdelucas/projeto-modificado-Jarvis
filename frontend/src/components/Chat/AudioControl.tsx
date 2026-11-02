import { Volume2, VolumeX } from 'lucide-react';
import { useInteractionMode } from '../../lib/interaction-mode';

export function AudioControl() {
  const { mode, setMode } = useInteractionMode();
  const enabled = mode === 'voice';
  const Icon = enabled ? Volume2 : VolumeX;
  return (
    <button
      type="button"
      role="switch"
      aria-label="Áudio e respostas faladas"
      aria-checked={enabled}
      onClick={() => setMode(enabled ? 'off' : 'voice')}
      className="w-full flex items-center gap-2 rounded-lg px-3 py-2.5 cursor-pointer"
      style={{
        background: enabled ? 'var(--color-accent-subtle)' : 'var(--color-bg-secondary)',
        border: `1px solid ${enabled ? 'var(--color-accent)' : 'var(--color-border)'}`,
        color: enabled ? 'var(--color-accent)' : 'var(--color-text-secondary)',
      }}
      title="OFF interrompe a fala e pausa a escuta automática. O chat por texto continua disponível."
    >
      <Icon size={16} aria-hidden="true" />
      <span className="text-xs flex-1 text-left">Áudio e respostas faladas</span>
      <span className="text-[10px] font-semibold">{enabled ? 'ON' : 'OFF'}</span>
    </button>
  );
}
