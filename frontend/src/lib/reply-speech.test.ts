import { beforeEach, describe, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({ mode: 'voice', activeId: 'chat', generation: 0, enqueue: vi.fn(), stop: vi.fn(), markAutoSpoken: vi.fn() }));
vi.mock('./interaction-mode', () => ({ useInteractionMode: { getState: () => state } }));
vi.mock('./store', () => ({ useAppStore: { getState: () => state } }));
vi.mock('./tts', () => ({ useTtsStore: { getState: () => state }, speechGeneration: () => state.generation }));
import { ReplySpeech } from './reply-speech';
beforeEach(() => { state.mode = 'voice'; state.activeId = 'chat'; state.generation = 0; vi.clearAllMocks(); });

describe('speech during model streaming', () => {
  it('sends a complete phrase before the model finishes, then flushes only the remainder', () => {
    const reply = new ReplySpeech('chat', 'reply');
    reply.push('Olá! Vamos conversar sobre como organizar melhor o seu dia. ');
    expect(state.enqueue).toHaveBeenCalledTimes(1);
    reply.push('Posso ajudar você.');
    reply.finish();
    expect(state.enqueue).toHaveBeenCalledTimes(2);
    expect(state.enqueue.mock.calls[1][1].trim()).toBe('Posso ajudar você.');
  });
  it('does not read reasoning or code, including blocks split across chunks', () => {
    const reply = new ReplySpeech('chat', 'reply');
    reply.push('<think>Segredo. Ainda pensando.');
    expect(state.enqueue).not.toHaveBeenCalled();
    reply.push('</think>```python\nprint("segredo")');
    reply.push('\n```Olá! Como posso ajudar você hoje?');
    reply.finish();
    expect(state.enqueue).toHaveBeenCalledExactlyOnceWith('reply', 'Olá! Como posso ajudar você hoje?');
  });
  it('stops adding audio after the user stops playback or changes mode', () => {
    const reply = new ReplySpeech('chat', 'reply');
    reply.push('Esta é uma frase completa com contexto suficiente para leitura. ');
    state.generation++;
    reply.push('Esta frase seguinte não deve ser reproduzida. ');
    reply.finish();
    expect(state.enqueue).toHaveBeenCalledTimes(1);
    state.mode = 'text';
    new ReplySpeech('chat', 'other').push('Mensagem por texto.', true);
    expect(state.enqueue).toHaveBeenCalledTimes(1);
  });
});
