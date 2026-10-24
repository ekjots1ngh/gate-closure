import * as d3 from 'd3';
import { useMemo, useState } from 'react';
import { decidedCount, GATE_MS, gbp, hhmm, PERIOD_MS, PRINT_MS, printedCount, side, sure, tone, verb, type Derived, type Replay } from './data';
import { useSize } from './useSize';

const HOUR = 3_600_000;
const BACK_HOURS = 7;                        // history on screen
const AHEAD_HOURS = 2.9;                     // the gate band and the period just decided
const M = { top: 22, right: 16, left: 112 };
const TRACK = 20;                            // px either side of the 50% line in the P(short) track
const FULL = 0.4;                            // a call this far from 50% (a 90% call) fills the track
const STRIP = 8;                             // the outcome strip's height
const AXIS = 20;
const FLASH_MS = 900;                        // a print is marked for this long, scaled by the replay's speed

interface Props {
  r: Replay;
  d: Derived;
  now: number;
  poison: boolean;
  noiseSeed: number;
}

/**
 * The hero: time flowing past the gate. Printed prices as steps on the left, the hour between
 * deciding and knowing in the middle, the period just decided on the right. Below, the call made
 * at each gate as a bar from 50% (up for short, down for long, as tall as the call was sure), and
 * under it what then happened.
 */
