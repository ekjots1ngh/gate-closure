import * as d3 from 'd3';
import { useMemo, useState } from 'react';
import { decidedCount, GATE_MS, gbp, hhmm, PERIOD_MS, PRINT_MS, printedCount, type Derived, type Replay } from './data';
import { useSize } from './useSize';

const HOUR = 3_600_000;
const BACK_HOURS = 7;                        // history on screen
const AHEAD_HOURS = 2.4;                     // the gate band and the period just decided
const M = { top: 26, right: 16, left: 128 };
const LAMP = 16;                             // lamp height in px
const LAMP_GAP = 6;
const AXIS = 22;
const FLASH_MS = 900;                        // a price's print is marked for this long

/** Lamp colour and strength for a probability that the grid is short. */
export function lamp(p: number): { fill: string; opacity: number } {
  return { fill: p >= 0.5 ? 'var(--short)' : 'var(--long)', opacity: 0.3 + 1.4 * Math.abs(p - 0.5) };
}

interface Props {
  r: Replay;
  d: Derived;
  now: number;
  poison: boolean;
  noiseSeed: number;
}

/**
 * The hero: time flowing past the gate. Printed prices to the left as steps, the hour between
 * deciding and knowing in the middle, the period just decided on the right; below, two rows of
 * lamps, what the forecast said at each gate and what then happened.
 */
