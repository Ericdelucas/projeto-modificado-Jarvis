import { describe, expect, it } from 'vitest';
import { SpeechEndDetector } from './speech-vad';

describe('microphone endpoint detection', () => {
  it('allows conversational pauses with the recorder silence window', () => {
    const detector = new SpeechEndDetector(1100);
    detector.update(0.1, 0);
    detector.update(0.1, 200);
    expect(detector.update(0, 1000)).toBe(false);
    expect(detector.update(0, 1300)).toBe(true);
  });
  it('waits for speech instead of submitting startup silence or a click', () => {
    const detector = new SpeechEndDetector();
    expect(detector.update(0, 0)).toBe(false);
    expect(detector.update(0.1, 100)).toBe(false);
    expect(detector.update(0, 150)).toBe(false);
    expect(detector.update(0, 5000)).toBe(false);
  });

  it('keeps short pauses and stops 650 ms after the last speech sample', () => {
    const detector = new SpeechEndDetector();
    detector.update(0.1, 0);
    detector.update(0.1, 200);
    expect(detector.update(0, 600)).toBe(false);
    expect(detector.update(0.1, 650)).toBe(false);
    expect(detector.update(0, 1299)).toBe(false);
    expect(detector.update(0, 1300)).toBe(true);
  });
});
