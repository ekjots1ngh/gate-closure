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

/** Our battery as a one-line diagram, its state, and the week's money against the schedule and the side oracle. */
export default function Battery({ r, d, now, period }: Props) {
  const row = period >= 0 ? r.tape[period] : null;
  const soc = row ? row.ours.soc : 0;
  const action = row ? row.ours.action : 0;
  const state = action > 0 ? 'discharging' : action < 0 ? 'charging' : 'holding';
  const settled = printedCount(d, now);
  return (
    <>
      <h2>Our battery, 1 MW / 2 MWh</h2>
      <div>
        <Schematic soc={soc} state={state} />
        <div className="state">
          <span className="readout">{soc.toFixed(1)} of 2 MWh</span>
          <span className="action">{state}{action !== 0 ? ' 1 MW' : ''}</span>
        </div>
        <div className="legs">
          {LEGS.flatMap((leg) => [
            <span key={`${leg}-label`} className={leg === 'ours' ? 'ours' : undefined}>{LABEL[leg]}</span>,
            <span key={`${leg}-value`} className={`figure readout${leg === 'ours' ? ' ours' : ''}`}>{gbp(d.cum[leg][settled])}</span>,
          ])}
        </div>
      </div>
      <PnlChart d={d} settled={settled} />
    </>
  );
}

/** Grid bus bar above, battery below, and the feeder between them carrying moving dashes when power flows. */
function Schematic({ soc, state }: { soc: number; state: 'charging' | 'discharging' | 'holding' }) {
  const width = 330;
  const height = 126;
  const cells = [0.5, 1, 1.5, 2];
  const body = { x: 196, y: 42, w: 52, h: 78 };
  const cellH = (body.h - 10) / cells.length;
  return (
    <svg width={width} height={height} role="img" aria-label={`${soc} of 2 megawatt hours stored, ${state}`}>
      <line x1={8} x2={width - 8} y1={22} y2={22} stroke="var(--ink-soft)" strokeWidth={3} />
      <text x={8} y={14}>the grid</text>
      <text x={width - 8} y={14} textAnchor="end" className="readout">{state === 'holding' ? 'no flow' : state === 'charging' ? 'grid to battery' : 'battery to grid'}</text>
      <line x1={body.x + body.w / 2} x2={body.x + body.w / 2} y1={22} y2={body.y} stroke="var(--rule)" strokeWidth={3} />
      <line className={`feeder ${state}`} x1={body.x + body.w / 2} x2={body.x + body.w / 2} y1={22} y2={body.y}
        stroke={state === 'holding' ? 'none' : state === 'charging' ? 'var(--long)' : 'var(--short)'} strokeWidth={3} />
      <rect x={body.x} y={body.y} width={body.w} height={body.h} rx={4} fill="var(--recess)" stroke="var(--ink-soft)" strokeWidth={1.5} />
      {cells.map((level, i) => (
        <rect key={level} className="cell" x={body.x + 5} y={body.y + 5 + (cells.length - 1 - i) * cellH} width={body.w - 10} height={cellH - 3} rx={2}
          fill={soc >= level ? 'var(--ink-soft)' : 'var(--lamp-off)'} />
      ))}
      <text x={body.x - 10} y={body.y + 14} textAnchor="end">the battery</text>
      <text x={body.x - 10} y={body.y + 32} textAnchor="end" style={{ fill: 'var(--ink-faint)' }}>charges when it expects long,</text>
      <text x={body.x - 10} y={body.y + 47} textAnchor="end" style={{ fill: 'var(--ink-faint)' }}>discharges when it expects short</text>
    </svg>
  );
}

const PNL_HEIGHT = 196;

function PnlChart({ d, settled }: { d: Derived; settled: number }) {
  const [ref, width] = useWidth<HTMLDivElement>(600);
  const height = PNL_HEIGHT;
  const m = { top: 14, right: 128, bottom: 26, left: 56 };
  const x = d3.scaleUtc().domain([d.t0, d.starts[d.n - 1]]).range([m.left, width - m.right]);
  const all = LEGS.flatMap((leg) => d.cum[leg]);
  const y = d3.scaleLinear().domain([Math.min(0, d3.min(all)!), d3.max(all)!]).nice().range([height - m.bottom, m.top]);
  const line = (leg: Leg3) =>
    d3.line<number>().x((_, i) => x(d.starts[Math.min(i, d.n - 1)])).y((v) => y(v))(d.cum[leg].slice(0, settled + 1)) ?? '';
  return (
    <div ref={ref}>
      <svg width={width} height={height} role="img" aria-label="Cumulative money for each battery this week">
        <text x={m.left} y={m.top - 4}>the week's money, from half hours whose price has printed{settled > 0 ? ` (up to ${hhmm(d.starts[settled - 1])})` : ''}</text>
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
