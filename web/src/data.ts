export interface Leg { action: number; soc: number; pnl: number }
export interface Row {
  t: string; price: number; short: number;
  p_ours: number; p_persistence: number; p_neso: number;
  wind_revision_mw: number; demand_revision_mw: number;
  ours: Leg; tilt: Leg; oracle: Leg;
}
export interface Interval { lo: number; hi: number }
export interface SkillPoint { k: number; brier: number; gbp_per_day: number }

/** Mirrors gclose/export.py. Policy names are <family>_<forecast>: one_ours, chain_tilt, price_ridge, ... */
export interface Replay {
  meta: {
    generated_at: string; test_period: string; replay_week: string; replay_rule: string;
    battery: string; decision_time: string;
    tape_policies: Record<'ours' | 'tilt' | 'oracle', string>;   // which policy each tape leg shows
  };
  tape: Row[];
  brier: ({ model: string; brier: number } & Interval)[];
  money: ({ policy: string; gbp_per_day: number; active_share: number } & Interval)[];
  gap_share: Record<string, { share: number; without_top_1pct_days: number } & Interval>;
  skill_curve: { one: SkillPoint[]; chain: SkillPoint[] };
  poison: { cutoff: string; decisions_checked: number; features_changed: number; forecasts_changed: number; rows_after_cutoff_poisoned: number };
  by_year: ({ year: number } & Record<string, number>)[];
}

/** Derived, precomputed series so the animation loop only does lookups. */
export interface Derived {
  t0: number;               // ms epoch of period 0
  n: number;
  cum: { ours: number[]; tilt: number[]; oracle: number[] }; // cum[k] = sum of pnl over periods < k
  sse: { ours: number[]; neso: number[]; persistence: number[] }; // cumulative squared error, same indexing
  cutoffIndex: number;
}

export const PERIOD_MS = 30 * 60 * 1000;

export function derive(r: Replay): Derived {
  const n = r.tape.length;
  const t0 = Date.parse(r.tape[0].t.replace('Z', ':00Z'));
  const mk = () => new Array(n + 1).fill(0) as number[];
  const cum = { ours: mk(), tilt: mk(), oracle: mk() };
  const sse = { ours: mk(), neso: mk(), persistence: mk() };
  r.tape.forEach((d, i) => {
    cum.ours[i + 1] = cum.ours[i] + d.ours.pnl;
    cum.tilt[i + 1] = cum.tilt[i] + d.tilt.pnl;
    cum.oracle[i + 1] = cum.oracle[i] + d.oracle.pnl;
    sse.ours[i + 1] = sse.ours[i] + (d.p_ours - d.short) ** 2;
    sse.neso[i + 1] = sse.neso[i] + (d.p_neso - d.short) ** 2;
    sse.persistence[i + 1] = sse.persistence[i] + (d.p_persistence - d.short) ** 2;
  });
  const cutoffMs = parseTime(r.poison.cutoff);
  const cutoffIndex = Math.round((cutoffMs - t0) / PERIOD_MS);
  return { t0, n, cum, sse, cutoffIndex };
}

/** replay.json uses "2026-06-25T12:00Z" (no seconds); make it parseable everywhere. */
export function parseTime(s: string): number {
  const m = s.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})Z$/);
  return Date.parse(m ? `${m[1]}T${m[2]}:00Z` : s);
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
export const NAMES: Record<string, string> = {
  tilt: 'No forecast',
  ours: 'Ours',
  hgb: 'Boosted classifier',
  persistence: 'Persistence, calibrated',
  indicated: 'NESO indicated',
  oracle: 'Perfect knowledge of the side',
  coin: 'Coin flip',
  persistence_cal: 'Persistence, calibrated',
  price_oracle: 'Perfect knowledge of the price',
  price_last_seen: 'Last price seen',
  price_ridge: 'Price forecast, ridge',
  price_hgb: 'Price forecast, boosted',
};
