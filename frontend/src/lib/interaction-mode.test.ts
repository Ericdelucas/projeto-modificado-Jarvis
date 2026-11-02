import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./store', () => ({ useAppStore: { getState: () => ({ activeId: 'chat' }) } }));
vi.mock('./tts', () => ({ useTtsStore: { getState: vi.fn() } }));
import { useTtsStore } from './tts';

beforeEach(() => {
  vi.resetModules();
  vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: vi.fn() });
});

describe('interaction modes and completed replies', () => {
  it('starts in voice mode and speaks a completed reply exactly once', async () => {
    const speak = vi.fn();
    const state = { speak, autoSpokenId: null as string | null, markAutoSpoken: (id: string) => { state.autoSpokenId = id; }, stop: vi.fn() };
    vi.mocked(useTtsStore.getState).mockReturnValue(state as unknown as ReturnType<typeof useTtsStore.getState>);
    const { useInteractionMode, autoplayCompletedReply } = await import('./interaction-mode');
    expect(useInteractionMode.getState().mode).toBe('voice');
    autoplayCompletedReply('chat', 'reply', 'Olá!');
    autoplayCompletedReply('chat', 'reply', 'Olá!');
    expect(speak).toHaveBeenCalledExactlyOnceWith('reply', 'Olá!');
    useInteractionMode.getState().setMode('text');
    autoplayCompletedReply('chat', 'next', 'Outra resposta');
    useInteractionMode.getState().setMode('off');
    autoplayCompletedReply('chat', 'third', 'Outra resposta');
    expect(speak).toHaveBeenCalledTimes(1);
    expect(state.stop).toHaveBeenCalledTimes(2);
  });

  it('preserves the selected mode after reload', async () => {
    vi.stubGlobal('sessionStorage', { getItem: () => 'text' });
    const { useInteractionMode } = await import('./interaction-mode');
    expect(useInteractionMode.getState().mode).toBe('text');
  });
  it('preserves Off after reload', async () => {
    vi.stubGlobal('sessionStorage', { getItem: () => 'off' });
    const { useInteractionMode } = await import('./interaction-mode');
    expect(useInteractionMode.getState().mode).toBe('off');
  });
});