export default function GateChart({ r, d, now, poison, noiseSeed }: Props) {
  const [ref, { width, height }] = useSize<HTMLDivElement>({ width: 800, height: 380 });
  const gate = Math.floor(now / PERIOD_MS) * PERIOD_MS;      // the latest gate passed
  const target = gate + GATE_MS;                              // the period it decided
  const printed = printedCount(d, now);
  const decided = decidedCount(d, now);

  const lampTop = height - AXIS - 2 * LAMP - LAMP_GAP - 10;
  const rows = { forecast: lampTop, outcome: lampTop + LAMP + LAMP_GAP };
  const plotBottom = lampTop - 18;
  const x = d3.scaleUtc().domain([now - BACK_HOURS * HOUR, now + (poison ? 7 : AHEAD_HOURS) * HOUR]).range([M.left, width - M.right]);

  const visible = useMemo(() => {
    const lo = now - (BACK_HOURS + 0.5) * HOUR;
    const hi = now + 8 * HOUR;
    return r.tape.map((row, i) => ({ row, i, start: d.starts[i] })).filter(({ start }) => start >= lo && start <= hi);
  }, [r, d, now]);

  // Poison: everything first public after the cutoff becomes noise, redrawn on every tick.
  const noise = useMemo(() => {
    const rand = d3.randomLcg(noiseSeed);
    return visible.map(() => ({ price: -80 + rand() * 880, p: rand() }));
  }, [visible, noiseSeed]);
  const afterCutoff = (publishedAt: number) => poison && publishedAt >= d.cutoff;

  // The printed steps on screen: real prices, or noise where poisoned.
  const steps = visible.flatMap(({ row, i, start }, k) => {
    const printsAt = start + PRINT_MS;
    if (printsAt > now && !afterCutoff(printsAt)) return [];
    const poisoned = afterCutoff(printsAt);
    return [{ i, start, printsAt, poisoned, price: poisoned ? noise[k].price : row.price }];
  });
  const shown = steps.map((s) => s.price);
  const yMax = Math.max(160, 1.15 * (d3.max(shown) ?? 0));
  const yMin = Math.min(-20, (d3.min(shown) ?? 0) - 10);
  const y = d3.scaleSymlog().constant(80).domain([yMin, yMax]).range([plotBottom, M.top]).clamp(true);
  const gridValues = [0, 50, 100, 200, 400, 800].filter((v) => v <= yMax);

  const stepPath = d3.line<{ x: number; y: number }>().x((p) => p.x).y((p) => p.y)(
    steps.filter((s) => !s.poisoned).flatMap((s) => [{ x: x(s.start), y: y(s.price) }, { x: x(s.start + PERIOD_MS), y: y(s.price) }]),
  ) ?? '';
  const real = steps.filter((s) => !s.poisoned);
  const newest = real.length ? real[real.length - 1] : undefined;
  const justPrinted = newest && now - newest.printsAt < FLASH_MS * 4;   // the replay runs faster than real time

  const decidedRow = r.tape[(target - d.t0) / PERIOD_MS];
  const ticks = x.ticks(d3.utcHour.every(width > 760 ? 1 : 2)!);

  // Hovering a half hour that has been decided reads out what was forecast, what happened and what it earned.
  const [hover, setHover] = useState<number | null>(null);
  const inspected = hover !== null && hover < decided && !poison ? r.tape[hover] : null;
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const px = e.clientX - e.currentTarget.getBoundingClientRect().left;
    const i = Math.floor((x.invert(px).getTime() - d.t0) / PERIOD_MS);
    setHover(i >= 0 && i < d.n ? i : null);
  };

  return (
    <div ref={ref} className="fill">
      <svg width={width} height={height} role="img" aria-label="Prices, the gate and the forecast lamps"
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {gridValues.map((v) => (
          <g key={v}>
            <line x1={M.left} x2={width - M.right} y1={y(v)} y2={y(v)} stroke="var(--rule)" strokeWidth={v === 0 ? 1 : 0.6} />
            <text x={M.left - 8} y={y(v) + 4} textAnchor="end">{v}</text>
          </g>
        ))}
        <text x={M.left - 8} y={M.top - 10} textAnchor="end">£/MWh</text>

        {/* The hour between deciding and knowing, and the period just decided. */}
        <rect x={x(gate)} y={M.top - 4} width={x(target) - x(gate)} height={plotBottom - M.top + 4} fill="var(--ink)" opacity={0.06} />
        <text x={(x(gate) + x(target)) / 2} y={M.top - 10} textAnchor="middle">the hour between deciding and knowing</text>
        {decidedRow && !poison && (
          <g>
            <rect x={x(target)} y={M.top - 4} width={x(target + PERIOD_MS) - x(target)} height={plotBottom - M.top + 4}
              fill="none" stroke={lamp(decidedRow.p_ours).fill} strokeWidth={1.5} strokeDasharray="4 3" />
            <text x={x(target + PERIOD_MS) + 6} y={M.top + 10} className="readout" style={{ fontSize: 13 }}>
              {decidedRow.p_ours >= 0.5 ? 'short' : 'long'} {(100 * Math.max(decidedRow.p_ours, 1 - decidedRow.p_ours)).toFixed(0)}%
            </text>
            <text x={x(target + PERIOD_MS) + 6} y={M.top + 27}>
              {decidedRow.ours.action > 0 ? 'discharge' : decidedRow.ours.action < 0 ? 'charge' : 'hold'} at {hhmm(target)}
            </text>
          </g>
        )}

        {/* Printed prices as steps; noise after the cutoff when poisoned. */}
        <path d={stepPath} fill="none" stroke="var(--ink)" strokeWidth={2} strokeLinejoin="round" />
        {steps.filter((s) => s.poisoned).map((s) => (
          <line key={s.i} x1={x(s.start)} x2={x(s.start + PERIOD_MS)} y1={y(s.price)} y2={y(s.price)} stroke="var(--short)" strokeWidth={2} />
        ))}
        {newest && (
          <g>
            <circle cx={x(newest.start + PERIOD_MS)} cy={y(newest.price)} r={4} fill="var(--panel)" stroke="var(--ink)" strokeWidth={2} />
            {justPrinted && <circle key={newest.i} className="print-flash" cx={x(newest.start + PERIOD_MS)} cy={y(newest.price)} stroke="var(--ink)" />}
            <text x={x(newest.start + PERIOD_MS) + 8} y={y(newest.price) + 4} className="readout">{newest.price.toFixed(0)}</text>
          </g>
        )}

        {/* Two lamp rows: the forecast at each gate, and what happened. */}
        <text x={M.left - 8} y={rows.forecast + LAMP / 2 + 4} textAnchor="end">forecast at the gate</text>
        <text x={M.left - 8} y={rows.outcome + LAMP / 2 + 4} textAnchor="end">what happened</text>
        {visible.map(({ row, i, start }, k) => {
          const gateTime = start - GATE_MS;
          const forecastKnown = i < decided || afterCutoff(gateTime);
          const outcomeKnown = i < printed || afterCutoff(start + PRINT_MS);
          const left = Math.max(M.left, x(start));
          const w = Math.min(width - M.right, x(start + PERIOD_MS)) - left - 2;
          if (w <= 0) return null;
          const f = lamp(afterCutoff(gateTime) ? noise[k].p : row.p_ours);
          const o = afterCutoff(start + PRINT_MS) ? lamp(noise[k].p) : { fill: row.short ? 'var(--short)' : 'var(--long)', opacity: 0.95 };
          return (
            <g key={i}>
              <rect x={left} y={rows.forecast} width={w} height={LAMP} rx={2} fill="var(--lamp-off)" />
              <rect x={left} y={rows.outcome} width={w} height={LAMP} rx={2} fill="var(--lamp-off)" />
              {forecastKnown && <rect className="lamp" x={left} y={rows.forecast} width={w} height={LAMP} rx={2} fill={f.fill} opacity={f.opacity} />}
              {outcomeKnown && <rect className="lamp" x={left} y={rows.outcome} width={w} height={LAMP} rx={2} fill={o.fill} opacity={o.opacity} />}
            </g>
          );
        })}

        {/* The clock's own position, and the poison cutoff. */}
        <line x1={x(now)} x2={x(now)} y1={M.top - 4} y2={rows.outcome + LAMP + 2} stroke="var(--ink)" strokeWidth={1} />
        {poison && (
          <g>
            <rect x={x(d.cutoff)} y={M.top - 4} width={width - M.right - x(d.cutoff)} height={plotBottom - M.top + 4} fill="var(--short)" opacity={0.07} />
            <text x={x(d.cutoff) + 8} y={M.top + 12} style={{ fill: 'var(--short)' }}>everything published after this line is noise</text>
          </g>
        )}

        {inspected && (() => {
          const start = d.starts[hover!];
          const printedYet = hover! < printed;
          const left = Math.min(Math.max(x(start), M.left), width - M.right - 232);
          const lines = [
            `${hhmm(start)}: forecast ${inspected.p_ours >= 0.5 ? 'short' : 'long'} ${(100 * Math.max(inspected.p_ours, 1 - inspected.p_ours)).toFixed(0)}%`,
            `ours ${inspected.ours.action > 0 ? 'discharged' : inspected.ours.action < 0 ? 'charged' : 'held'}` + (printedYet ? `, ${gbp(inspected.ours.pnl)}` : ''),
            printedYet ? `price ${gbp(inspected.price)}/MWh, the grid was ${inspected.short ? 'short' : 'long'}` : 'price not printed yet',
          ];
          return (
            <g pointerEvents="none">
              <rect x={x(start)} y={M.top - 4} width={Math.max(1, x(start + PERIOD_MS) - x(start))} height={rows.outcome + LAMP + 6 - M.top} fill="var(--ink)" opacity={0.08} />
              <rect x={left} y={plotBottom - 66} width={228} height={58} rx={3} fill="var(--recess)" stroke="var(--rule)" />
              {lines.map((line, k) => <text key={k} x={left + 10} y={plotBottom - 48 + 17 * k} style={{ fill: k === 0 ? 'var(--ink)' : undefined }}>{line}</text>)}
            </g>
          );
        })()}

        {ticks.map((t) => (
          <text key={+t} x={x(t)} y={height - 6} textAnchor="middle">{hhmm(+t)}</text>
        ))}
      </svg>
    </div>
  );
}
