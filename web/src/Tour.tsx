import { useEffect } from 'react';

const HOUR = 3_600_000;
const MINUTE = 60_000;

/** What a step lights up: one region of the board, and within the gate chart one element. */
export type Region = 'gate' | 'map' | 'gate-battery';
export type ChartFocus = 'outcome' | 'call' | 'band' | 'price' | null;

export interface Step {
  title: string;
  body: string;
  at?: number;              // replay time, ms after the week starts; unset keeps the clock where it is
  poison?: boolean;
  region: Region;
  chart: ChartFocus;
  card: 'left' | 'right';   // which side the card sits, clear of what the step lights up
}

// Tuesday 23 June: at the 18:00 gate the model calls 19:00 short; 19:00 prints £789 and the battery sells into it.
const TUESDAY_18 = 42 * HOUR + 2 * MINUTE;
const TUESDAY_20 = 44 * HOUR + 2 * MINUTE;   // the 20:00 gate, when 19:00 has just printed

export const STEPS: Step[] = [
  {
    title: 'Short or long',
    body: 'Every half hour, Britain’s grid ends up short of power (amber: prices high) or long (blue: prices low). This strip is what actually happened.',
    at: TUESDAY_18, region: 'gate', chart: 'outcome', card: 'left',
  },
  {
    title: 'What the model knows',
    body: 'At 18:00 it may only use what was public at 18:00: the newest printed price, and the wind, demand and NESO forecasts as published.',
    at: TUESDAY_18, region: 'map', chart: null, card: 'right',
  },
  {
    title: 'The call',
    body: 'The rules lock every position an hour ahead. So at 18:00 the model calls 19:00: short, 61% sure. The battery will sell.',
    at: TUESDAY_18, region: 'gate', chart: 'call', card: 'left',
  },
  {
    title: 'The hour between deciding and knowing',
    body: 'Nobody learns 19:00’s price until about 52 minutes into it. The call has to survive this shaded hour.',
    at: TUESDAY_18, region: 'gate', chart: 'band', card: 'left',
  },
  {
    title: 'The price arrives',
    body: '19:00 printed £789: the grid was short, as called. The battery sold 1 MW into it and made £333 in half an hour.',
    at: TUESDAY_20, region: 'gate-battery', chart: 'price', card: 'left',
  },
  {
    title: 'Could we have peeked?',
    body: 'Everything published after Thursday noon is replaced with noise and the whole pipeline rebuilt. Not one call before the line moves.',
    poison: true, region: 'gate', chart: null, card: 'left',
  },
  {
    title: 'Four years of this',
    body: 'Over four years the forecast beats NESO’s own and is worth £5.4 a day to this battery; decided 30 minutes later, £15. The evidence is below.',
    at: TUESDAY_18, region: 'gate', chart: null, card: 'left',
  },
];

interface Props {
  step: number | null;      // null: the offer to start; a number: that step
  onStep: (step: number) => void;
  onClose: () => void;      // leave the tour where it stands
  onFinish: () => void;     // leave it from the last step, and play the week
}

/** The card that walks a newcomer through the board, one element at a time. */
export default function Tour({ step, onStep, onClose, onFinish }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'Enter' || (step !== null && e.key === 'ArrowRight')) {
        e.preventDefault();
        e.stopImmediatePropagation();
        if (step === null) onStep(0);
        else if (step + 1 < STEPS.length) onStep(step + 1);
        else onFinish();
      } else if (step !== null && e.key === 'ArrowLeft') {
        e.preventDefault();
        e.stopImmediatePropagation();
        if (step > 0) onStep(step - 1);
      }
    };
    window.addEventListener('keydown', onKey, { capture: true });
    return () => window.removeEventListener('keydown', onKey, { capture: true });
  }, [step, onStep, onClose, onFinish]);

  if (step === null) {
    return (
      <aside className="tour-card left" aria-label="Tour">
        <p className="tour-title">New here?</p>
        <p className="tour-body">A one-minute walk through one decision: what the model knew, the call, the wait, and the price.</p>
        <div className="tour-actions">
          <button className="primary" onClick={() => onStep(0)}>Show me how it works</button>
          <button onClick={onClose}>Explore on my own</button>
        </div>
      </aside>
    );
  }

  const s = STEPS[step];
  const last = step === STEPS.length - 1;
  return (
    <aside className={`tour-card ${s.card}`} aria-live="polite" aria-label={`Tour, step ${step + 1} of ${STEPS.length}`}>
      <p className="tour-count">{step + 1} of {STEPS.length}</p>
      <p className="tour-title">{s.title}</p>
      <p className="tour-body">{s.body}</p>
      <div className="tour-actions">
        {step > 0 && <button onClick={() => onStep(step - 1)}>Back</button>}
        <button className="primary" onClick={() => (last ? onFinish() : onStep(step + 1))}>{last ? 'Play the week' : 'Next'}</button>
        {!last && <button className="quiet" onClick={onClose}>Skip</button>}
      </div>
    </aside>
  );
}
