import { describe, expect, it } from 'vitest';
import { deriveCoreState } from './core-state';

const base = { mic: 'idle', tts: 'idle', isStreaming: false, hasContent: false } as const;

describe('deriveCoreState', () => {
  it('is idle when nothing happens', () => {
    expect(deriveCoreState(base)).toBe('idle');
  });

  it('listens while the mic records, even during a reply', () => {
    expect(deriveCoreState({ ...base, mic: 'recording', isStreaming: true })).toBe('listening');
  });

  it('processes before the first token and while transcribing or loading voice', () => {
    expect(deriveCoreState({ ...base, isStreaming: true })).toBe('processing');
    expect(deriveCoreState({ ...base, mic: 'transcribing' })).toBe('processing');
    expect(deriveCoreState({ ...base, tts: 'loading' })).toBe('processing');
  });

  it('speaks while text streams in or the voice plays', () => {
    expect(deriveCoreState({ ...base, isStreaming: true, hasContent: true })).toBe('speaking');
    expect(deriveCoreState({ ...base, tts: 'speaking' })).toBe('speaking');
  });
});
