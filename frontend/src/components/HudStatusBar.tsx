import { useEffect, useState } from 'react';
import { useAppStore } from '../lib/store';
import { fetchSystemLoad, getMemoryStats, type SystemLoad } from '../lib/api';
import { CORE_STATE_LABEL, type CoreState } from '../lib/core-state';

function Dot({ ok }: { ok: boolean | null }) {
  const color = ok === null ? 'var(--color-text-tertiary)' : ok ? 'var(--color-success)' : 'var(--color-error)';
  return <span className="inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle" style={{ background: color }} />;
}

/** Compact HUD readout: core state, active model, RAG and CPU/GPU load. */
export function HudStatusBar({ state }: { state: CoreState }) {
  const model = useAppStore((s) => s.selectedModel || s.serverInfo?.model || '');
  const [load, setLoad] = useState<SystemLoad | null>(null);
  const [rag, setRag] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    const poll = () =>
      fetchSystemLoad()
        .then((value) => alive && setLoad(value))
        .catch(() => alive && setLoad(null));
    poll();
    const interval = setInterval(poll, 5000);
    return () => { alive = false; clearInterval(interval); };
  }, []);

  useEffect(() => {
    let alive = true;
    const probe = () =>
      getMemoryStats()
        .then(() => alive && setRag(true))
        .catch(() => alive && setRag(false));
    probe();
    const interval = setInterval(probe, 60000);
    return () => { alive = false; clearInterval(interval); };
  }, []);

  const gpu = load?.gpu;
  const gpuName = gpu?.name.replace(/^NVIDIA\s+(GeForce\s+)?/i, '');

  return (
    <div className="hud-frame flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-1.5" role="status">
      <span className="hud-chip">Estado <b>{CORE_STATE_LABEL[state]}</b></span>
      <span className="hud-chip">Modelo <b>{model || '—'}</b></span>
      <span className="hud-chip" title={rag === false ? 'Memória (RAG) indisponível no servidor' : undefined}>
        <Dot ok={rag} />RAG <b>{rag === null ? '…' : rag ? 'Conectado' : 'Offline'}</b>
      </span>
      <span className="hud-chip">CPU <b>{load ? `${Math.round(load.cpu_percent)}%` : '—'}</b></span>
      <span className="hud-chip" title={gpu?.name}>
        GPU <b>{gpu ? `${gpuName} · ${Math.round(gpu.percent)}%` : '—'}</b>
      </span>
    </div>
  );
}
