import { useId, useRef } from 'react';
import { AnimatePresence, motion, useAnimationFrame, useReducedMotion } from 'motion/react';
import { CORE_STATE_LABEL, type CoreState } from '../lib/core-state';
import { useCoreState } from '../hooks/useCoreState';

// Degrees per second: three rings, then three particle orbits. Sign = direction.
const SPIN: Record<CoreState, number[]> = {
  idle: [6, -9, 14, 3, -5, 8],
  listening: [10, -14, 20, 6, -9, 12],
  processing: [45, -170, 260, 20, -30, 45],
  speaking: [12, -18, 28, 6, -9, 14],
};
const STILL = [0, 0, 0, 0, 0, 0];

// Breathing of the whole ring stack, per state.
const BREATH: Record<CoreState, { scale: number[]; duration: number }> = {
  idle: { scale: [1, 1.03, 1], duration: 4 },
  listening: { scale: [1, 1.08, 1], duration: 1.1 },
  processing: { scale: [0.97, 0.99, 0.97], duration: 0.6 },
  speaking: { scale: [1, 1.04, 1], duration: 0.7 },
};

const ORBITS = [0, 1, 2].map((orbit) =>
  Array.from({ length: 6 }, (_, i) => {
    const angle = ((i * 60 + orbit * 23) * Math.PI) / 180;
    const radius = 64 + orbit * 12 + (i % 2) * 4;
    return {
      x: 100 + radius * Math.cos(angle),
      y: 100 + radius * Math.sin(angle),
      r: 0.8 + ((i + orbit) % 3) * 0.45,
      opacity: 0.35 + ((i * 7 + orbit) % 5) * 0.12,
    };
  }),
);

const BARS = [0.55, 0.8, 1, 0.7, 0.95, 0.75, 0.5];

interface JarvisCoreProps {
  /** Overrides the live state (useful for previews). */
  state?: CoreState;
  size?: number;
  showLabel?: boolean;
}

