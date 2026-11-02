import { useEffect, useState } from 'react';
import { apiFetch } from '../../lib/api';

export function AutomationControl() {
  const [paused, setPaused] = useState(false);
  const [reason, setReason] = useState('');
  const [pending, setPending] = useState(false);
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const response = await apiFetch('/api/automation/status');
        if (!response.ok) return;
        const status = await response.json();
        if (alive) { setPaused(status.stopped); setReason(status.reason || 'Parada de segurança'); }
      } catch { /* Status will be retried. */ }
    };
    void poll();
    const timer = setInterval(poll, 3000);
    return () => { alive = false; clearInterval(timer); };
  }, []);
  if (!paused) return null;
  const resume = async () => {
    setPending(true);
    try {
      const response = await apiFetch('/api/automation/resume', { method: 'POST' });
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Não foi possível reativar.');
      }
      setPaused(false);
    } catch (error) { setReason(error instanceof Error ? error.message : 'Falha ao reativar'); }
    finally { setPending(false); }
  };
  return (
    <div role="alert" className="flex items-center gap-2 text-xs rounded-md px-2 py-1" style={{ border: '1px solid #f5a524', color: '#f5a524' }} title={reason}>
      <span>Automação pausada</span>
      <button type="button" disabled={pending} onClick={() => void resume()} className="underline cursor-pointer">
        {pending ? 'Reativando…' : 'Reativar'}
      </button>
    </div>
  );
}
