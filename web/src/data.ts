export interface Leg { action: number; soc: number; pnl: number }
export interface Row {
  t: string; price: number; short: number;
  p_ours: number; p_persistence_cal: number; p_indicated: number;
  wind_revision_mw: number | null; demand_revision_mw: number | null;
  ours: Leg; schedule: Leg; side_oracle: Leg;
}
export interface Estimate { value: number; lo: number; hi: number }
export interface Gain { gbp: Estimate; share: Estimate }
export interface SkillPoint { k: number; brier: number; gbp: number }

/** Mirrors gclose/export.py. Policies are named family/forecaster: one/ours, chain/schedule, price/ridge, hindsight. */
export interface Replay {
  meta: {
    generated_at: string; test_period: string; replay_week: string; replay_rule: string; battery: string;
    tape_policies: Record<'ours' | 'schedule' | 'side_oracle', string>;   // which policy each tape leg shows
  };
  tape: Row[];
  poison: { cutoff: string; decisions_checked: number; features_changed: number; forecasts_changed: number;
            decisions_changed: number; later_rows_poisoned: number };
  forecasts: {
    model: string; brier: Estimate; log_loss: number; log_loss_bits: number; ours_minus: Estimate;
    decomposition: { reliability: number; resolution: number; uncertainty: number; residual: number;
                     bins: { forecast: number; observed: number; count: number }[] };
    diebold_mariano: { statistic: number; p_value: number } | null;
  }[];
  risk: Record<string, { sharpe: number; max_drawdown: number }>;
  markov_check: { lags: number[]; observed: number[]; geometric: number[];
                  chain_ours_gbp: { geometric: number; measured: number } };
  money: Record<string, Estimate & { active_share: number }>;
  gain: Record<string, Gain>;
  gain_without_spike_half_hours: Record<string, Gain>;
  gain_without_top_days: Record<string, Gain>;
  by_era: Record<string, { ours_minus_persistence_cal: Estimate; schedule: number; chain_ours: number; gain: Gain }>;
  by_year: ({ year: number } & Record<string, number>)[];
  value_of_skill: { one: SkillPoint[]; chain: SkillPoint[] };
}

/** Derived, precomputed series so the animation loop only does lookups. */
export interface Derived {
  t0: number;               // ms epoch of period 0
  n: number;
  cum: { ours: number[]; schedule: number[]; side_oracle: number[] }; // cum[k] = sum of pnl over periods < k
  sse: { ours: number[]; indicated: number[]; persistence_cal: number[] }; // cumulative squared error, same indexing
  cutoffIndex: number;
}

export const PERIOD_MS = 30 * 60 * 1000;

export function derive(r: Replay): Derived {
  const n = r.tape.length;
  const t0 = Date.parse(r.tape[0].t);
  const mk = () => new Array(n + 1).fill(0) as number[];
  const cum = { ours: mk(), schedule: mk(), side_oracle: mk() };
  const sse = { ours: mk(), indicated: mk(), persistence_cal: mk() };
  r.tape.forEach((d, i) => {
    cum.ours[i + 1] = cum.ours[i] + d.ours.pnl;
    cum.schedule[i + 1] = cum.schedule[i] + d.schedule.pnl;
    cum.side_oracle[i + 1] = cum.side_oracle[i] + d.side_oracle.pnl;
    sse.ours[i + 1] = sse.ours[i] + (d.p_ours - d.short) ** 2;
    sse.indicated[i + 1] = sse.indicated[i] + (d.p_indicated - d.short) ** 2;
    sse.persistence_cal[i + 1] = sse.persistence_cal[i] + (d.p_persistence_cal - d.short) ** 2;
  });
  const cutoffMs = Date.parse(r.poison.cutoff);
  const cutoffIndex = Math.round((cutoffMs - t0) / PERIOD_MS);
  return { t0, n, cum, sse, cutoffIndex };
}

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const pad = (x: number) => String(x).padStart(2, '0');

export const hhmm = (ms: number) => { const d = new Date(ms); return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`; };
export const dayLabel = (ms: number) => { const d = new Date(ms); return `${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`; };
export const dayShort = (ms: number) => { const d = new Date(ms); return `${DAYS[d.getUTCDay()]} ${d.getUTCDate()}`; };

export const gbp = (x: number, dp = 0) => {
  const s = Math.abs(x).toLocaleString('en-GB', { minimumFractionDigits: dp, maximumFractionDigits: dp });
  return `${x < 0 ? '−' : ''}£${s}`;
};
export const num = (x: number, dp: number) => {
  const s = Math.abs(x).toFixed(dp);
  return `${x < 0 ? '−' : ''}${s}`;
};
export const pct = (x: number, dp = 1) => `${num(x * 100, dp)}%`;

/** Display names for forecast sources; the family (one step or chain) is shown separately. */
/** Display names for forecasters; the family (one step or chain) is shown separately. */
export const NAMES: Record<string, string> = {
  schedule: 'No forecast, fixed schedule',
  ours: 'Ours',
  boosted: 'Boosted classifier',
  persistence_cal: 'Persistence, calibrated',
  persistence_raw: 'Persistence, raw',
  indicated: 'NESO indicated imbalance',
  side_oracle: 'Knowing the side an hour early',
  coin: 'Coin flip',
  'price/ridge': 'Price forecast, ridge',
  'price/boosted': 'Price forecast, boosted',
  'price/last_seen': 'Last price seen',
  'price/oracle': 'Knowing the price an hour early',
  hindsight: 'Perfect hindsight, every price known',
};
