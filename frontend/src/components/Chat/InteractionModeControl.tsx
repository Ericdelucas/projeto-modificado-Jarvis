import { Mic, Keyboard, Power } from 'lucide-react';
import { useInteractionMode, type InteractionMode } from '../../lib/interaction-mode';

export function InteractionModeControl() {
  const { mode, setMode } = useInteractionMode();
  const Icon = mode === 'voice' ? Mic : mode === 'text' ? Keyboard : Power;
  return (
    <label className="mr-auto flex items-center gap-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
      <Icon size={16} aria-hidden="true" />
      <select
        aria-label="Modo de interação"
        value={mode}
        onChange={(event) => setMode(event.target.value as InteractionMode)}
        className="rounded-md px-2 py-1.5 cursor-pointer"
        style={{ background: 'var(--color-bg-secondary)', color: mode === 'voice' ? 'var(--color-accent)' : 'var(--color-text)', border: '1px solid var(--color-border)' }}
        title="Voz: use o microfone e ouça as respostas. Escrita: chat por texto. Desligado: áudio pausado."
      >
        <option value="voice">Modo Voz</option>
        <option value="text">Modo Escrita</option>
        <option value="off">Desligado</option>
      </select>
    </label>
  );
}
