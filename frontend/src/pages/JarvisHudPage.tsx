import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { Cpu, Radio, CircuitBoard, ArrowUpRight } from 'lucide-react';
import { JarvisCore } from '../components/JarvisCore';
import { AudioControl } from '../components/Chat/AudioControl';
import { useCoreState } from '../hooks/useCoreState';
import { CORE_STATE_LABEL } from '../lib/core-state';
import { fetchSystemLoad, type SystemLoad } from '../lib/api';
import { useAppStore } from '../lib/store';
import { ChatPage } from './ChatPage';

function LoadMeter({ label, value, detail }: { label: string; value?: number; detail: string }) {
  const percent = value == null ? null : Math.min(100, Math.max(0, value));
  return (
    <div className="reactor-meter">
      <div className="reactor-meter-label"><span>{label}</span><strong>{percent == null ? '—' : `${Math.round(percent)}%`}</strong></div>
      <div className="reactor-meter-track" role="meter" aria-label={`Uso de ${label}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent ?? undefined}>
        <i style={{ width: `${percent ?? 0}%` }} />
      </div>
      <small>{detail}</small>
    </div>
  );
}

/** The home route is the HUD, even when a previous chat is restored. */
export function JarvisHudPage() {
  const state = useCoreState();
  const model = useAppStore(s => s.selectedModel || s.serverInfo?.model || 'Conectando…');
  const [load, setLoad] = useState<SystemLoad | null>(null);
  useEffect(() => {
    let alive = true;
    const refresh = () => fetchSystemLoad().then(data => { if (alive) setLoad(data); }).catch(() => { if (alive) setLoad(null); });
    void refresh();
    const timer = setInterval(refresh, 3000);
    return () => { alive = false; clearInterval(timer); };
  }, []);
  return (
    <section className="reactor-home" data-testid="jarvis-hud-home">
      <header className="reactor-masthead">
        <div><span className="reactor-eyebrow">PERSONAL INTELLIGENCE SYSTEM</span><h1>J.A.R.V.I.S<span> / CONTROL DECK</span></h1></div>
        <span className="reactor-link-state"><i />{load ? 'TELEMETRIA CONECTADA' : 'AGUARDANDO TELEMETRIA'}</span>
      </header>
      <div className="reactor-deck">
        <aside className="reactor-panel reactor-hardware">
          <h2><Cpu size={14} /> HARDWARE / LIVE</h2>
          <LoadMeter label="CPU" value={load?.cpu_percent} detail={load ? 'PROCESSAMENTO DO SISTEMA' : 'Sem leitura do servidor'} />
          <LoadMeter label="GPU" value={load?.gpu?.percent} detail={load?.gpu?.name || 'GPU não informada pelo servidor'} />
        </aside>
        <div className="reactor-stage">
          <div className="reactor-crosshair" aria-hidden="true" />
          <span className="reactor-coordinate">NEURAL CORE // 01</span>
          <JarvisCore state={state} size={250} showLabel />
          <span className="reactor-coordinate reactor-coordinate-bottom">LOCAL INFERENCE · {CORE_STATE_LABEL[state].toUpperCase()}</span>
        </div>
        <aside className="reactor-panel reactor-session">
          <h2><CircuitBoard size={14} /> CENTRAL DE CONTROLE</h2>
          <span className="reactor-eyebrow">MODELO SELECIONADO</span><strong className="reactor-model">{model}</strong>
          <div className="reactor-state"><Radio size={15} />{CORE_STATE_LABEL[state]}</div>
          <AudioControl />
          <Link to="/dashboard" className="reactor-dashboard-link">Abrir telemetria completa <ArrowUpRight size={14} /></Link>
        </aside>
      </div>
      <div className="reactor-console-heading"><span>CANAL DE COMUNICAÇÃO</span><span>JARVIS / TERMINAL ATIVO</span></div>
      <div className="reactor-conversation"><ChatPage embeddedHud /></div>
    </section>
  );
}
