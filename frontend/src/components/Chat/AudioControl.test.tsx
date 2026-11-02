import { beforeEach, expect, it, vi } from 'vitest';
const fixture = vi.hoisted(() => ({
  mode: 'voice',
  setMode: vi.fn((mode: string) => { fixture.mode = mode; }),
}));
vi.mock('../../lib/interaction-mode', () => ({ useInteractionMode: () => fixture }));
import { AudioControl } from './AudioControl';

beforeEach(() => { fixture.mode = 'voice'; vi.clearAllMocks(); });
it('turns voice off and reflects the shared interaction mode', () => {
  expect(AudioControl().props['aria-checked']).toBe(true);
  AudioControl().props.onClick();
  expect(fixture.setMode).toHaveBeenLastCalledWith('off');
  expect(AudioControl().props['aria-checked']).toBe(false);
  AudioControl().props.onClick();
  expect(fixture.setMode).toHaveBeenLastCalledWith('voice');
});
it('shows audio off when text mode is selected in the top bar', () => {
  fixture.mode = 'text';
  expect(AudioControl().props['aria-checked']).toBe(false);
});
