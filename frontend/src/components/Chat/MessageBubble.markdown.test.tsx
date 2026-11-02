import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
vi.mock('./SpeakMessageButton', () => ({ SpeakMessageButton: () => null }));
vi.mock('./XRayFooter', () => ({ XRayFooter: () => null }));
import { MessageBubble } from './MessageBubble';
function render(content: string) {
  return renderToStaticMarkup(<MessageBubble message={{ id: 'reply', role: 'assistant', content, timestamp: 1 }} />);
}

describe('chat Markdown layout', () => {
  it('preserves single line breaks and renders bullets and numbered items as separate lists', () => {
    const html = render('Primeira linha\nSegunda linha\n\n- Café\n- Reunião\n\n1. Primeiro\n2. Segundo');
    expect(html).toMatch(/Primeira linha<br\s*\/>\s*Segunda linha/);
    expect(html).toContain('<ul>');
    expect(html).toContain('<ol>');
    for (const item of ['Café', 'Reunião', 'Primeiro', 'Segundo']) expect(html).toContain(`<li>${item}</li>`);
  });
  it('keeps nested list structure and never inserts HTML breaks into fenced code', () => {
    const html = render('- Pai\n  - Filho\n\n```text\nlinha 1\nlinha 2\n```');
    expect(html.match(/<ul>/g)).toHaveLength(2);
    const code = html.match(/<pre[\s\S]*?<\/pre>/)?.[0];
    expect(code).toBeDefined();
    expect(code).not.toContain('<br');
    expect(code).toContain('linha 1\nlinha 2');
  });
});
