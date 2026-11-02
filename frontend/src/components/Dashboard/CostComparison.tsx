import { DollarSign, TrendingDown, Cloud, HardDrive } from 'lucide-react';
import { useAppStore } from '../../lib/store';
import { SHOW_COST_COMPARISON } from '../../lib/ui-config';

const CLOUD_PRICING = [
  { name: 'GPT-5.6 Sol', input: 5.00, output: 30.00 },
  { name: 'Claude Fable 5', input: 10.00, output: 50.00 },
  { name: 'Gemini 3.1 Pro', input: 2.00, output: 12.00 },
];

export function CostComparison() {
  const savings = useAppStore((s) => s.savings);

  if (!SHOW_COST_COMPARISON) return null;

  if (!savings || savings.total_tokens === 0) {
    return (
      <div className="hud-panel p-6">
        <h3 className="hud-label flex items-center gap-2 mb-4">
          <DollarSign size={12} style={{ color: 'var(--color-success)' }} />
          Comparação de custos
        </h3>
        <div className="h-48 flex items-center justify-center text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
          <span className="hud-mono">aguardando a primeira inferência…</span>
        </div>
      </div>
    );
  }

  const promptK = savings.total_prompt_tokens / 1000;
  const completionK = savings.total_completion_tokens / 1000;

  return (
    <div className="hud-panel p-6">
      <h3 className="hud-label flex items-center gap-2 mb-4">
        <DollarSign size={12} style={{ color: 'var(--color-success)' }} />
        Comparação de custos*
      </h3>

      {/* Local stats */}
      <div
        className="flex items-center gap-3 p-3 rounded-lg mb-3"
        style={{ background: 'var(--color-accent-subtle)', border: '1px solid var(--color-accent)' }}
      >
        <HardDrive size={18} style={{ color: 'var(--color-accent)' }} />
        <div className="flex-1">
          <div className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
            Local (seu computador)
          </div>
          <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            {savings.total_calls} requisições · {savings.total_tokens.toLocaleString()} tokens
          </div>
        </div>
        <div className="text-right">
          <div className="text-lg font-semibold" style={{ color: 'var(--color-success)' }}>
            ${savings.local_cost.toFixed(4)}
          </div>
          <div className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
            apenas eletricidade
          </div>
        </div>
      </div>

      {/* Cloud comparisons */}
      <div className="flex flex-col gap-2">
        {CLOUD_PRICING.map((provider) => {
          const cost = (promptK * provider.input / 1000) + (completionK * provider.output / 1000);
          const saved = cost - savings.local_cost;
          return (
            <div
              key={provider.name}
              className="flex items-center gap-3 p-3 rounded-lg"
              style={{ background: 'var(--color-bg-secondary)' }}
            >
              <Cloud size={16} style={{ color: 'var(--color-text-tertiary)' }} />
              <div className="flex-1">
                <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  {provider.name}
                </div>
              </div>
              <div className="text-right">
                <div className="text-sm font-mono" style={{ color: 'var(--color-text)' }}>
                  ${cost.toFixed(4)}
                </div>
                {saved > 0 && (
                  <div className="text-[10px] flex items-center gap-0.5 justify-end" style={{ color: 'var(--color-success)' }}>
                    <TrendingDown size={10} />
                    ${saved.toFixed(4)} economizados
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 pt-3" style={{ borderTop: '1px solid var(--color-border)' }}>
        <p className="text-[10px] leading-relaxed" style={{ color: 'var(--color-text-tertiary)' }}>
          *As estimativas de economia pressupõem que modelos locais (Qwen, Nemotron, Kimi etc.) geram, em média, aproximadamente a mesma quantidade de tokens por requisição que os modelos proprietários na nuvem.
        </p>
      </div>
    </div>
  );
}
