import * as d3 from 'd3';
import { useState } from 'react';
import { gbp, type Replay } from './data';
import { useWidth } from './useSize';

// The three real forecasts sit within 0.02 of Brier of each other, so each label is a callout:
// (dx, dy) is where its text starts, in pixels from the point.
const REAL = [
  { model: 'ours', label: 'ours', policy: 'chain/ours', dx: -14, dy: -18 },
  { model: 'persistence_cal', label: 'persistence', policy: 'chain/persistence_cal', dx: 18, dy: 34 },
  { model: 'indicated', label: "NESO's forecast", policy: 'chain/indicated', dx: -18, dy: 48 },
];
const HEIGHT = 300;
const COIN = 0.25;   // the Brier score of always saying 50%

/** Scale our forecast's errors up or down and re-run the same battery: what accuracy is worth in pounds a day. */
export default function Skill({ r }: { r: Replay }) {
  const curve = [...r.value_of_skill.chain].sort((a, b) => a.k - b.k);
  const [k, setK] = useState(1);
  const at = interpolate(curve, k);
  const [ref, width] = useWidth<HTMLDivElement>(600);
  const m = { top: 14, right: 20, bottom: 36, left: 52 };
  const x = d3.scaleLinear().domain([0.3, 0]).range([m.left, width - m.right]);
  const y = d3.scaleLinear().domain([-60, 240]).range([HEIGHT - m.bottom, m.top]);
  const schedule = r.money['chain/schedule'];
  const path = d3.line<{ brier: number; gbp: number }>().x((p) => x(p.brier)).y((p) => y(p.gbp))(curve.filter((p) => p.brier <= 0.3)) ?? '';
  const breakEven = crossing(curve, schedule.value);
  const real = Math.abs(k - 1) < 0.005;

  return (
    <div className="inset" ref={ref}>
      <h2>What the skill is worth</h2>
      <svg width={width} height={HEIGHT} role="img" aria-label="Money per day against forecast accuracy">
        {y.ticks(5).map((v) => (
          <g key={v}>
            <line x1={m.left} x2={width - m.right} y1={y(v)} y2={y(v)} stroke="var(--rule)" strokeWidth={v === 0 ? 1 : 0.6} opacity={v === 0 ? 1 : 0.6} />
            <text x={m.left - 6} y={y(v) + 4} textAnchor="end">{gbp(v)}</text>
          </g>
        ))}
        {x.ticks(6).map((v) => (
          <text key={v} x={x(v)} y={HEIGHT - 20} textAnchor="middle">{v.toFixed(2)}</text>
        ))}
        <text x={width - m.right} y={HEIGHT - 4} textAnchor="end">Brier score, better to the right</text>

        {/* No forecast: the fixed schedule, with its interval; and the coin, always saying 50%. */}
        <rect x={m.left} y={y(schedule.hi)} width={width - m.right - m.left} height={y(schedule.lo) - y(schedule.hi)} fill="var(--schedule)" opacity={0.1} />
        <line x1={m.left} x2={width - m.right} y1={y(schedule.value)} y2={y(schedule.value)} stroke="var(--schedule)" strokeDasharray="5 4" />
        <text x={width - m.right} y={y(schedule.lo) + 14} textAnchor="end">no forecast: the fixed schedule, {gbp(schedule.value)} a day</text>
        <line x1={x(COIN)} x2={x(COIN)} y1={m.top} y2={HEIGHT - m.bottom} stroke="var(--ink-faint)" strokeDasharray="2 4" />
        <text x={x(COIN) - 5} y={m.top + 10} textAnchor="end">coin-flip accuracy</text>
        {breakEven !== null && (
          <line x1={x(breakEven)} x2={x(breakEven)} y1={y(schedule.value) - 6} y2={y(schedule.value) + 6} stroke="var(--ink)" strokeWidth={1.5} />
        )}

        <path d={path} fill="none" stroke="var(--ours)" strokeWidth={2} />
        <text x={x(0) - 4} y={y(curve[0].gbp) - 8} textAnchor="end">knowing the side, {gbp(curve[0].gbp)}</text>
        {REAL.map(({ model, label, policy, dx, dy }) => {
          const cx = x(r.forecasts.find((f) => f.model === model)!.brier.value);
          const money = r.money[policy];
          const cy = y(money.value);
          const tip = dy > 0 ? cy + dy - 12 : cy + dy + 4;   // the leader stops just short of the text
          return (
            <g key={model}>
              <line x1={cx} x2={cx} y1={y(money.lo)} y2={y(money.hi)} stroke="var(--ink-soft)" strokeWidth={1.5} />
              <line x1={cx} y1={cy} x2={cx + dx} y2={tip} stroke="var(--ink-faint)" />
              <circle cx={cx} cy={cy} r={4} fill="var(--recess)" stroke="var(--ink-soft)" strokeWidth={1.5} />
              <text x={cx + dx} y={cy + dy} textAnchor={dx < 0 ? 'end' : 'start'}>{label}</text>
            </g>
          );
        })}
        <circle cx={x(at.brier)} cy={y(at.gbp)} r={6.5} fill="var(--ink)" stroke="var(--panel)" strokeWidth={2} />
      </svg>
      <input id="skill" className="slider" type="range" min={0} max={1.5} step={0.01} value={1.5 - k}
        aria-label="Scale the forecast's errors" onChange={(e) => setK(1.5 - Number(e.target.value))} />
      <label htmlFor="skill" className="slider-label">Drag to make the forecast worse (left) or better (right)</label>
      <p className="slider-readout">
        <span className="big">{gbp(at.gbp)}</span>
        a day {real ? 'with our forecast' : 'with a hypothetical forecast'} at Brier {at.brier.toFixed(3)},{' '}
        {gbp(Math.abs(at.gbp - schedule.value))} {at.gbp >= schedule.value ? 'more' : 'less'} than no forecast at all.
      </p>
      <p className="note">
        Vertical bars are 90% intervals. A forecast pays for itself only below Brier {breakEven?.toFixed(3)}, the tick on
        the schedule's line; from there each 0.01 is worth £8 to £10 a day.
      </p>
    </div>
  );
}

function interpolate(curve: { k: number; brier: number; gbp: number }[], k: number) {
  const i = Math.max(1, curve.findIndex((p) => p.k >= k));
  const a = curve[i - 1];
  const b = curve[Math.min(i, curve.length - 1)];
  const t = b.k === a.k ? 0 : (k - a.k) / (b.k - a.k);
  return { brier: a.brier + t * (b.brier - a.brier), gbp: a.gbp + t * (b.gbp - a.gbp) };
}

/** The Brier score at which the curve crosses `level`, by linear interpolation; null if it never does. */
function crossing(curve: { brier: number; gbp: number }[], level: number): number | null {
  for (let i = 1; i < curve.length; i++) {
    const [a, b] = [curve[i - 1], curve[i]];
    if ((a.gbp - level) * (b.gbp - level) <= 0 && a.gbp !== b.gbp) return a.brier + ((level - a.gbp) / (b.gbp - a.gbp)) * (b.brier - a.brier);
  }
  return null;
}
