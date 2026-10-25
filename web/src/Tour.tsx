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

// Tuesday 23 June: at the 19:00 gate the model calls 20:00 short while NESO's forecast leans long;
// 20:00 prints £550, and our battery sells into it after the fixed schedule's has already emptied.
const TUESDAY_19 = 43 * HOUR + 2 * MINUTE;
const TUESDAY_21 = 45 * HOUR + 2 * MINUTE;   // the 21:00 gate, when 20:00 has just printed

export const STEPS: Step[] = [
  {
    title: 'Short or long',
    body: 'Every half hour, Britain’s grid ends up short of power (amber: prices high) or long (blue: prices low). This strip is what actually happened.',
    at: TUESDAY_19, region: 'gate', chart: 'outcome', card: 'left',
  },
  {
    title: 'What the model knows',
    body: 'At 19:00 it may only use what was public at 19:00: the newest printed price, and the wind, demand and NESO forecasts as published.',
    at: TUESDAY_19, region: 'map', chart: null, card: 'right',
  },
  {
    title: 'The call',
    body: 'Positions lock an hour ahead, so at 19:00 the model calls 20:00: short, 61% sure. NESO’s own forecast leans long. Our battery will sell.',
    at: TUESDAY_19, region: 'gate', chart: 'call', card: 'left',
  },
  {
    title: 'Locked',
    body: 'Past the gate nothing can change. 20:00 is an hour away, and its price is only published at about 20:52. The call has to hold that long.',
    at: TUESDAY_19, region: 'gate', chart: 'band', card: 'left',
  },
  {
    title: 'The price arrives',
    body: '20:00 printed £550: short, as called. The schedule’s battery was already empty; ours sold 1 MW into it for £231 the schedule could not make.',
    at: TUESDAY_21, region: 'gate-battery', chart: 'price', card: 'left',
  },
  {
    title: 'Could we have peeked?',
    body: 'Everything published after Thursday noon is replaced with noise and the whole pipeline rebuilt. Not one call before the line moves.',
    poison: true, region: 'gate', chart: null, card: 'left',
  },
  {
    title: 'Four years, and four sealed months',
    body: 'Over four years: Brier 0.229 against NESO’s 0.247, and £5.5 a day over a fixed schedule. On four sealed months since, the skill held; the money did not.',
    at: TUESDAY_19, region: 'gate', chart: null, card: 'left',
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
