import * as d3 from 'd3';
import { gbp, hhmm, LEGS, printedCount, type Derived, type Leg3, type Replay } from './data';
import { useWidth } from './useSize';

const LABEL: Record<Leg3, string> = { ours: 'ours', schedule: 'fixed schedule', side_oracle: 'knowing the side' };
const STYLE: Record<Leg3, { stroke: string; dash?: string; width: number }> = {
  ours: { stroke: 'var(--ours)', width: 2 },
  schedule: { stroke: 'var(--schedule)', dash: '5 4', width: 1.5 },
  side_oracle: { stroke: 'var(--ink-faint)', dash: '1 3', width: 1.5 },
};

interface Props {
  r: Replay;
  d: Derived;
  now: number;
  period: number;   // the half hour in progress, or -1
}

/** Our battery's state and the week's money so far, against the schedule and the side oracle. */
export default function Battery({ r, d, now, period }: Props) {
  const row = period >= 0 ? r.tape[period] : null;
  const soc = row ? row.ours.soc : 0;
  const action = row ? (row.ours.action > 0 ? 'discharging' : row.ours.action < 0 ? 'charging' : 'holding') : 'idle';
  const settled = printedCount(d, now);
  return (
    <>
      <div>
        <h2>Our battery</h2>
        <div className="cells" aria-label={`${soc} of 2 MWh stored`}>
          {[0.5, 1, 1.5, 2].map((level) => <div key={level} className={`cell${soc >= level ? ' on' : ''}`} />)}
        </div>
        <div className="state-line">
          <span>{soc.toFixed(1)} of 2 MWh</span>
          <span className="action">{action}</span>
        </div>
        <div className="ledger-figures">
          {LEGS.flatMap((leg) => [
            <span key={`${leg}-label`}>{LABEL[leg]}</span>,
            <span key={`${leg}-value`} className="figure">{gbp(d.cum[leg][settled])}</span>,
          ])}
        </div>
        <p className="note">Money from half hours whose price has printed{row ? `, up to ${hhmm(d.starts[Math.max(0, settled - 1)])}` : ''}.</p>
      </div>
      <PnlChart d={d} settled={settled} />
    </>
  );
}

function PnlChart({ d, settled }: { d: Derived; settled: number }) {
  const [ref, width] = useWidth<HTMLDivElement>(600);
  const height = 210;
  const m = { top: 14, right: 132, bottom: 30, left: 56 };
  const x = d3.scaleUtc().domain([d.t0, d.starts[d.n - 1]]).range([m.left, width - m.right]);
  const all = LEGS.flatMap((leg) => d.cum[leg]);
  const y = d3.scaleLinear().domain([Math.min(0, d3.min(all)!), d3.max(all)!]).nice().range([height - m.bottom, m.top]);
  const line = (leg: Leg3) =>
    d3.line<number>().x((_, i) => x(d.starts[Math.min(i, d.n - 1)])).y((v) => y(v))(d.cum[leg].slice(0, settled + 1)) ?? '';
  return (
    <div ref={ref}>
      <h2>The week's money</h2>
      <svg width={width} height={height} role="img" aria-label="Cumulative money for each battery this week">
        {y.ticks(4).map((v) => (
          <g key={v}>
            <line x1={m.left} x2={width - m.right} y1={y(v)} y2={y(v)} stroke="var(--rule)" strokeWidth={0.6} />
            <text x={m.left - 6} y={y(v) + 4} textAnchor="end">{gbp(v)}</text>
          </g>
        ))}
        {x.ticks(d3.utcDay.every(1)!).map((t) => (
          <text key={+t} x={x(t)} y={height - 4} textAnchor="middle">{d3.utcFormat('%a %-d')(t)}</text>
        ))}
        {LEGS.map((leg) => (
          <path key={leg} d={line(leg)} fill="none" stroke={STYLE[leg].stroke} strokeWidth={STYLE[leg].width} strokeDasharray={STYLE[leg].dash} />
        ))}
        {settled > 0 && endLabels(LEGS.map((leg) => ({ leg, y: y(d.cum[leg][settled]) })), height - m.bottom).map(({ leg, y: ly }) => (
          <text key={leg} x={x(d.starts[Math.min(settled, d.n - 1)]) + 6} y={ly + 4}>{LABEL[leg]}</text>
        ))}
      </svg>
    </div>
  );
}

/** Direct labels at the ends of the lines, nudged apart so they never overlap. */
function endLabels(labels: { leg: Leg3; y: number }[], floor: number, gap = 13) {
  const sorted = [...labels].sort((a, b) => a.y - b.y);
  for (let i = 1; i < sorted.length; i++) sorted[i].y = Math.max(sorted[i].y, sorted[i - 1].y + gap);
  const overflow = sorted[sorted.length - 1].y - (floor - 4);
  return overflow > 0 ? sorted.map((label) => ({ ...label, y: label.y - overflow })) : sorted;
}
