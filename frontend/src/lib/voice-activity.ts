import { create } from 'zustand';
import type { SpeechState } from '../hooks/useSpeech';

interface VoiceActivity {
  mic: SpeechState;
  setMic: (mic: SpeechState) => void;
}

/** Microphone state shared outside the component that owns the recorder. */
export const useVoiceActivity = create<VoiceActivity>((set) => ({
  mic: 'idle',
  setMic: (mic) => set({ mic }),
}));