export function JarvisCore({ state: forced, size = 220, showLabel = false }: JarvisCoreProps) {
  const live = useCoreState();
  const state = forced ?? live;
  const reduce = useReducedMotion() ?? false;
  const uid = useId().replace(/:/g, '');
  const groups = useRef<(SVGGElement | null)[]>([]);
  const angles = useRef(STILL.slice());
  const speeds = useRef(STILL.slice());

  // One frame loop eases each ring toward its target speed, so switching
  // state accelerates the spin instead of restarting it.
  useAnimationFrame((_, delta) => {
    const target = reduce ? STILL : SPIN[state];
    const dt = Math.min(delta, 64) / 1000;
    const ease = 1 - Math.exp(-dt * 3);
    for (let i = 0; i < target.length; i++) {
      speeds.current[i] += (target[i] - speeds.current[i]) * ease;
      angles.current[i] = (angles.current[i] + speeds.current[i] * dt) % 360;
      groups.current[i]?.setAttribute('transform', `rotate(${angles.current[i].toFixed(2)} 100 100)`);
    }
  });

  const ring = `url(#${uid}-ring)`;
  const intense = state === 'processing';
  const breath = BREATH[state];
  const loop = (duration: number, delay = 0) =>
    reduce ? { duration: 0 } : { duration, delay, repeat: Infinity, ease: 'easeInOut' as const };

  return (
    <div className="flex flex-col items-center gap-3 select-none">
      <svg
        viewBox="0 0 200 200"
        width={size}
        height={size}
        role="img"
        aria-label={`Núcleo do Jarvis: ${CORE_STATE_LABEL[state]}`}
        className="hud-core-glow overflow-visible"
      >
        <defs>
          <radialGradient id={`${uid}-core`}>
            <stop offset="0%" stopColor="var(--core-a)" stopOpacity="0.95" />
            <stop offset="55%" stopColor="var(--core-b)" stopOpacity="0.5" />
            <stop offset="100%" stopColor="var(--core-b)" stopOpacity="0" />
          </radialGradient>
          <linearGradient id={`${uid}-ring`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="var(--core-a)" />
            <stop offset="100%" stopColor="var(--core-b)" />
          </linearGradient>
        </defs>

        {/* Sound-wave ripples while listening. */}
        <AnimatePresence>
          {state === 'listening' && !reduce &&
            [0, 1, 2].map((i) => (
              <motion.circle
                key={`ripple-${i}`}
                cx="100"
                cy="100"
                fill="none"
                stroke="var(--core-a)"
                strokeWidth="1"
                initial={{ r: 40, opacity: 0 }}
                animate={{ r: [40, 99], opacity: [0.7, 0] }}
                exit={{ opacity: 0 }}
                transition={{ duration: 1.5, delay: i * 0.5, repeat: Infinity, ease: 'easeOut' }}
              />
            ))}
        </AnimatePresence>

        <motion.g animate={{ scale: reduce ? 1 : breath.scale }} transition={loop(breath.duration)}>
          {/* Outer ring */}
          <g ref={(el) => { groups.current[0] = el; }}>
            <circle cx="100" cy="100" r="92" fill="none" stroke={ring} strokeWidth="1" strokeDasharray="2 5" opacity="0.8" />
            <circle cx="100" cy="100" r="86" fill="none" stroke={ring} strokeWidth="0.75" strokeDasharray="44 14" opacity="0.45" />
          </g>
          {/* Middle ring */}
          <g ref={(el) => { groups.current[1] = el; }}>
            <motion.circle
              cx="100" cy="100" r="74" fill="none" stroke={ring}
              strokeDasharray="90 26 18 26" strokeLinecap="round"
              animate={{ strokeWidth: intense ? 3.5 : 2.5, opacity: intense ? 1 : 0.75 }}
              transition={{ duration: 0.4 }}
            />
          </g>
          {/* Inner ring */}
          <g ref={(el) => { groups.current[2] = el; }}>
            <motion.circle
              cx="100" cy="100" r="56" fill="none" stroke="var(--core-a)" strokeDasharray="10 7"
              animate={{ strokeWidth: intense ? 2 : 1.25, opacity: intense ? 1 : 0.6 }}
              transition={{ duration: 0.4 }}
            />
            <circle cx="100" cy="100" r="49" fill="none" stroke="var(--core-b)" strokeWidth="0.5" opacity="0.5" />
          </g>
          {/* Particles on three orbits */}
          {ORBITS.map((dots, orbit) => (
            <g key={orbit} ref={(el) => { groups.current[3 + orbit] = el; }}>
              {dots.map((d, i) => (
                <circle key={i} cx={d.x} cy={d.y} r={d.r} fill="var(--core-a)" opacity={d.opacity} />
              ))}
            </g>
          ))}
        </motion.g>

        {/* Core */}
        <motion.circle
          cx="100"
          cy="100"
          r="30"
          fill={`url(#${uid}-core)`}
          animate={{
            scale: reduce ? 1 : intense ? [1, 1.14, 1] : [1, 1.06, 1],
            opacity: state === 'speaking' ? 0.4 : 1,
          }}
          transition={{ scale: loop(intense ? 0.5 : 3), opacity: { duration: 0.3 } }}
        />

        {/* Equalizer while speaking */}
        <AnimatePresence>
          {state === 'speaking' && (
            <motion.g key="eq" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              {BARS.map((peak, i) => (
                <motion.rect
                  key={i}
                  x={81.5 + i * 5.5}
                  y="84"
                  width="3"
                  height="32"
                  rx="1.5"
                  fill={ring}
                  style={{ originY: 0.5 }}
                  initial={{ scaleY: 0.2 }}
                  animate={{ scaleY: reduce ? peak * 0.6 : [0.2, peak, 0.35, peak * 0.8, 0.2] }}
                  transition={loop(0.9 + (i % 3) * 0.15, i * 0.07)}
                />
              ))}
            </motion.g>
          )}
        </AnimatePresence>
      </svg>
      {showLabel && (
        <span className="hud-core-label" aria-live="polite">
          {CORE_STATE_LABEL[state]}
        </span>
      )}
    </div>
  );
}
