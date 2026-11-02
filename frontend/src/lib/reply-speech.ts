import { useInteractionMode } from './interaction-mode';
import { useAppStore } from './store';
import { useTtsStore, speechGeneration } from './tts';

/** Buffer words into phrases so synthesis keeps intonation and sentence context. */
export class ReplySpeech {
  private pending = '';
  private cancelled = false;
  private started = false;
  private generation = 0;

  constructor(private conversationId: string, private messageId: string) {
    this.cancelled = useInteractionMode.getState().mode !== 'voice';
  }

  push(delta: string, final = false): void {
    if (this.cancelled) return;
    if (this.started && speechGeneration() !== this.generation) { this.cancelled = true; return; }
    if (useInteractionMode.getState().mode !== 'voice' || useAppStore.getState().activeId !== this.conversationId) {
      this.cancel();
      return;
    }
    this.pending += delta;
    // Do not let unfinished reasoning or code leak into a spoken chunk.
    this.pending = this.pending.replace(/<think>[\s\S]*?<\/think>/gi, '')
      .replace(/```[\s\S]*?```|~~~[\s\S]*?~~~/g, '');
    const blockedAt = this.pending.search(/<think>|```|~~~/i);
    const safe = blockedAt < 0 ? this.pending : this.pending.slice(0, blockedAt);
    let cut = 0;
    if (final) cut = safe.length;
    else {
      const sentences = /[.!?](?:["”')]*)(?=\s)/g;
      for (const match of safe.matchAll(sentences)) {
        const end = match.index! + match[0].length;
        // Group very short greetings with the next sentence, avoiding a clip per word.
        if (end >= 50) { cut = end; break; }
      }
      if (!cut && safe.length >= 260) {
        const comma = safe.lastIndexOf(',', 260);
        cut = comma >= 100 ? comma + 1 : safe.lastIndexOf(' ', 260);
      }
    }
    if (cut > 0) {
      const text = this.pending.slice(0, cut);
      this.pending = this.pending.slice(cut);
      const tts = useTtsStore.getState();
      if (!this.started) { tts.stop(); this.started = true; }
      tts.markAutoSpoken(this.messageId);
      tts.enqueue(this.messageId, text);
      this.generation = speechGeneration();
      // More complete phrases may already be buffered in a large model chunk.
      if (!final && this.pending.length) this.push('');
    }
  }

  finish(): void { this.push('', true); }

  cancel(): void {
    this.cancelled = true;
    this.pending = '';
    if (this.started) useTtsStore.getState().stop();
  }
}
