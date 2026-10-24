import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import replay from '../public/replay.json';
import Battery from './Battery';
import {
  dayLabel, dayShort, derive, gbp, GATE_MS, hhmm, num, PERIOD_MS, periodAt, printedCount, side, sure, tally, tone, verb,
  type Derived, type Replay,
} from './data';
import GateChart from './GateChart';
import MapPanel from './MapPanel';
import MoneyLadder from './MoneyLadder';
import Receipts from './Receipts';
import Reliability from './Reliability';
import Skill from './Skill';

const R = replay as unknown as Replay;
const SPEEDS = [0.5, 2, 8];                    // half hours of replay per second: slow enough to read by default
// Open on Tuesday 18:00, paused: one press of play and the battery discharges into the week's dearest evening.
const START_OFFSET = 42 * 3_600_000;
const CLOCK_STEP_MS = 10 * 60_000;            // the clock shows ten-minute steps, so it can be read while it runs
const REPO = 'https://github.com/ekjots1ngh/gate-closure';

const brier = (model: string) => R.forecasts.find((f) => f.model === model)!.brier;

export default function App() {
  const d = useMemo(() => derive(R), []);
  const end = d.starts[d.n - 1] + 3 * PERIOD_MS;
  const [now, setNow] = useState(d.t0 + START_OFFSET);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(SPEEDS[0]);
  const [poison, setPoison] = useState(false);
  const [noiseSeed, setNoiseSeed] = useState(1);
  const last = useRef<number | null>(null);

  // The replay clock.
  useEffect(() => {
    if (!playing) { last.current = null; return; }
    let frame = 0;
    const tick = (t: number) => {
      const dt = last.current === null ? 0 : (t - last.current) / 1000;
      last.current = t;
      setNow((prev) => {
        const next = Math.min(end, prev + dt * speed * PERIOD_MS);
        if (next >= end) setPlaying(false);
        return next;
      });
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, speed, end]);

  // Poisoned data flickers: a fresh draw of noise a few times a second.
  useEffect(() => {
    if (!poison) return;
    const timer = setInterval(() => setNoiseSeed((s) => s + 1), 140);
    return () => clearInterval(timer);
  }, [poison]);

  const togglePoison = useCallback(() => {
    setPoison((on) => {
      if (!on) { setPlaying(false); setNow(d.cutoff); }
      return !on;
    });
  }, [d.cutoff]);
  const nextSpeed = () => setSpeed((s) => SPEEDS[(SPEEDS.indexOf(s) + 1) % SPEEDS.length]);
  const seek = (t: number) => { setPoison(false); setPlaying(false); setNow(t); };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.key === ' ') { e.preventDefault(); setPoison(false); setPlaying((p) => !p); }
      else if (e.key === 'ArrowRight') { setPlaying(false); setNow((n) => Math.min(end, n + PERIOD_MS)); }
      else if (e.key === 'ArrowLeft') { setPlaying(false); setNow((n) => Math.max(d.t0, n - PERIOD_MS)); }
      else if (e.key === 'p' || e.key === 'P') togglePoison();
      else if (['1', '2', '3'].includes(e.key)) setSpeed(SPEEDS[Number(e.key) - 1]);
      else if (e.key === 'Home') { setPoison(false); setNow(d.t0 + START_OFFSET); setPlaying(true); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [end, d.t0, togglePoison]);

  const gate = Math.floor(now / PERIOD_MS) * PERIOD_MS;
  const target = gate + GATE_MS;
  const printed = printedCount(d, now);
  const newestKnown = printedCount(d, gate) - 1;
  const ours = R.money['chain/ours'].value;
  const schedule = R.money['chain/schedule'].value;
  const gain = R.gain['chain/ours'].gbp;

  return (
    <>
      <div className="show">
        <header className="masthead">
          <div>
            <h1>Gate Closure</h1>
            <p className="what">
              Every half hour the GB grid is short of power or long. An hour before, using only what was public, we call
              which; a battery trades on the call; the price arrives later.
            </p>
          </div>
          <div className="clock" aria-live="off">
            <div className="time readout">{hhmm(Math.floor(now / CLOCK_STEP_MS) * CLOCK_STEP_MS)}</div>
            <div className="day">{dayLabel(now)} 2026, UTC</div>
          </div>
          <div>
            <div className="controls">
              <button className={playing ? undefined : 'play'} onClick={() => { setPoison(false); setPlaying((p) => !p); }} aria-pressed={playing} title="Space">{playing ? 'Pause' : 'Play the week'}</button>
              <button className="speed" onClick={nextSpeed} title="Half hours a second; keys 1, 2, 3">{speed}×</button>
              <button className="poison" onClick={togglePoison} aria-pressed={poison} title="P">Poison the future</button>
            </div>
            <p className="four-years">
              Four years out of sample: Brier <b>{brier('ours').value.toFixed(3)}</b> against {brier('persistence_cal').value.toFixed(3)} for
              persistence and {brier('indicated').value.toFixed(3)} for NESO; <b>{gbp(ours, 1)}</b> a day against {gbp(schedule, 1)} with no forecast.
            </p>
          </div>
        </header>
        <WeekStrip d={d} now={now} end={end} printed={printed} seek={seek} />

        <main className="deck">
          <section className="region map">
            <MapPanel r={R} d={d} now={now} />
          </section>
          <section className="region gate">
            <Headline gate={gate} target={target} newestKnown={newestKnown} d={d} poison={poison} />
            <GateChart r={R} d={d} now={now} poison={poison} noiseSeed={noiseSeed} />
            <Legend printed={printed} poison={poison} />
          </section>
          <section className="region battery">
            <Battery r={R} d={d} now={now} period={periodAt(d, now)} />
          </section>
        </main>
      </div>

      <div className="record">
        <div className="section">
          <h2>Four years, out of sample</h2>
          <div className="figures headline-figures">
            <div><span className="big">{brier('ours').value.toFixed(3)}</span><span className="label">Brier score, against {brier('persistence_cal').value.toFixed(3)} for persistence and {brier('indicated').value.toFixed(3)} for NESO</span></div>
            <div><span className="big">{gbp(ours, 1)}</span><span className="label">a day with the forecast, against {gbp(schedule, 1)} with none</span></div>
            <div><span className="big">+{gbp(gain.value, 1)}</span><span className="label">a day, paired by week; 90% interval £{num(gain.lo, 1)} to £{num(gain.hi, 1)}</span></div>
          </div>
          <p className="lede">
            July 2022 to June 2026, 70,120 half hours, refitted every month on what was public at the time.
            The forecast is clearly better than both baselines, and calibrated, but rarely confident: that is why it is worth
            only about £5 a day.
          </p>
          <Reliability r={R} />
          <Skill r={R} />
          <div className="span"><MoneyLadder r={R} /></div>
        </div>

        <div className="section">
          <h2>Receipts</h2>
          <Receipts r={R} onPoison={() => { togglePoison(); window.scrollTo({ top: 0, behavior: 'smooth' }); }} />
        </div>
        <p className="colophon">
          Pre-registered in <a href={`${REPO}/blob/main/PROTOCOL.md`} target="_blank" rel="noreferrer">PROTOCOL.md</a> before the first
          result; every change since is a dated amendment. Code, data and every number: <a href={REPO} target="_blank" rel="noreferrer">github.com/ekjots1ngh/gate-closure</a>.
          Elexon BMRS data © Elexon Limited. Keys: space plays and pauses, arrows step a half hour, 1 2 3 set the speed, P poisons the future.
        </p>
      </div>
    </>
  );
}

