import * as d3 from 'd3';
import { useState } from 'react';
import { gbp, num, type Replay } from './data';
import { useWidth } from './useSize';

const HEIGHT = 260;
const RULE = 60;   // today's gate closure, minutes before the half hour

/** The four-year study rerun at four decision times: what the battery gains over the fixed schedule at each. */
export default function HourCurve({ r }: { r: Replay }) {
  const leads = [...(r.value_of_time ?? [])].sort((a, b) => b.minutes - a.minutes);   // 120 first: time runs left to right
  const [chosen, setChosen] = useState(RULE);
  const [ref, width] = useWidth<HTMLDivElement>(600);
  if (leads.length === 0) return null;

  const m = { top: 24, right: 24, bottom: 34, left: 52 };
  const x = d3.scalePoint<number>().domain(leads.map((l) => l.minutes)).range([m.left + 30, width - m.right - 30]);
  const y = d3.scaleLinear().domain([-8, 22]).range([HEIGHT - m.bottom, m.top]);
  const at = leads.find((l) => l.minutes === chosen)!;
  const rule = leads.find((l) => l.minutes === RULE)!;
  const line = d3.line<(typeof leads)[number]>().x((l) => x(l.minutes)!).y((l) => y(l.gain.value))(leads) ?? '';

  return (
    <>
      <div className="inset" ref={ref}>
        <h2>The battery’s edge over a fixed schedule, by when the call is made</h2>
        <svg width={width} height={HEIGHT} role="img" aria-label="Gain over the schedule against minutes before the half hour">
          {y.ticks(5).map((v) => (
            <g key={v}>
              <line x1={m.left} x2={width - m.right} y1={y(v)} y2={y(v)} stroke="var(--rule)" strokeWidth={v === 0 ? 1.2 : 0.6} opacity={v === 0 ? 1 : 0.6} />
              <text x={m.left - 6} y={y(v) + 4} textAnchor="end">{v > 0 ? '+' : ''}{gbp(v)}</text>
            </g>
          ))}
          <text x={width - m.right} y={y(0) - 6} textAnchor="end">fixed schedule</text>
          <line x1={x(RULE)!} x2={x(RULE)!} y1={m.top - 10} y2={HEIGHT - m.bottom} stroke="var(--ink-faint)" strokeDasharray="3 4" />
          <text x={x(RULE)! + 6} y={m.top - 2}>today’s gate closure</text>
          <path d={line} fill="none" stroke="var(--ink)" strokeWidth={2} />
          {leads.map((l) => (
            <g key={l.minutes} onClick={() => setChosen(l.minutes)} style={{ cursor: 'pointer' }}>
              <line x1={x(l.minutes)!} x2={x(l.minutes)!} y1={y(l.gain.lo)} y2={y(l.gain.hi)} stroke="var(--ink-soft)" strokeWidth={1.5} />
              <circle cx={x(l.minutes)!} cy={y(l.gain.value)} r={l.minutes === chosen ? 7 : 4.5}
                fill={l.minutes === chosen ? 'var(--ink)' : 'var(--recess)'} stroke="var(--ink)" strokeWidth={1.5} />
              <rect x={x(l.minutes)! - 30} y={m.top} width={60} height={HEIGHT - m.top - m.bottom} fill="transparent" />
              <text x={x(l.minutes)!} y={HEIGHT - 12} textAnchor="middle" style={l.minutes === chosen ? { fill: 'var(--ink)', fontWeight: 700 } : undefined}>
                {l.minutes} min before
              </text>
            </g>
          ))}
        </svg>
        <p className="note">Pounds a day over four years, 90% intervals from whole weeks. Click a point.</p>
      </div>
      <div className="inset">
        <h2>Decide at</h2>
        <div className="segmented" role="radiogroup" aria-label="Minutes before the half hour">
          {leads.map((l) => (
            <button key={l.minutes} role="radio" aria-checked={l.minutes === chosen} onClick={() => setChosen(l.minutes)}>
              {l.minutes} min
            </button>
          ))}
        </div>
        <div className="figures">
          <div><span className="big">{at.brier.ours.toFixed(3)}</span><span className="label">Brier score</span></div>
          <div><span className="big">{gbp(at.ours_gbp, 1)}</span><span className="label">a day</span></div>
          <div><span className="big">{at.gain.value >= 0 ? '+' : '−'}{gbp(Math.abs(at.gain.value), 1)}</span><span className="label">over the schedule, [{num(at.gain.lo, 1)}, {num(at.gain.hi, 1)}]</span></div>
        </div>
        <p className="hour-say">
          {chosen === RULE
            ? 'Today’s rule: positions lock an hour before each half hour.'
            : chosen < RULE
              ? `Deciding ${RULE - chosen} minutes later sharpens the call from ${rule.brier.ours.toFixed(3)} to ${at.brier.ours.toFixed(3)} and is worth ${gbp(at.ours_gbp - rule.ours_gbp, 1)} a day more.`
              : `Deciding ${chosen - RULE} minutes earlier blunts the call to ${at.brier.ours.toFixed(3)}; the edge over the schedule is gone.`}
        </p>
        <p className="note">
          Every timing rule in the code is one constant, so the whole four-year test reruns at each decision time, with the
          poison test passing at every one. In NESO’s 2026 call for input on balancing reform, many respondents asked for a
          shorter gate closure; NESO judged under an hour not yet feasible. This prices that question. An analysis added
          after the results, and labelled as one.
        </p>
      </div>
    </>
  );
}
