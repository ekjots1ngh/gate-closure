import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import replay from '../public/replay.json';
import Battery from './Battery';
import { dayLabel, derive, gbp, GATE_MS, hhmm, PERIOD_MS, periodAt, type Replay } from './data';
import GateChart from './GateChart';
import MapPanel from './MapPanel';
import MoneyLadder from './MoneyLadder';
import Receipts from './Receipts';
import Skill from './Skill';

const R = replay as unknown as Replay;
const SPEEDS = [1, 4, 16];                     // half hours of replay per second
const START_OFFSET = 10 * 3_600_000;           // open on Monday 10:00, so the chart has history

export default function App() {
  const d = useMemo(() => derive(R), []);
  const end = d.starts[d.n - 1] + 3 * PERIOD_MS;
  const [now, setNow] = useState(d.t0 + START_OFFSET);
  const [playing, setPlaying] = useState(true);
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
  const decided = R.tape[(gate + GATE_MS - d.t0) / PERIOD_MS];
  const ours = R.money['chain/ours'].value;
  const schedule = R.money['chain/schedule'].value;

  return (
    <div className="board">
      <header className="masthead">
        <div>
          <h1>Gate Closure</h1>
          <p>
            A week of the GB grid, replayed. An hour before each half hour, a forecast says whether the grid will be short
            of power or long, and a battery trades on it. Then the price arrives.
          </p>
        </div>
        <div className="clock" aria-live="off">
          <div className="time">{hhmm(now)}</div>
          <div className="day">{dayLabel(now)} 2026, UTC</div>
        </div>
        <div className="controls">
          <button onClick={() => { setPoison(false); setPlaying((p) => !p); }} aria-pressed={playing}>{playing ? 'Pause' : 'Play'}</button>
          {SPEEDS.map((s) => (
            <button key={s} onClick={() => setSpeed(s)} aria-pressed={speed === s} aria-label={`${s} half hours a second`}>{s}×</button>
          ))}
          <button className="poison" onClick={togglePoison} aria-pressed={poison}>Poison the future</button>
        </div>
      </header>

      <main className="deck">
        <section className="inset gate">
          <h2>The gate</h2>
          <GateChart r={R} d={d} now={now} poison={poison} noiseSeed={noiseSeed} />
          <p className="note">
            {poison
              ? 'Everything published after the cutoff is noise. Every lamp to the left of it is unchanged: rebuilt from the poisoned data, 0 of 170 decisions moved.'
              : 'Amber means the grid is short of power and prices run high; blue means long. The lower lamps fill in as each price prints, about 52 minutes after its half hour starts.'}
          </p>
        </section>
        <section className="inset map">
          <h2>Wind, at the gate</h2>
          <MapPanel revisionMw={decided?.wind_revision_mw ?? null} pulseKey={gate} />
        </section>
        <section className="inset battery">
          <Battery r={R} d={d} now={now} period={periodAt(d, now)} />
        </section>
      </main>

      <p className="note" style={{ marginTop: 12 }}>
        {R.meta.replay_rule} The fixed schedule won this week. Over four years of walk-forward testing the forecast earns{' '}
        {gbp(ours, 1)} a day against {gbp(schedule, 1)} for the schedule. Keys: space plays and pauses, arrows step a half
        hour, 1 2 3 set the speed, P poisons the future.
      </p>

      <div className="section">
        <h2>Four years, in two numbers</h2>
        <p className="lede">
          The forecast is clearly better than persistence and than NESO's own: Brier 0.229 against 0.241 and 0.247, a
          difference the Diebold-Mariano test puts at 17 standard errors. It is almost perfectly calibrated, but rarely
          confident, and that is why it is worth only about £5 a day more than no forecast at all.
        </p>
        <Skill r={R} />
        <MoneyLadder r={R} />
      </div>

      <div className="section">
        <h2>Receipts</h2>
        <Receipts r={R} onPoison={() => { togglePoison(); window.scrollTo({ top: 0, behavior: 'smooth' }); }} />
      </div>
    </div>
  );
}
