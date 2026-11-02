import { useAppStore } from '../lib/store';
import { useTtsStore } from '../lib/tts';
import { useVoiceActivity } from '../lib/voice-activity';
import { deriveCoreState, type CoreState } from '../lib/core-state';

/** Live HUD core state from the mic, voice output and chat stream. */
export function useCoreState(): CoreState {
  const mic = useVoiceActivity((s) => s.mic);
  const tts = useTtsStore((s) => s.state);
  const isStreaming = useAppStore((s) => s.streamState.isStreaming);
  const hasContent = useAppStore((s) => s.streamState.content !== '');
  return deriveCoreState({ mic, tts, isStreaming, hasContent });
}
