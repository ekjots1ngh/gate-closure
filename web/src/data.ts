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

export const PERIOD_MS = 30 * 60_000;
export const GATE_MS = 60 * 60_000;     // the decision for a period is made an hour before it starts
export const PRINT_MS = 52 * 60_000;    // its price prints about 52 minutes after it starts

export type Leg3 = 'ours' | 'schedule' | 'side_oracle';
export const LEGS: Leg3[] = ['ours', 'schedule', 'side_oracle'];

/** Precomputed series, so the animation loop only does lookups. */
export interface Derived {
  t0: number;                            // ms epoch of the first period's start
  n: number;
  starts: number[];                      // ms epoch of each period's start
  cum: Record<Leg3, number[]>;           // cum[leg][k] = P&L of periods 0..k-1
  cutoff: number;                        // the poison check's cutoff, ms epoch
}

export function derive(r: Replay): Derived {
  const n = r.tape.length;
  const starts = r.tape.map((d) => Date.parse(d.t));
  const cum = Object.fromEntries(LEGS.map((leg) => {
    const out = new Array(n + 1).fill(0) as number[];
    r.tape.forEach((d, i) => { out[i + 1] = out[i] + d[leg].pnl; });
    return [leg, out];
  })) as Record<Leg3, number[]>;
  return { t0: starts[0], n, starts, cum, cutoff: Date.parse(r.poison.cutoff) };
}

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));

/** How many periods have printed their price by `now`. */
export const printedCount = (d: Derived, now: number) => clamp(Math.floor((now - d.t0 - PRINT_MS) / PERIOD_MS) + 1, 0, d.n);

/** How many periods have been decided by `now` (their gate has passed). */
export const decidedCount = (d: Derived, now: number) => clamp(Math.floor((now - d.t0 + GATE_MS) / PERIOD_MS) + 1, 0, d.n);

/** The period in progress at `now`, or -1 outside the replay. */
export const periodAt = (d: Derived, now: number) => {
  const i = Math.floor((now - d.t0) / PERIOD_MS);
  return i >= 0 && i < d.n ? i : -1;
};

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
