import { expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
const fixture = vi.hoisted(() => ({ mode: 'voice', setMode: vi.fn((mode: string) => { fixture.mode = mode; }) }));
vi.mock('../../lib/interaction-mode', () => ({ useInteractionMode: () => fixture }));
import { InteractionModeControl } from './InteractionModeControl';
function select() {
  const control = InteractionModeControl();
  return (control.props.children as ReactElement[]).find((child) => child.type === 'select') as ReactElement<{
    value: string;
    onChange: (event: { target: { value: string } }) => void;
  }>;
}
it('binds mode changes to the select and reflects switching Off and back to Voice', () => {
  select().props.onChange({ target: { value: 'off' } });
  expect(fixture.setMode).toHaveBeenLastCalledWith('off');
  expect(select().props.value).toBe('off');
  select().props.onChange({ target: { value: 'voice' } });
  expect(select().props.value).toBe('voice');
});
