import { Volume2, Square } from 'lucide-react';
import { useTts } from '../../hooks/useTts';
import { useInteractionMode } from '../../lib/interaction-mode';

interface Props {
  messageId: string;
  content: string;
}

/** Reads one assistant message aloud through the server's TTS backend. */
export function SpeakMessageButton({ messageId, content }: Props) {
  const voiceOutputEnabled = useInteractionMode((s) => s.mode === 'voice');
  const { speak, stop, speakingId, available, state, error, errorId } = useTts();

  if (!voiceOutputEnabled || !available) return null;

  // Playback is global, so this button reflects the shared utterance only when
  // that utterance is this message.
  const isMine = speakingId === messageId;
  const busy = isMine && (state === 'loading' || state === 'speaking');
  const messageError = errorId === messageId ? error : null;

  return (
    <>
      <button
        onClick={() => (busy ? stop() : speak(messageId, content))}
        className="p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
        style={{
          color: busy ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
          opacity: busy ? 1 : undefined,
        }}
        title={
          messageError ||
          (isMine && state === 'loading'
            ? 'Synthesizing...'
            : isMine && state === 'speaking'
              ? "Parar"
              : "Ler em voz alta")
        }
        aria-label={busy ? 'Stop reading message' : 'Read message aloud'}
      >
        {busy ? <Square size={14} /> : <Volume2 size={14} />}
      </button>
      {messageError && (
        <span role="alert" className="text-xs" style={{ color: 'var(--color-error)' }}>
          {messageError}
        </span>
      )}
    </>
  );
}
