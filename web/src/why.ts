import model from '../../ledger/model.json';
import { gbp, hhmm, PERIOD_MS } from './data';
import type { Decision } from './live';

/**
 * What moved a live call. The frozen model is a logistic regression, so its log-odds split exactly into one
 * term per input: weight times the input's distance from its training mean, in standard deviations (a missing
 * input takes the training median, as gclose/live.py does). Each input's push is shown in percentage points:
 * the call as made, against the same call with that one input at its average.
 */
export interface Push { feature: string; label: string; points: number }

const sigmoid = (z: number) => 1 / (1 + Math.exp(-z));
const pad = (x: number) => String(Math.round(x)).padStart(2, '0');
const gw = (mw: number) => `${(mw / 1000).toFixed(1)} GW`;
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];   // pandas: Monday is 0

const NAMES: Record<string, string> = {
  short_newest: 'the newest side', short_prev1: 'the side before that', short_prev2: 'the side two before',
  niv_newest: 'the newest imbalance volume', niv_prev1: 'the imbalance volume before that',
  price_newest: 'the newest price', price_day_mean: "the past day's average price", price_day_std: "the past day's price swings",
  short_run_length: 'the run on one side', wind_latest: 'the wind forecast', wind_revision: 'the wind revision',
  demand_latest: 'the demand forecast', demand_revision: 'the demand revision', indicated_latest: "NESO's forecast",
  hour: 'the time of day', weekday: 'the day of the week',
};

function describe(feature: string, x: number, target: number): string {
  // The newest price visible at the gate is for the half hour two hours before the one being called.
  const at = (back: number) => hhmm(target - back * PERIOD_MS);
  const side = x >= 0.5 ? 'short' : 'long';
  const revised = (what: string) => (x === 0 ? `${what} forecast unrevised` : `${what} forecast revised ${x > 0 ? 'up' : 'down'} ${Math.round(Math.abs(x))} MW`);
  switch (feature) {
    case 'short_newest': return `${at(4)} was ${side}`;
    case 'short_prev1': return `${at(5)} was ${side}`;
    case 'short_prev2': return `${at(6)} was ${side}`;
    case 'niv_newest': return `grid ${x >= 0 ? 'short' : 'long'} by ${Math.round(Math.abs(x))} MWh at ${at(4)}`;
    case 'niv_prev1': return `grid ${x >= 0 ? 'short' : 'long'} by ${Math.round(Math.abs(x))} MWh at ${at(5)}`;
    case 'price_newest': return `${at(4)} price ${gbp(x)}`;
    case 'price_day_mean': return `past day's prices averaged ${gbp(x)}`;
    case 'price_day_std': return `past day's prices swung by about ${gbp(x)}`;
    case 'short_run_length': return `${Math.round(x)} half hours on one side in a row`;
    case 'wind_latest': return `wind forecast ${gw(x)}`;
    case 'wind_revision': return revised('wind');
    case 'demand_latest': return `demand forecast ${gw(x)}`;
    case 'demand_revision': return revised('demand');
    case 'indicated_latest': return `NESO forecasts a ${gw(Math.abs(x))} ${x >= 0 ? 'surplus' : 'shortfall'}`;
    case 'hour': return `time of day, ${pad(x)}:00`;
    case 'weekday': return `a ${WEEKDAYS[Math.round(x)] ?? 'weekday'}`;
    default: return feature;
  }
}

/** The inputs that moved this call most, largest first; empty if the call came from another model. */
export function explain(row: Decision, top = 3): Push[] {
  if (row.model_sha256 !== model.sha256) return [];
  const target = Date.parse(row.target_start);
  const parts = model.features.map((feature, i) => {
    const raw = row.inputs[feature];
    const x = raw === null || raw === undefined || Number.isNaN(raw) ? model.medians[i] : raw;
    return { feature, raw, term: (model.coef[i] * (x - model.mean[i])) / model.scale[i] };
  });
  const logit = model.intercept + parts.reduce((sum, part) => sum + part.term, 0);
  const p = sigmoid(logit);
  return parts
    .map(({ feature, raw, term }) => ({
      feature,
      label: raw === null || raw === undefined ? `${NAMES[feature] ?? feature} not out yet` : describe(feature, raw, target),
      points: 100 * (p - sigmoid(logit - term)),
    }))
    .sort((a, b) => Math.abs(b.points) - Math.abs(a.points))
    .slice(0, top);
}
