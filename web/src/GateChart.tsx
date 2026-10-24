import * as d3 from 'd3';
import { useMemo } from 'react';
import { decidedCount, GATE_MS, hhmm, PERIOD_MS, printedCount, type Derived, type Replay } from './data';
import { useWidth } from './useSize';

const HEIGHT = 380;
const M = { top: 30, right: 14, bottom: 96, left: 48 };
const HOUR = 3_600_000;

/** Lamp colour and strength for a probability that the grid is short. */
export function lamp(p: number): { fill: string; opacity: number } {
  return { fill: p >= 0.5 ? 'var(--short)' : 'var(--long)', opacity: 0.25 + 1.5 * Math.abs(p - 0.5) };
}

interface Props {
  r: Replay;
  d: Derived;
  now: number;
  poison: boolean;
  noiseSeed: number;
}

/**
 * The hero: time flowing past the gate. Printed prices to the left, the hour between deciding
 * and knowing in the middle, the period just decided on the right; below, two rows of lamps,
 * what the forecast said at each gate and what then happened.
 */
export default function GateChart({ r, d, now, poison, noiseSeed }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const gate = Math.floor(now / PERIOD_MS) * PERIOD_MS;      // the latest gate passed
  const target = gate + GATE_MS;                              // the period it decided
  const x = d3.scaleUtc().domain([now - 8 * HOUR, now + (poison ? 8 : 2.6) * HOUR]).range([M.left, width - M.right]);
  const y = d3.scaleSymlog().constant(60).domain([-100, 820]).range([HEIGHT - M.bottom, M.top]).clamp(true);
  const printed = printedCount(d, now);
  const decided = decidedCount(d, now);
  const lampRow = { forecast: HEIGHT - M.bottom + 24, outcome: HEIGHT - M.bottom + 58 };

  const visible = useMemo(() => {
    const lo = now - 8.5 * HOUR;
    const hi = now + 9 * HOUR;
    return r.tape.map((row, i) => ({ row, i, start: d.starts[i] })).filter(({ start }) => start >= lo && start <= hi);
  }, [r, d, now]);

  // Poison: everything first public after the cutoff becomes noise, redrawn on every tick.
  const noise = useMemo(() => {
    const rand = d3.randomLcg(noiseSeed);
    return visible.map(() => ({ price: -100 + rand() * 900, p: rand() }));
  }, [visible, noiseSeed]);
  const afterCutoff = (publishedAt: number) => poison && publishedAt >= d.cutoff;

  const decidedRow = r.tape[(target - d.t0) / PERIOD_MS];
  const ticks = x.ticks(d3.utcHour.every(width > 700 ? 1 : 2)!);

  return (
    <div ref={ref}>
      <svg width={width} height={HEIGHT} role="img" aria-label="Prices, the gate and the forecast lamps">
        {[0, 50, 100, 200, 400, 800].map((v) => (
          <g key={v}>
            <line x1={M.left} x2={width - M.right} y1={y(v)} y2={y(v)} stroke="var(--rule)" strokeWidth={v === 0 ? 1 : 0.6} />
            <text x={M.left - 6} y={y(v) + 4} textAnchor="end">{v}</text>
          </g>
        ))}
        <text x={M.left - 6} y={M.top - 12} textAnchor="end">£/MWh</text>

        {/* The hour between deciding and knowing, and the period just decided. */}
        <rect x={x(gate)} y={M.top} width={x(target) - x(gate)} height={HEIGHT - M.bottom - M.top} fill="var(--ink)" opacity={0.05} />
        <text x={(x(gate) + x(target)) / 2} y={M.top - 12} textAnchor="middle">the hour between deciding and knowing</text>
        {decidedRow && !poison && (
          <g>
            <rect x={x(target)} y={M.top} width={x(target + PERIOD_MS) - x(target)} height={HEIGHT - M.bottom - M.top}
              fill="none" stroke={lamp(decidedRow.p_ours).fill} strokeWidth={1.5} strokeDasharray="4 3" />
            <text x={x(target + PERIOD_MS) + 4} y={M.top + 12} className="readout">
              {decidedRow.p_ours >= 0.5 ? 'short' : 'long'} {(100 * Math.max(decidedRow.p_ours, 1 - decidedRow.p_ours)).toFixed(0)}%
            </text>
            <text x={x(target + PERIOD_MS) + 4} y={M.top + 27}>
              {decidedRow.ours.action > 0 ? 'discharge' : decidedRow.ours.action < 0 ? 'charge' : 'hold'} {hhmm(target)}
            </text>
          </g>
        )}

        {/* Printed prices, as steps; noise after the cutoff when poisoned. */}
        {visible.map(({ row, i, start }, k) => {
          const printsAt = start + 52 * 60_000;
          if (printsAt > now && !afterCutoff(printsAt)) return null;
          const price = afterCutoff(printsAt) ? noise[k].price : row.price;
          return (
            <line key={i} x1={x(start)} x2={x(start + PERIOD_MS)} y1={y(price)} y2={y(price)}
              stroke={afterCutoff(printsAt) ? 'var(--short)' : 'var(--ink)'} strokeWidth={2} strokeLinecap="round" />
          );
        })}

        {/* Two lamp rows: the forecast at each gate, and what happened. */}
        <text x={M.left} y={lampRow.forecast - 6}>forecast at the gate</text>
        <text x={M.left} y={lampRow.outcome - 6}>what happened</text>
        {visible.map(({ row, i, start }, k) => {
          const gateTime = start - GATE_MS;
          const forecastKnown = i < decided || afterCutoff(gateTime);
          const outcomeKnown = i < printed || afterCutoff(start + 52 * 60_000);
          const w = Math.max(1, x(start + PERIOD_MS) - x(start) - 1.5);
          const f = lamp(afterCutoff(gateTime) ? noise[k].p : row.p_ours);
          const o = afterCutoff(start + 52 * 60_000) ? lamp(noise[k].p) : { fill: row.short ? 'var(--short)' : 'var(--long)', opacity: 0.95 };
          return (
            <g key={i}>
              {forecastKnown && <rect className="lamp" x={x(start)} y={lampRow.forecast} width={w} height={11} rx={2} fill={f.fill} opacity={f.opacity} />}
              {outcomeKnown && <rect className="lamp" x={x(start)} y={lampRow.outcome} width={w} height={11} rx={2} fill={o.fill} opacity={o.opacity} />}
            </g>
          );
        })}

        {/* The clock's own position, and the poison cutoff. */}
        <line x1={x(now)} x2={x(now)} y1={M.top - 4} y2={lampRow.outcome + 12} stroke="var(--ink)" strokeWidth={1} />
        {poison && (
          <g>
            <rect x={x(d.cutoff)} y={M.top} width={width - M.right - x(d.cutoff)} height={HEIGHT - M.bottom - M.top} fill="var(--short)" opacity={0.06} />
            <text x={x(d.cutoff) + 8} y={M.top + 14} style={{ fill: 'var(--short)' }}>everything published after this line is noise</text>
          </g>
        )}

        {ticks.map((t) => (
          <text key={+t} x={x(t)} y={HEIGHT - 6} textAnchor="middle">{hhmm(+t)}</text>
        ))}
      </svg>
    </div>
  );
}
