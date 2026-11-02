// End a microphone utterance after speech followed by a short pause.
// Keep short pauses and isolated clicks from ending a recording immediately.
export class SpeechEndDetector {
  private speechSince: number | null = null;
  private lastSpeech: number | null = null;
  private heardSpeech = false;

  constructor(
    private readonly silenceMs = 650,
    private readonly threshold = 0.01,
    private readonly minSpeechMs = 150,
  ) {}

  update(rms: number, now: number): boolean {
    if (rms >= this.threshold) {
      this.speechSince ??= now;
      if (now - this.speechSince >= this.minSpeechMs) this.heardSpeech = true;
      this.lastSpeech = now;
    } else {
      this.speechSince = null;
    }
    return this.heardSpeech && this.lastSpeech !== null
      && now - this.lastSpeech >= this.silenceMs;
  }
}
