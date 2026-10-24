import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import replay from '../public/replay.json';
import Battery from './Battery';
import { dayLabel, dayShort, derive, gbp, GATE_MS, hhmm, PERIOD_MS, periodAt, type Derived, type Replay } from './data';
import GateChart from './GateChart';
import MapPanel from './MapPanel';
import MoneyLadder from './MoneyLadder';
import Receipts, { LiveBadge } from './Receipts';
import Skill from './Skill';

const R = replay as unknown as Replay;
const SPEEDS = [1, 4, 16];                     // half hours of replay per second
const START_OFFSET = 10 * 3_600_000;           // open on Monday 10:00, so the chart has history

/** The week as a strip under the masthead: where the replay is, and a click to go anywhere. */
function WeekStrip({ d, now, end, seek }: { d: Derived; now: number; end: number; seek: (t: number) => void }) {
  const days = Array.from({ length: 7 }, (_, k) => d.t0 + k * 48 * PERIOD_MS);
  const span = end - d.t0;
  const at = (t: number) => `${(100 * (t - d.t0)) / span}%`;
  return (
    <div className="week" role="slider" aria-label="Position in the week" aria-valuemin={0} aria-valuemax={100}
      aria-valuenow={Math.round((100 * (now - d.t0)) / span)} tabIndex={0}
      onClick={(e) => { const box = e.currentTarget.getBoundingClientRect(); seek(d.t0 + Math.min(1, Math.max(0, (e.clientX - box.left) / box.width)) * span); }}>
      {days.map((t) => <span key={t} className="day-mark" style={{ left: at(t) }}>{dayShort(t)}</span>)}
      <span className="week-elapsed" style={{ width: at(now) }} />
      <span className="week-now" style={{ left: at(now) }} />
    </div>
  );
}

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
  const decided = R.tape[(gate + GATE_MS - d.t0) / PERIOD_MS] ?? null;
  const ours = R.money['chain/ours'].value;
  const schedule = R.money['chain/schedule'].value;

  return (
    <>
      <div className="show">
        <header className="masthead">
          <h1>Gate Closure<span>a week of the GB grid, replayed</span></h1>
          <div className="clock" aria-live="off">
            <span className="time readout">{hhmm(now)}</span>
            <span className="day">{dayLabel(now)} 2026, UTC</span>
            <LiveBadge />
          </div>
          <div className="controls">
            <button onClick={() => { setPoison(false); setPlaying((p) => !p); }} aria-pressed={playing}>{playing ? 'Pause' : 'Play'}</button>
            {SPEEDS.map((s) => (
              <button key={s} onClick={() => setSpeed(s)} aria-pressed={speed === s} aria-label={`${s} half hours a second`}>{s}×</button>
            ))}
            <button className="poison" onClick={togglePoison} aria-pressed={poison}>Poison the future</button>
          </div>
        </header>
        <WeekStrip d={d} now={now} end={end} seek={(t) => { setPoison(false); setPlaying(false); setNow(t); }} />

        <main className="deck">
          <section className="region map">
            <h2>What the model saw at the gate</h2>
            <MapPanel decided={decided} pulseKey={gate} />
          </section>
          <section className="region gate">
            <h2>The gate: an hour before each half hour, a forecast and a trade; the price arrives 52 minutes after it starts</h2>
            <GateChart r={R} d={d} now={now} poison={poison} noiseSeed={noiseSeed} />
            <p className="note">
              {poison
                ? 'Everything published after the cutoff is noise. Every lamp to the left of it is unchanged: rebuilt from the poisoned data, 0 of 170 decisions moved.'
                : 'Amber: the grid is short of power and prices run high. Blue: long. Space plays and pauses, arrows step a half hour, 1 2 3 set the speed, P poisons the future.'}
            </p>
          </section>
          <section className="region battery">
            <Battery r={R} d={d} now={now} period={periodAt(d, now)} />
          </section>
        </main>
      </div>

      <div className="record">
        <p className="caption">
          {R.meta.replay_rule} The fixed schedule won this week. Over four years of walk-forward testing the forecast earns{' '}
          {gbp(ours, 1)} a day against {gbp(schedule, 1)} for the schedule; the record below is that test.
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
    </>
  );
}
