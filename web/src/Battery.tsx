import * as d3 from 'd3';
import { gbp, hhmm, printedCount, type Derived, type Replay } from './data';
import { useWidth } from './useSize';

type Shown = 'ours' | 'schedule';
const SHOWN: Shown[] = ['ours', 'schedule'];
const LABEL: Record<Shown, string> = { ours: 'ours', schedule: 'fixed schedule' };
const STYLE: Record<Shown, { stroke: string; dash?: string; width: number }> = {
  ours: { stroke: 'var(--ours)', width: 2 },
  schedule: { stroke: 'var(--schedule)', dash: '5 4', width: 1.5 },
};
const CHART_HEIGHT = 150;

interface Props {
  r: Replay;
  d: Derived;
  now: number;
  period: number;   // the half hour in progress, or -1
}

/** Our battery: what it is doing now, and the week's money against the fixed schedule. */
export default function Battery({ r, d, now, period }: Props) {
  const row = period >= 0 ? r.tape[period] : null;
  const soc = row ? row.ours.soc : 0;
  const action = row ? row.ours.action : 0;
  const state = action > 0 ? 'discharging' : action < 0 ? 'charging' : 'holding';
  const settled = printedCount(d, now);
  const ours = r.money['chain/ours'].value;
  const schedule = r.money['chain/schedule'].value;
  return (
    <>
      <h2>Our battery, 1 MW / 2 MWh</h2>
      <div>
        <div className="state">
          <Glyph soc={soc} state={state} />
          <div>
            <div className="action">{state}</div>
            <div className="soc readout">{soc.toFixed(1)} of 2 MWh{action > 0 ? ', sending 1 MW' : action < 0 ? ', taking 1 MW' : ''}</div>
          </div>
        </div>
        <div className="scoreboard">
          <span className="caption">this week</span>
          {SHOWN.flatMap((leg) => [
            <span key={`${leg}-label`} className={leg === 'ours' ? 'ours' : undefined}>{LABEL[leg]}</span>,
            <span key={`${leg}-value`} className={`figure${leg === 'ours' ? ' ours' : ''}`}>{gbp(d.cum[leg][settled])}</span>,
          ])}
        </div>
        <p className="note">
          The week was picked for its range of prices, not its money, and the schedule won it. Over four years the
          forecast earns {gbp(ours, 1)} a day to {gbp(schedule, 1)}.
        </p>
      </div>
      <PnlChart r={r} d={d} settled={settled} />
    </>
  );
}

/** A small one-line diagram: the grid's bus bar, the feeder carrying moving dashes when power flows, the cells. */
function Glyph({ soc, state }: { soc: number; state: 'charging' | 'discharging' | 'holding' }) {
  const cells = [0.5, 1, 1.5, 2];
  return (
    <svg width={64} height={58} role="img" aria-label={`${soc} of 2 megawatt hours stored, ${state}`}>
      <line x1={2} x2={62} y1={4} y2={4} stroke="var(--ink-soft)" strokeWidth={3} />
      <line x1={32} x2={32} y1={4} y2={16} stroke="var(--rule)" strokeWidth={3} />
      <line className={`feeder ${state}`} x1={32} x2={32} y1={4} y2={16}
        stroke={state === 'holding' ? 'none' : state === 'charging' ? 'var(--long)' : 'var(--short)'} strokeWidth={3} />
      <rect x={18} y={16} width={28} height={40} rx={3} fill="var(--recess)" stroke="var(--ink-soft)" strokeWidth={1.5} />
      {cells.map((level, i) => (
        <rect key={level} className="cell" x={22} y={20 + (cells.length - 1 - i) * 8.5} width={20} height={6.5} rx={1}
          fill={soc >= level ? 'var(--ink-soft)' : 'var(--lamp-off)'} />
      ))}
    </svg>
  );
}

function PnlChart({ r, d, settled }: { r: Replay; d: Derived; settled: number }) {
  const [ref, width] = useWidth<HTMLDivElement>(600);
  const height = CHART_HEIGHT;
  const m = { top: 18, right: 150, bottom: 22, left: 52 };
  const x = d3.scaleUtc().domain([d.t0, d.starts[d.n - 1]]).range([m.left, width - m.right]);
  const all = SHOWN.flatMap((leg) => d.cum[leg]);
  const y = d3.scaleLinear().domain([Math.min(0, d3.min(all)!), d3.max(all)!]).nice().range([height - m.bottom, m.top]);
  const line = (leg: Shown) =>
    d3.line<number>().x((_, i) => x(d.starts[Math.min(i, d.n - 1)])).y((v) => y(v))(d.cum[leg].slice(0, settled + 1)) ?? '';

  // The week's dearest half hour, labelled once it has printed: it is where most of the week's money is made.
  const spike = d3.maxIndex(r.tape, (row) => row.price);
  const spikeShown = settled > spike;
  const end = x(d.starts[Math.min(settled, d.n - 1)]);

  return (
    <div ref={ref}>
      <svg width={width} height={height} role="img" aria-label="Cumulative money this week, ours against the fixed schedule">
        <text x={m.left} y={10}>the week's money, counted as each price prints{settled > 0 ? `, to ${hhmm(d.starts[settled - 1])}` : ''}</text>
        {y.ticks(3).map((v) => (
          <g key={v}>
            <line x1={m.left} x2={width - m.right} y1={y(v)} y2={y(v)} stroke="var(--rule)" strokeWidth={0.6} />
            <text x={m.left - 6} y={y(v) + 4} textAnchor="end">{gbp(v)}</text>
          </g>
        ))}
        {x.ticks(d3.utcDay.every(1)!).map((t) => (
          <text key={+t} x={x(t)} y={height - 4} textAnchor="middle">{d3.utcFormat('%a')(t)}</text>
        ))}
        {spikeShown && (
          <g>
            <line x1={x(d.starts[spike])} x2={x(d.starts[spike])} y1={m.top + 2} y2={height - m.bottom} stroke="var(--short)" strokeDasharray="2 3" />
            <text x={x(d.starts[spike]) - 5} y={m.top + 10} textAnchor="end" style={{ fill: 'var(--short)' }}>
              {gbp(r.tape[spike].price)} at {hhmm(d.starts[spike])} {d3.utcFormat('%a')(new Date(d.starts[spike]))}
            </text>
          </g>
        )}
        {SHOWN.map((leg) => (
          <path key={leg} d={line(leg)} fill="none" stroke={STYLE[leg].stroke} strokeWidth={STYLE[leg].width} strokeDasharray={STYLE[leg].dash} />
        ))}
        {settled > 0 && endLabels(SHOWN.map((leg) => ({ leg, y: y(d.cum[leg][settled]) })), height - m.bottom).map(({ leg, y: ly }) => (
          <text key={leg} x={end + 6} y={ly + 4} style={leg === 'ours' ? { fill: 'var(--ink)', fontWeight: 700 } : undefined}>
            {LABEL[leg]} {gbp(d.cum[leg][settled])}
          </text>
        ))}
      </svg>
    </div>
  );
}

/** Direct labels at the ends of the lines, nudged apart so they never overlap. */
function endLabels(labels: { leg: Shown; y: number }[], floor: number, gap = 14) {
  const sorted = [...labels].sort((a, b) => a.y - b.y);
  for (let i = 1; i < sorted.length; i++) sorted[i].y = Math.max(sorted[i].y, sorted[i - 1].y + gap);
  const overflow = sorted[sorted.length - 1].y - (floor - 4);
  return overflow > 0 ? sorted.map((label) => ({ ...label, y: label.y - overflow })) : sorted;
}
