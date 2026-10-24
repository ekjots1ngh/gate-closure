import * as d3 from 'd3';
import { gbp, num, type Gain, type Replay } from './data';
import { useWidth } from './useSize';

type Kind = 'ceiling' | 'ours' | 'schedule' | 'baseline';

const ROWS: { label: string; policy: string; kind: Kind }[] = [
  { label: 'knowing every price in advance', policy: 'hindsight', kind: 'ceiling' },
  { label: 'knowing the side an hour early', policy: 'chain/side_oracle', kind: 'ceiling' },
  { label: 'ours', policy: 'chain/ours', kind: 'ours' },
  { label: 'fixed schedule, no forecast', policy: 'chain/schedule', kind: 'schedule' },
  { label: 'calibrated persistence', policy: 'chain/persistence_cal', kind: 'baseline' },
  { label: "NESO's forecast", policy: 'chain/indicated', kind: 'baseline' },
];
const FILL: Record<Kind, string> = {
  ceiling: 'none',
  ours: 'var(--ours)',
  schedule: 'var(--schedule)',
  baseline: 'var(--ink-faint)',
};
const ROW_H = 34;
const BAR_H = 14;
const M = { top: 4, right: 58, bottom: 24, left: 214 };

const interval = (g: Gain) => `${gbp(g.gbp.value, 1)} [${num(g.gbp.lo, 1)}, ${num(g.gbp.hi, 1)}]`;

/** Every policy's pounds a day on one axis, so the distance from ours to the ceilings is visible. */
export default function MoneyLadder({ r }: { r: Replay }) {
  const [ref, width] = useWidth<HTMLDivElement>(600);
  const height = M.top + ROWS.length * ROW_H + M.bottom;
  const x = d3.scaleLinear().domain([0, 380]).range([M.left, width - M.right]);
  const schedule = r.money['chain/schedule'].value;
  const bottom = M.top + ROWS.length * ROW_H;
  const [firstPrints, revised] = Object.values(r.by_era);   // export writes them in date order

  return (
    <div className="inset" ref={ref}>
      <h2>Where the money is</h2>
      <p>
        Pounds a day over four years, with 90% intervals from resampling whole weeks. The two ceilings, drawn open,
        show how much skill is left on the table.
      </p>
      <svg width={width} height={height} role="img" aria-label="Money per day for every policy, with the ceilings">
        {x.ticks(4).map((v) => (
          <g key={v}>
            <line x1={x(v)} x2={x(v)} y1={M.top} y2={bottom} stroke="var(--rule)" strokeWidth={0.6} />
            <text x={x(v)} y={height - 6} textAnchor="middle">{gbp(v)}</text>
          </g>
        ))}
        {ROWS.map(({ label, policy, kind }, i) => {
          const { value, lo, hi } = r.money[policy];
          const mid = M.top + i * ROW_H + ROW_H / 2;
          return (
            <g key={policy}>
              <text x={M.left - 10} y={mid + 4} textAnchor="end" style={kind === 'ours' ? { fill: 'var(--ink)' } : undefined}>
                {label}
              </text>
              <rect x={x(0)} y={mid - BAR_H / 2} width={x(value) - x(0)} height={BAR_H} fill={FILL[kind]}
                stroke={kind === 'ceiling' ? 'var(--ink-soft)' : 'none'} strokeDasharray="3 3" />
              <line x1={x(lo)} x2={x(hi)} y1={mid} y2={mid} stroke="var(--ink-soft)" />
              <line x1={x(lo)} x2={x(lo)} y1={mid - 4} y2={mid + 4} stroke="var(--ink-soft)" />
              <line x1={x(hi)} x2={x(hi)} y1={mid - 4} y2={mid + 4} stroke="var(--ink-soft)" />
              <text x={x(hi) + 6} y={mid + 4} className="figure">{gbp(value, 1)}</text>
            </g>
          );
        })}
        <line x1={x(schedule)} x2={x(schedule)} y1={M.top - 2} y2={bottom} stroke="var(--schedule)" strokeDasharray="4 3" />
      </svg>
      <p className="note">
        Ours beats the schedule by {interval(r.gain['chain/ours'])} a day, paired week by week. Leaving out the 1% of
        half hours with the most extreme prices: {interval(r.gain_without_spike_half_hours['chain/ours'])}. Leaving out the
        1% of days with the most at stake: {interval(r.gain_without_top_days['chain/ours'])}, so a good part of the edge
        comes from a handful of days.
      </p>
      <p className="note">
        Split where Elexon began serving revised prices: before February 2024, on clean first prints, ours made{' '}
        {gbp(firstPrints.chain_ours, 1)} a day against {gbp(firstPrints.schedule, 1)}; since then{' '}
        {gbp(revised.chain_ours, 1)} against {gbp(revised.schedule, 1)}.
      </p>
    </div>
  );
}
