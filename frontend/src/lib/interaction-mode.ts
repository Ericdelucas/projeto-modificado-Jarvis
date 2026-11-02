import { useAppStore } from './store';
import { stripThinkTags } from './message-text';
import { create } from 'zustand';
import { useTtsStore } from './tts';

export type InteractionMode = 'voice' | 'text' | 'off';
const MODE_KEY = 'jarvis-interaction-mode';
function savedMode(): InteractionMode {
  try {
    const mode = sessionStorage.getItem(MODE_KEY);
    if (mode === 'voice' || mode === 'text' || mode === 'off') return mode;
  } catch { /* Storage may be unavailable. */ }
  return 'voice';
}
export const useInteractionMode = create<{
  mode: InteractionMode;
  setMode: (mode: InteractionMode) => void;
}>((set) => ({
  mode: savedMode(),
  setMode: (mode) => {
    // Update the control immediately, even if media cleanup fails.
    set({ mode });
    try { sessionStorage.setItem(MODE_KEY, mode); } catch { /* Keep in-memory preference. */ }
    useTtsStore.getState().stop();
  },
}));

/** Called once by the response receiver after a successful completion. */
export function autoplayCompletedReply(conversationId: string, messageId: string, content: string): void {
  const tts = useTtsStore.getState();
  const text = stripThinkTags(content).trim();
  if (useInteractionMode.getState().mode !== 'voice' || !text) return;
  if (useAppStore.getState().activeId !== conversationId || tts.autoSpokenId === messageId) return;
  tts.markAutoSpoken(messageId);
  void tts.speak(messageId, text);
}