export default function GateChart({ r, d, now, poison, noiseSeed }: Props) {
  const [ref, { width, height }] = useSize<HTMLDivElement>({ width: 800, height: 380 });
  const gate = Math.floor(now / PERIOD_MS) * PERIOD_MS;      // the latest gate passed
  const target = gate + GATE_MS;                              // the period it decided
  const printed = printedCount(d, now);
  const decided = decidedCount(d, now);

  const stripTop = height - AXIS - 8 - STRIP;
  const centre = stripTop - 8 - TRACK;
  const plotBottom = centre - TRACK - 14;
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
  const real = steps.filter((s) => !s.poisoned);
  const newest = real.length ? real[real.length - 1] : undefined;
  const justPrinted = newest !== undefined && now - newest.printsAt < FLASH_MS * 4;

  // Linear while prices are ordinary; a symlog scale once a spike is on screen, so £800 and £80 both read.
  const shown = steps.map((s) => s.price);
  const yMax = Math.max(140, 1.12 * (d3.max(shown) ?? 0));
  const yMin = Math.min(0, (d3.min(shown) ?? 0) - 10);
  const spiky = yMax > 320;
  const y = (spiky ? d3.scaleSymlog().constant(80) : d3.scaleLinear()).domain([yMin, yMax]).range([plotBottom, M.top]).clamp(true);
  const gridValues = spiky ? [0, 50, 100, 200, 400, 800].filter((v) => v <= yMax) : y.ticks(4);
  const stepPath = d3.line<{ x: number; y: number }>().x((p) => p.x).y((p) => p.y)(
    real.flatMap((s) => [{ x: x(s.start), y: y(s.price) }, { x: x(s.start + PERIOD_MS), y: y(s.price) }]),
  ) ?? '';

  const decidedRow = r.tape[(target - d.t0) / PERIOD_MS];
  const ticks = x.ticks(d3.utcHour.every(width > 760 ? 1 : 2)!);
  const bar = (p: number) => Math.max(1.5, (Math.min(FULL, Math.abs(p - 0.5)) / FULL) * TRACK);

  // Hovering a half hour that has been decided reads out the call, the outcome and the money.
  const [hover, setHover] = useState<number | null>(null);
  const inspected = hover !== null && hover < decided && !poison ? r.tape[hover] : null;
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const px = e.clientX - e.currentTarget.getBoundingClientRect().left;
    const i = Math.floor((x.invert(px).getTime() - d.t0) / PERIOD_MS);
    setHover(px > M.left && i >= 0 && i < d.n ? i : null);
  };

  return (
    <div ref={ref} className="fill">
      <svg width={width} height={height} role="img" aria-label="Prices, the gate, the call at each gate and what happened"
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        <defs>
          <clipPath id="plot"><rect x={M.left} y={0} width={Math.max(0, width - M.right - M.left)} height={height} /></clipPath>
        </defs>
        {gridValues.map((v) => (
          <g key={v}>
            <line x1={M.left} x2={width - M.right} y1={y(v)} y2={y(v)} stroke="var(--rule)" strokeWidth={v === 0 ? 1 : 0.6} opacity={v === 0 ? 1 : 0.6} />
            <text x={M.left - 8} y={y(v) + 4} textAnchor="end">{v}</text>
          </g>
        ))}
        <text x={M.left - 8} y={M.top - 8} textAnchor="end">£/MWh</text>

        {/* The hour between deciding and knowing, and the period just decided. */}
        <rect x={x(gate)} y={M.top - 4} width={x(target) - x(gate)} height={stripTop + STRIP + 4 - M.top} fill="var(--ink)" opacity={0.055} />
        <text x={(x(gate) + x(target)) / 2} y={M.top - 8} textAnchor="middle">the hour between deciding and knowing</text>
        {decidedRow && !poison && (
          <g>
            <rect x={x(target)} y={M.top - 4} width={x(target + PERIOD_MS) - x(target)} height={stripTop + STRIP + 4 - M.top}
              fill="none" stroke={tone(side(decidedRow.p_ours))} strokeWidth={1.5} strokeDasharray="4 3" />
            <text x={x(target + PERIOD_MS) + 7} y={M.top + 12} className="readout" style={{ fontSize: 15, fontWeight: 700, fill: tone(side(decidedRow.p_ours)) }}>
              {side(decidedRow.p_ours)} {sure(decidedRow.p_ours)}%
            </text>
            <text x={x(target + PERIOD_MS) + 7} y={M.top + 29}>{verb(decidedRow.ours.action)} at {hhmm(target)}</text>
          </g>
        )}

        {/* Printed prices as steps; noise after the cutoff when poisoned. */}
        <g clipPath="url(#plot)">
          <path d={stepPath} fill="none" stroke="var(--ink)" strokeWidth={2} strokeLinejoin="round" />
          {steps.filter((s) => s.poisoned).map((s) => (
            <line key={s.i} x1={x(s.start)} x2={x(s.start + PERIOD_MS)} y1={y(s.price)} y2={y(s.price)} stroke="var(--short)" strokeWidth={2} />
          ))}
        </g>
        {newest && (
          <g>
            <circle cx={x(newest.start + PERIOD_MS)} cy={y(newest.price)} r={4} fill="var(--panel)" stroke="var(--ink)" strokeWidth={2} />
            {justPrinted && <circle key={newest.i} className="print-flash" cx={x(newest.start + PERIOD_MS)} cy={y(newest.price)} stroke="var(--ink)" />}
            <text x={x(newest.start + PERIOD_MS) + 8} y={y(newest.price) + 4} className="readout">{gbp(newest.price)}</text>
          </g>
        )}

        {/* The call at each gate, as a bar from 50%, and what happened. */}
        <text x={M.left - 8} y={centre - TRACK + 9} textAnchor="end">called short</text>
        <text x={M.left - 8} y={centre + TRACK - 1} textAnchor="end">called long</text>
        <text x={M.left - 8} y={stripTop + STRIP} textAnchor="end">what happened</text>
        <line x1={M.left} x2={width - M.right} y1={centre} y2={centre} stroke="var(--rule)" />
        {visible.map(({ row, i, start }, k) => {
          const left = Math.max(M.left, x(start) + 1);
          const w = Math.min(width - M.right, x(start + PERIOD_MS)) - left - 1;
          if (w <= 0) return null;
          const gateTime = start - GATE_MS;
          const p = afterCutoff(gateTime) ? noise[k].p : row.p_ours;
          const called = i < decided || afterCutoff(gateTime);
          const outcome = afterCutoff(start + PRINT_MS) ? side(noise[k].p) : i < printed ? (row.short ? 'short' : 'long') : null;
          const h = bar(p);
          return (
            <g key={i}>
              {called && <rect className="lamp" x={left} y={p >= 0.5 ? centre - h : centre} width={w} height={h} fill={tone(side(p))} />}
              <rect className="lamp" x={left} y={stripTop} width={w} height={STRIP} rx={1.5} fill={outcome ? tone(outcome) : 'var(--lamp-off)'} />
            </g>
          );
        })}

        {/* The clock's own position, and the poison cutoff. */}
        <line x1={x(now)} x2={x(now)} y1={M.top - 4} y2={stripTop + STRIP + 2} stroke="var(--ink)" strokeWidth={1} />
        {poison && (
          <g>
            <rect x={x(d.cutoff)} y={M.top - 4} width={width - M.right - x(d.cutoff)} height={stripTop + STRIP + 4 - M.top} fill="var(--short)" opacity={0.07} />
            <text x={x(d.cutoff) + 8} y={M.top + 12} style={{ fill: 'var(--short)' }}>everything published after this line is noise</text>
          </g>
        )}

        {inspected && (() => {
          const start = d.starts[hover!];
          const printedYet = hover! < printed;
          const left = Math.min(Math.max(x(start) + 10, M.left), width - M.right - 250);
          const hit = (inspected.p_ours >= 0.5) === (inspected.short === 1);
          const lines = [
            `${hhmm(start)}: called ${side(inspected.p_ours)}, ${sure(inspected.p_ours)}%; ${verb(inspected.ours.action)}`,
            printedYet ? `printed ${gbp(inspected.price)}, the grid was ${inspected.short ? 'short' : 'long'}: ${hit ? 'right' : 'wrong'}` : 'price not printed yet',
            printedYet ? `the battery made ${gbp(inspected.ours.pnl)}` : '',
          ].filter(Boolean);
          return (
            <g pointerEvents="none">
              <rect x={x(start)} y={M.top - 4} width={Math.max(1, x(start + PERIOD_MS) - x(start))} height={stripTop + STRIP + 4 - M.top} fill="var(--ink)" opacity={0.08} />
              <rect x={left} y={M.top + 34} width={246} height={14 + 17 * lines.length} rx={3} fill="var(--recess)" stroke="var(--rule)" />
              {lines.map((line, n) => <text key={n} x={left + 10} y={M.top + 52 + 17 * n} style={{ fill: n === 0 ? 'var(--ink)' : undefined }}>{line}</text>)}
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