/** One line that narrates the latest gate: the call just made, and how the newest printed price turned out. */
function Headline({ gate, target, newestKnown, d, poison }: { gate: number; target: number; newestKnown: number; d: Derived; poison: boolean }) {
  if (poison) return <p className="headline">The future is poisoned: everything published after the line is noise. <span className="soft">Every call before it is unchanged.</span></p>;
  const call = R.tape[(target - d.t0) / PERIOD_MS];
  const known = newestKnown >= 0 ? R.tape[newestKnown] : null;
  if (!call) return <p className="headline">The end of the week.</p>;
  const hit = known && (known.p_ours >= 0.5) === (known.short === 1);
  return (
    <p className="headline">
      {hhmm(gate)} gate: we call {hhmm(target)} <span style={{ color: tone(side(call.p_ours)) }}>{side(call.p_ours)}, {sure(call.p_ours)}%</span>, and {verb(call.ours.action)}.{' '}
      {known && (
        <span className="soft">
          Newest price: {hhmm(d.starts[newestKnown])} printed {gbp(known.price)}, the grid was {known.short ? 'short' : 'long'}; we had called it {hit ? 'right' : 'wrong'}.
        </span>
      )}
    </p>
  );
}

/** The legend for the call and the outcome, and the week's running score. */
function Legend({ printed, poison }: { printed: number; poison: boolean }) {
  const score = tally(R, printed);
  return (
    <p className="legend-line">
      <span className="swatch" style={{ background: 'var(--short)' }} /> short, prices high
      <span className="swatch" style={{ background: 'var(--long)' }} /> long, prices low
      <span className="sep">Bar height: how sure the call was.</span>
      {!poison && score.n > 0 && (
        <span className="score">
          This week so far: {score.right} of {score.n} sides right; Brier {score.ours.toFixed(3)} against {score.persistence.toFixed(3)} for persistence.
        </span>
      )}
    </p>
  );
}

/** The week as a strip under the masthead: each printed half hour in its outcome's colour, and a click to go anywhere. */
function WeekStrip({ d, now, end, printed, seek }: { d: Derived; now: number; end: number; printed: number; seek: (t: number) => void }) {
  const days = Array.from({ length: 7 }, (_, k) => d.t0 + k * 48 * PERIOD_MS);
  const span = end - d.t0;
  const at = (t: number) => `${(100 * (t - d.t0)) / span}%`;
  const slots = span / PERIOD_MS;
  return (
    <div className="week" role="slider" aria-label="Position in the week" aria-valuemin={0} aria-valuemax={100}
      aria-valuenow={Math.round((100 * (now - d.t0)) / span)} tabIndex={0}
      onClick={(e) => { const box = e.currentTarget.getBoundingClientRect(); seek(d.t0 + Math.min(1, Math.max(0, (e.clientX - box.left) / box.width)) * span); }}>
      {days.map((t) => <span key={t} className="day-mark" style={{ left: at(t) }}>{dayShort(t)}</span>)}
      <svg viewBox={`0 0 ${slots} 1`} preserveAspectRatio="none" aria-hidden="true">
        <rect x={0} y={0} width={slots} height={1} fill="var(--lamp-off)" />
        {R.tape.slice(0, printed).map((row, i) => (
          <rect key={i} x={i} y={0} width={1} height={1} fill={row.short ? 'var(--short)' : 'var(--long)'} />
        ))}
      </svg>
      <span className="week-now" style={{ left: at(now) }} />
    </div>
  );
}
