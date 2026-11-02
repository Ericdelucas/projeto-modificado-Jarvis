import type { SpeechState } from '../hooks/useSpeech';
import type { TtsState } from './tts';

export type CoreState = 'idle' | 'listening' | 'processing' | 'speaking';

export const CORE_STATE_LABEL: Record<CoreState, string> = {
  idle: 'Aguardando',
  listening: 'Ouvindo',
  processing: 'Processando',
  speaking: 'Respondendo',
};

export function deriveCoreState(input: {
  mic: SpeechState;
  tts: TtsState;
  isStreaming: boolean;
  hasContent: boolean;
}): CoreState {
  if (input.mic === 'recording') return 'listening';
  if (input.tts === 'speaking') return 'speaking';
  if (input.isStreaming) return input.hasContent ? 'speaking' : 'processing';
  if (input.mic === 'transcribing' || input.tts === 'loading') return 'processing';
  return 'idle';
}
