import * as d3 from 'd3';
import { useState } from 'react';
import { gbp, type Replay } from './data';
import { useWidth } from './useSize';

// The three real forecasts sit within 0.02 of Brier of each other, so each label is a callout:
// (dx, dy) is where its text starts, in pixels from the point.
const REAL = [
  { model: 'ours', label: 'ours', policy: 'chain/ours', dx: -14, dy: -16 },
  { model: 'persistence_cal', label: 'persistence', policy: 'chain/persistence_cal', dx: 16, dy: 30 },
  { model: 'indicated', label: "NESO's forecast", policy: 'chain/indicated', dx: -16, dy: 44 },
];

/** Drag the slider to make our forecast better or worse, and watch what it is worth. */
export default function Skill({ r }: { r: Replay }) {
  const curve = [...r.value_of_skill.chain].sort((a, b) => a.k - b.k);
  const [k, setK] = useState(1);
  const at = interpolate(curve, k);
  const [ref, width] = useWidth<HTMLDivElement>(600);
  const height = 300;
  const m = { top: 16, right: 20, bottom: 34, left: 56 };
  const x = d3.scaleLinear().domain([0.3, 0]).range([m.left, width - m.right]);
  const y = d3.scaleLinear().domain([-80, 240]).range([height - m.bottom, m.top]);
  const schedule = r.money['chain/schedule'].value;
  const path = d3.line<{ brier: number; gbp: number }>().x((p) => x(p.brier)).y((p) => y(p.gbp))(curve.filter((p) => p.brier <= 0.3)) ?? '';

  return (
    <div className="inset" ref={ref}>
      <h2>What forecasting skill is worth</h2>
      <svg width={width} height={height} role="img" aria-label="Money per day against forecast accuracy">
        {y.ticks(5).map((v) => (
          <g key={v}>
            <line x1={m.left} x2={width - m.right} y1={y(v)} y2={y(v)} stroke="var(--rule)" strokeWidth={v === 0 ? 1 : 0.6} />
            <text x={m.left - 6} y={y(v) + 4} textAnchor="end">{gbp(v)}</text>
          </g>
        ))}
        {x.ticks(6).map((v) => (
          <text key={v} x={x(v)} y={height - 14} textAnchor="middle">{v.toFixed(2)}</text>
        ))}
        <text x={width - m.right} y={height - 1} textAnchor="end">Brier score, better to the right</text>
        <line x1={m.left} x2={width - m.right} y1={y(schedule)} y2={y(schedule)} stroke="var(--schedule)" strokeDasharray="5 4" />
        <text x={width - m.right} y={y(schedule) + 16} textAnchor="end">no forecast: the fixed schedule, {gbp(schedule)} a day</text>
        <path d={path} fill="none" stroke="var(--ours)" strokeWidth={2} />
        {REAL.map(({ model, label, policy, dx, dy }) => {
          const cx = x(r.forecasts.find((f) => f.model === model)!.brier.value);
          const cy = y(r.money[policy].value);
          const tip = dy > 0 ? cy + dy - 12 : cy + dy + 4;   // the leader stops just short of the text
          return (
            <g key={model}>
              <line x1={cx} y1={cy} x2={cx + dx} y2={tip} stroke="var(--ink-faint)" />
              <circle cx={cx} cy={cy} r={4} fill="var(--recess)" stroke="var(--ink-soft)" strokeWidth={1.5} />
              <text x={cx + dx} y={cy + dy} textAnchor={dx < 0 ? 'end' : 'start'}>{label}</text>
            </g>
          );
        })}
        <circle cx={x(at.brier)} cy={y(at.gbp)} r={7} fill="var(--short)" />
      </svg>
      <label htmlFor="skill" className="note">Scale our forecast's errors: left is worse, right is better than we managed</label>
      <input id="skill" className="slider" type="range" min={0} max={1.5} step={0.01} value={1.5 - k}
        onChange={(e) => setK(1.5 - Number(e.target.value))} />
      <div className="figures">
        <div><span className="big">{at.brier.toFixed(3)}</span><span className="label">Brier score</span></div>
        <div><span className="big">{gbp(at.gbp)}</span><span className="label">a day, with the forecast carried forward</span></div>
        <div><span className="big">{gbp(at.gbp - schedule)}</span><span className="label">against the fixed schedule</span></div>
      </div>
      <p className="note">
        At k = 1 this is our real forecast. Money moves almost in a straight line, £8 to £10 a day per 0.01 of Brier,
        and a forecast at coin-flip accuracy that still trades loses to not forecasting at all.
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
