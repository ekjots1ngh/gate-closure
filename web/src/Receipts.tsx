import { useEffect, useState } from 'react';
import { hhmm, type Replay } from './data';

const LEDGER = 'https://raw.githubusercontent.com/ekjots1ngh/gate-closure/main/ledger/decisions.jsonl';
const REFRESH_MS = 60_000;
// Mirrors gclose/live.py: lines from the code before PROTOCOL amendment 8 carry its bug's signature,
// a side for the newest period although its volume had not printed. They stay in the ledger and are not scored.
const preFix = (row: Decision) => row.inputs.short_newest !== null && row.inputs.niv_newest === null;

interface Decision {
  target_start: string;
  gate: string;
  decided_at: string;
  p_short: number;
  action: number;
  soc_after: number;
  model_sha256: string;
  inputs: Record<string, number | null>;
}

/** The poison check on this very week, and the live record as it is pushed to GitHub. */
export default function Receipts({ r, onPoison }: { r: Replay; onPoison: () => void }) {
  const p = r.poison;
  return (
    <>
      <div className="inset poison-card">
        <h2>Poison the future</h2>
        <p>
          Every Elexon row published after {hhmm(Date.parse(p.cutoff))} on Thursday was replaced with noise, and the
          whole pipeline was rebuilt. For the {p.decisions_checked} half hours decided before the cutoff:
        </p>
        <div className="figures">
          <div><span className="check">{p.features_changed}</span><span className="label">inputs changed</span></div>
          <div><span className="check">{p.forecasts_changed}</span><span className="label">forecasts changed</span></div>
          <div><span className="check">{p.decisions_changed}</span><span className="label">decisions changed</span></div>
          <div><span className="check">{p.later_rows_poisoned}</span><span className="label">later rows that did change</span></div>
        </div>
        <p className="note">
          Computed on the real data by <code>python -m gclose.export</code>. The test suite runs the same check with a
          cutoff before every publication, and plants five leaks to prove it catches them.
        </p>
        <div className="controls inline"><button onClick={onPoison}>Show it on the replay (P)</button></div>
      </div>
      <LiveLedger />
    </>
  );
}

/** The ledger as pushed to GitHub, refreshed every minute; null until the first fetch, failed if GitHub is unreachable. */
export function useLedger(): { rows: Decision[] | null; failed: boolean } {
  const [rows, setRows] = useState<Decision[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch(`${LEDGER}?t=${Date.now()}`)
        .then((res) => (res.ok ? res.text() : Promise.reject(res.status)))
        .then((text) => alive && (setRows(text.trim().split('\n').map((line) => JSON.parse(line))), setFailed(false)))
        .catch(() => alive && setFailed(true));
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { alive = false; clearInterval(timer); };
  }, []);
  return { rows, failed };
}

/** A lamp in the masthead: the real ledger is alive, and this is its latest line. */
export function LiveBadge() {
  const { rows } = useLedger();
  if (!rows) return null;
  const clean = rows.filter((row) => !preFix(row));
  const last = clean[clean.length - 1] ?? rows[rows.length - 1];
  return (
    <a className="live-badge" href="https://github.com/ekjots1ngh/gate-closure/blob/main/ledger/decisions.jsonl" target="_blank" rel="noreferrer">
      <span className="live-lamp" />
      live: {clean.length} decisions pushed to GitHub, latest for {last.target_start.slice(11, 16)} UTC
    </a>
  );
}

function LiveLedger() {
  const { rows, failed } = useLedger();

  return (
    <div className="inset">
      <h2>The live record</h2>
      <p>
        Since the freeze, every half hour, a forecast and a trade are written down and pushed to GitHub before the
        half hour's gate. The prices come later.
      </p>
      {failed && <p className="note">GitHub is out of reach from here; the record is in ledger/decisions.jsonl in the repository.</p>}
      {rows && (
        <table className="ledger-table">
          <thead><tr><th>half hour (UTC)</th><th>decided</th><th>before the gate</th><th>P(short)</th><th>action</th></tr></thead>
          <tbody>
            {rows.slice(-9).reverse().map((row) => {
              const lead = (Date.parse(row.gate) - Date.parse(row.decided_at)) / 60_000;
              return (
                <tr key={row.target_start} className={preFix(row) ? 'pre-fix' : undefined}>
                  <td>{row.target_start.slice(5, 16).replace('T', ' ')}</td>
                  <td>{row.decided_at.slice(11, 16)}</td>
                  <td>{lead.toFixed(0)} min</td>
                  <td>{row.p_short.toFixed(2)}</td>
                  <td>{row.action > 0 ? 'discharge' : row.action < 0 ? 'charge' : 'hold'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {rows && <p className="note">Model {rows[rows.length - 1].model_sha256.slice(0, 12)}, {rows.length} decisions so far.</p>}
      {rows?.some(preFix) && (
        <p className="note">
          Struck through: decided by the first process, still running the code from before the fix in amendment 8, and
          recognisable by that bug’s signature in its inputs. The ledger is never edited, so the lines stay, and the score leaves them out.
        </p>
      )}
    </div>
  );
}
