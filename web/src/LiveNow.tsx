import { useEffect, useState } from 'react';
import { gbp, side, sure, tone, verb } from './data';
import { type Live } from './live';
import { explain } from './why';

const HALF_HOUR = 30 * 60_000;
const GATE_LEAD = 60 * 60_000;
const RUN_LEAD = 6 * 60_000;          // the laptop decides six minutes before each gate
const SHOWN = 16;                     // live calls on the strip

const utc = (ms: number) => new Date(ms).toISOString().slice(11, 16);
const mmss = (ms: number) => {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

/**
 * The system doing it now: a countdown to the next gate, the latest live call, and the recent calls
 * against what Elexon then printed, from the ledger and outcomes the laptop pushes to GitHub.
 */
export default function LiveNow({ live }: { live: Live }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const counted = live.clean.filter(live.inTime);
  const latest = counted[counted.length - 1];
  const nextGate = Math.floor(now / HALF_HOUR) * HALF_HOUR + HALF_HOUR;          // the next gate to close
  const nextTarget = nextGate + GATE_LEAD;
  const nextRun = nextGate - RUN_LEAD;
  const awaiting = latest && Date.parse(latest.gate) > now;                         // the latest call's gate is still ahead
  const recent = counted.slice(-SHOWN);
  const settled = recent.filter((row) => live.outcomes.has(row.target_start));
  const right = settled.filter((row) => (row.p_short >= 0.5) === live.outcomes.get(row.target_start)!.short).length;
  const money = settled.reduce((sum, row) => sum + live.outcomes.get(row.target_start)!.pnl, 0);
  const why = latest ? explain(latest) : [];
  const widest = Math.max(10, ...why.map((push) => Math.abs(push.points)));

  return (
    <section className="live-now" aria-label="Live">
      <div className="live-head">
        <h2><span className="live-lamp" /> Live from a laptop, since Saturday 16:52 UTC</h2>
        <p className="live-clock readout">
          {now < nextRun
            ? <>next call in <b>{mmss(nextRun - now)}</b>, for {utc(nextTarget)} UTC</>
            : <>the {utc(nextGate)} gate closes in <b>{mmss(nextGate - now)}</b></>}
        </p>
      </div>

      {!live.rows && <p className="note">{live.failed ? 'GitHub is out of reach from here; the record is in ledger/decisions.jsonl.' : 'Reading the ledger from GitHub…'}</p>}

      {latest && (
        <div className="live-call">
          <div className="live-big">
            <span className="live-when">{utc(Date.parse(latest.target_start))} UTC{awaiting ? ', gate at ' + utc(Date.parse(latest.gate)) : ''}</span>
            <span className="live-side" style={{ color: tone(side(latest.p_short)) }}>{side(latest.p_short)} {sure(latest.p_short)}%</span>
            <span className="live-act">{verb(latest.action)}{awaiting ? '' : ''}</span>
          </div>
          <p className="live-meta">
            called at {latest.decided_at.slice(11, 16)}, committed {live.committedAt(latest)?.slice(11, 16) ?? 'to GitHub'}, {Math.round((Date.parse(latest.gate) - Date.parse(live.committedAt(latest) ?? latest.decided_at)) / 60_000)} min before its gate.
            {live.outcomes.has(latest.target_start)
              ? ` It printed ${gbp(live.outcomes.get(latest.target_start)!.price)}: the grid was ${live.outcomes.get(latest.target_start)!.short ? 'short' : 'long'}.`
              : awaiting ? ' Nobody knows the answer yet.' : ` Its price prints at about ${utc(Date.parse(latest.target_start) + 52 * 60_000)}.`}
          </p>
          {why.length > 0 && (
            <div className="live-why" title="Each input's push, in percentage points: the call as made, against the same call with that input at its average. Exact for this model, a logistic regression on 16 inputs.">
              <p className="live-why-head">What moved this call</p>
              {why.map((push) => {
                const towards = push.points >= 0 ? 'short' : 'long';
                return (
                  <div key={push.feature} className="live-why-row">
                    <span className="live-why-track"><span style={{ width: `${(100 * Math.abs(push.points)) / widest}%`, background: tone(towards) }} /></span>
                    <span className="live-why-label">{push.label}</span>
                    <span className="live-why-pts" style={{ color: tone(towards) }}>{Math.abs(push.points) < 1 ? 'under 1 pt' : `${Math.round(Math.abs(push.points))} pts`} towards {towards}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {recent.length > 0 && (
        <div className="live-strip">
          <div className="live-rows" style={{ gridTemplateColumns: `auto repeat(${recent.length}, minmax(0, 1fr))` }}>
            <span className="live-label">called</span>
            {recent.map((row) => (
              <span key={row.target_start} className="live-cell" title={`${utc(Date.parse(row.target_start))} UTC: called ${side(row.p_short)} ${sure(row.p_short)}%`}>
                <span className="live-bar" style={{ background: tone(side(row.p_short)), height: `${6 + 28 * Math.min(0.4, Math.abs(row.p_short - 0.5)) / 0.4}px` }} />
              </span>
            ))}
            <span className="live-label">happened</span>
            {recent.map((row) => {
              const o = live.outcomes.get(row.target_start);
              return (
                <span key={row.target_start} className="live-cell" title={o ? `${utc(Date.parse(row.target_start))} UTC printed ${gbp(o.price)}: ${o.short ? 'short' : 'long'}` : 'not printed yet'}>
                  <span className="live-dot" style={{ background: o ? tone(o.short ? 'short' : 'long') : 'var(--lamp-off)' }} />
                </span>
              );
            })}
            <span className="live-label">UTC</span>
            {recent.map((row) => <span key={row.target_start} className="live-cell live-time">{utc(Date.parse(row.target_start))}</span>)}
          </div>
          <p className="live-score">
            {settled.length > 0
              ? <>{right} of {settled.length} sides right so far; the battery is at {gbp(money)}. A day of calls proves the process, not the skill.</>
              : <>No live half hour has printed yet.</>}
          </p>
        </div>
      )}
    </section>
  );
}
