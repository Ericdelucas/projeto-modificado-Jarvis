import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  joined: false,
  fetchIdentity: vi.fn(),
  savePreference: vi.fn(),
  setOptIn: vi.fn(),
}));
vi.mock('../lib/store', () => ({
  useAppStore: (selector: (state: Record<string, unknown>) => unknown) => selector({
    setOptIn: mocks.setOptIn,
    optInDisplayName: '',
    optInEmail: '',
    optInEnabled: mocks.joined,
  }),
}));
vi.mock('../lib/analytics', () => ({
  fetchAnalyticsIdentity: mocks.fetchIdentity,
  saveAnalyticsPreference: mocks.savePreference,
}));

import { OptInModal } from './OptInModal';

beforeEach(() => {
  mocks.joined = false;
  vi.clearAllMocks();
});

describe('existing sharing modal', () => {
  it('offers explicit analytics actions without a checkbox or side effects on render', () => {
    const html = renderToStaticMarkup(<OptInModal onClose={vi.fn()} />);
    expect(html).not.toContain('type="checkbox"');
    expect(html).toContain('Ativar estatísticas e participar do sorteio');
    expect(html).toContain('Participar apenas do sorteio');
    expect(html).toContain('Ativar apenas estatísticas');
    expect(html).toContain('Continuar sem compartilhar');
    expect(html).toContain('Ganhe um Mac mini');
    expect(html).toContain('Seu nome e sua economia são públicos');
    expect(mocks.savePreference).not.toHaveBeenCalled();
    expect(mocks.setOptIn).not.toHaveBeenCalled();
  });

  it('allows existing leaderboard members to change analytics independently', () => {
    mocks.joined = true;
    const html = renderToStaticMarkup(<OptInModal onClose={vi.fn()} />);
    expect(html).toContain('Ativar estatísticas');
    expect(html).toContain('Parar atualizações do ranking');
    expect(mocks.savePreference).not.toHaveBeenCalled();
  });
});
