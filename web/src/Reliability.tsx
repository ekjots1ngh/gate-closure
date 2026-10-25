import * as d3 from 'd3';
import type { Replay } from './data';
import { useWidth } from './useSize';

const SQUARE = 250;   // px for the reliability square
const HIST = 44;     // px for the histogram of how often each probability was said

/**
 * The reliability diagram: where the forecast says p, how often the grid was short. On the
 * diagonal means calibrated. The bars underneath show how often it says each p: a forecast
 * that hugs 50% is safe but worth little.
 */
export default function Reliability({ r }: { r: Replay }) {
  const [ref, width] = useWidth<HTMLDivElement>(480);
  const m = { top: 22, right: 16, left: 52 };
  const size = Math.min(width - m.left - m.right - 170, SQUARE);
  const x = d3.scaleLinear().domain([0, 1]).range([m.left, m.left + size]);
  const y = d3.scaleLinear().domain([0, 1]).range([m.top + size, m.top]);
  const ours = r.forecasts.find((f) => f.model === 'ours')!;
  const persistence = r.forecasts.find((f) => f.model === 'persistence_cal')!;
  const bins = ours.decomposition.bins;
  const total = d3.sum(bins, (b) => b.count);
  const histTop = m.top + size + 36;
  const h = d3.scaleLinear().domain([0, d3.max(bins, (b) => b.count / total)!]).range([0, HIST]);
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  const line = d3.line<{ forecast: number; observed: number }>().x((b) => x(b.forecast)).y((b) => y(b.observed));
  const confident = bins.reduce((best, b) => (Math.abs(b.forecast - 0.75) < Math.abs(best.forecast - 0.75) ? b : best));
  const middle = d3.sum(bins.filter((b) => b.forecast > 0.3 && b.forecast < 0.7), (b) => b.count) / total;

  return (
    <div className="inset" ref={ref}>
      <h2>Calibrated, but rarely confident</h2>
      <svg width={width} height={histTop + HIST + 6} role="img" aria-label="Reliability diagram of our forecast">
        {[0, 0.25, 0.5, 0.75, 1].map((v) => (
          <g key={v}>
            <line x1={x(0)} x2={x(1)} y1={y(v)} y2={y(v)} stroke="var(--rule)" strokeWidth={0.6} opacity={0.6} />
            <text x={x(0) - 6} y={y(v) + 4} textAnchor="end">{pct(v)}</text>
            <text x={x(v)} y={m.top + size + 14} textAnchor="middle">{pct(v)}</text>
          </g>
        ))}
        <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} stroke="var(--ink-faint)" strokeDasharray="4 4" />
        <text x={x(0)} y={m.top - 10}>how often the grid was short</text>
        <text x={x(1)} y={m.top + size + 30} textAnchor="end">what the forecast said</text>

        <path d={line(persistence.decomposition.bins) ?? ''} fill="none" stroke="var(--schedule)" strokeDasharray="5 4" strokeWidth={1.5} />
        {persistence.decomposition.bins.map((b) => (
          <circle key={b.forecast} cx={x(b.forecast)} cy={y(b.observed)} r={3} fill="var(--panel)" stroke="var(--schedule)" strokeWidth={1.5} />
        ))}
        <path d={line(bins) ?? ''} fill="none" stroke="var(--ink)" strokeWidth={2} />
        {bins.map((b) => (
          <circle key={b.forecast} cx={x(b.forecast)} cy={y(b.observed)} r={3.5} fill="var(--ink)" />
        ))}
        <g transform={`translate(${x(1) + 22}, ${y(0.95)})`}>
          <line x1={0} x2={22} y1={0} y2={0} stroke="var(--ink)" strokeWidth={2} />
          <circle cx={11} cy={0} r={3.5} fill="var(--ink)" />
          <text x={30} y={4} style={{ fill: 'var(--ink)' }}>ours</text>
          <line x1={0} x2={22} y1={20} y2={20} stroke="var(--schedule)" strokeWidth={1.5} strokeDasharray="5 4" />
          <circle cx={11} cy={20} r={3} fill="var(--panel)" stroke="var(--schedule)" strokeWidth={1.5} />
          <text x={30} y={24}>calibrated persistence</text>
          <line x1={0} x2={22} y1={40} y2={40} stroke="var(--ink-faint)" strokeDasharray="4 4" />
          <text x={30} y={44}>perfectly calibrated</text>
        </g>

        {bins.map((b, i) => {
          const lo = i === 0 ? 0 : (bins[i - 1].forecast + b.forecast) / 2;
          const hi = i === bins.length - 1 ? 1 : (b.forecast + bins[i + 1].forecast) / 2;
          return (
            <rect key={b.forecast} x={x(lo) + 1} y={histTop + HIST - h(b.count / total)} width={Math.max(1, x(hi) - x(lo) - 2)}
              height={h(b.count / total)} fill="var(--ink-soft)" opacity={0.55} />
          );
        })}
        <line x1={x(0)} x2={x(1)} y1={histTop + HIST} y2={histTop + HIST} stroke="var(--rule)" />
        <text x={x(1) + 22} y={histTop + HIST - 4}>how often ours says each</text>
      </svg>
      <p className="note">
        Where it says {pct(confident.forecast)}, the grid was short {pct(confident.observed)} of the time: it means what it says. But {pct(middle)} of its calls sit
        between 30% and 70%, and a call that rarely strays from even money is worth little to a battery.
      </p>
    </div>
  );
}
