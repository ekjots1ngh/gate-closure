import { useEffect, useState } from 'react';
import { hhmm, side, sure, verb, type Replay } from './data';

const REPO = 'https://github.com/ekjots1ngh/gate-closure';
const LEDGER = 'https://raw.githubusercontent.com/ekjots1ngh/gate-closure/main/ledger/decisions.jsonl';
const COMMITS = 'https://api.github.com/repos/ekjots1ngh/gate-closure/commits?path=ledger/decisions.jsonl&per_page=100';
const LEDGER_REFRESH_MS = 60_000;
const COMMITS_REFRESH_MS = 5 * 60_000;   // GitHub allows 60 unauthenticated API calls an hour
const SHOWN_ROWS = 8;

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
interface Commit { url: string; at: string }

// Mirrors gclose/live.py: lines from the code before PROTOCOL amendment 8 carry its bug's signature,
// a side for the newest period although its volume had not printed. They stay in the ledger and are not scored.
const preFix = (row: Decision) => row.inputs.short_newest !== null && row.inputs.niv_newest === null;

/** Fetch `url` now and every `ms`, keeping the last good result; null until the first answer. */
function usePolled<T>(url: string, ms: number, parse: (body: string) => T): { data: T | null; failed: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch(url.includes('raw.githubusercontent') ? `${url}?t=${Date.now()}` : url)
        .then((res) => (res.ok ? res.text() : Promise.reject(res.status)))
        .then((body) => { if (alive) { setData(parse(body)); setFailed(false); } })
        .catch(() => { if (alive) setFailed(true); });
    load();
    const timer = setInterval(load, ms);
    return () => { alive = false; clearInterval(timer); };
  }, [url, ms]);   // eslint-disable-line react-hooks/exhaustive-deps
  return { data, failed };
}

const parseLedger = (body: string): Decision[] => body.trim().split('\n').filter(Boolean).map((line) => JSON.parse(line));

/** Each ledger commit's GitHub page and commit time, keyed by "target|decided_at" from its message. */
const parseCommits = (body: string): Map<string, Commit> => {
  const commits = new Map<string, Commit>();
  for (const c of JSON.parse(body) as { html_url: string; commit: { message: string; committer: { date: string } } }[]) {
    const match = /^ledger: (\S+) decided at (\S+)/.exec(c.commit.message);
    if (match) commits.set(`${match[1]}|${match[2]}`, { url: c.html_url, at: c.commit.committer.date });
  }
  return commits;
};

/** The three receipts: the poison check on this very week, the sealed holdout, and the live record. */
export default function Receipts({ r, onPoison }: { r: Replay; onPoison: () => void }) {
  const p = r.poison;
  return (
    <>
      <div className="receipt-stack">
        <div className="inset receipt">
          <h2>Poison the future</h2>
          <p className="proves">Proves that no input came from after the gate.</p>
          <p>
            Every row published after {hhmm(Date.parse(p.cutoff))} on Thursday was replaced with noise and the whole
            pipeline rebuilt. Of the {p.decisions_checked} half hours decided before the cutoff:
          </p>
          <div className="figures">
            <div><span className="check">{p.features_changed}</span><span className="label">inputs changed</span></div>
            <div><span className="check">{p.forecasts_changed}</span><span className="label">forecasts changed</span></div>
            <div><span className="check">{p.decisions_changed}</span><span className="label">decisions changed</span></div>
            <div><span className="check soft">{p.later_rows_poisoned}</span><span className="label">later rows did change</span></div>
          </div>
          <p className="note">
            The test suite repeats it with a cutoff before every publication, and plants five leaks to prove it can fail.
          </p>
          <div className="controls inline"><button onClick={onPoison}>Show it on the replay (P)</button></div>
        </div>
        <div className="inset receipt">
          <h2>The sealed holdout</h2>
          <p className="proves">Proves the results were not tuned to the test.</p>
          <p>
            July to 23 October 2026 was never looked at. It is opened once, on Sunday morning, with the frozen recipe.
            The failure condition was written before any result: if ours does not beat persistence on Brier outside the
            90% interval, that null is the headline.
          </p>
        </div>
      </div>
      <LiveRecord />
    </>
  );
}

function LiveRecord() {
  const ledger = usePolled(LEDGER, LEDGER_REFRESH_MS, parseLedger);
  const commits = usePolled(COMMITS, COMMITS_REFRESH_MS, parseCommits);
  const rows = ledger.data;
  // Two live processes once made the same call within a millisecond; the score counts each half hour once, and so does this table.
  const clean = (rows?.filter((row) => !preFix(row)) ?? []).filter(
    (row, i, all) => all.findIndex((other) => other.target_start === row.target_start) === i,
  );
  const folded = (rows?.length ?? 0) - clean.length;
  const recent = clean.slice(-SHOWN_ROWS).reverse();

  return (
    <div className="inset receipt">
      <h2>The live record</h2>
      <p className="proves">Proves each call was made before anyone could know the answer.</p>
      <p>
        The model was frozen on Saturday afternoon. Since then a laptop makes the call for every half hour and pushes it
        to GitHub six minutes before that half hour's gate.
      </p>
      {ledger.failed && !rows && <p className="note">GitHub is out of reach from here; the record is in ledger/decisions.jsonl.</p>}
      {rows && (
        <>
          <p className="live-line">
            <span className="live-lamp" /> {clean.length} calls since the freeze, the latest for {recent[0]?.target_start.slice(11, 16) ?? 'none'} UTC
          </p>
          <table className="ledger-table">
            <thead><tr><th>half hour, UTC</th><th>called</th><th>trade</th><th>decided</th><th>on GitHub</th><th>before the gate</th></tr></thead>
            <tbody>
              {recent.map((row) => {
                const commit = commits.data?.get(`${row.target_start}|${row.decided_at}`);
                const lead = (Date.parse(row.gate) - Date.parse(commit?.at ?? row.decided_at)) / 60_000;
                return (
                  <tr key={`${row.target_start}|${row.decided_at}`}>
                    <td>{row.target_start.slice(5, 16).replace('T', ' ')}</td>
                    <td>{side(row.p_short)} {sure(row.p_short)}%</td>
                    <td>{verb(row.action)}</td>
                    <td>{row.decided_at.slice(11, 16)}</td>
                    <td>{commit ? <a href={commit.url} target="_blank" rel="noreferrer">{commit.at.slice(11, 16)}</a> : 'on GitHub'}</td>
                    <td>{lead.toFixed(0)} min</td>
                  </tr>
                );
              })}
              {folded > 0 && (
                <tr className="folded"><td colSpan={6}>{folded} earlier lines from the process running the code before the fix, kept unedited and not scored</td></tr>
              )}
            </tbody>
          </table>
          <p className="note">
            Model <span className="mono">{rows[rows.length - 1].model_sha256.slice(0, 12)}</span>, plain JSON with its own
            hash, so anyone can recompute every call. <a href={`${REPO}/commits/main/ledger/decisions.jsonl`} target="_blank" rel="noreferrer">Every push on GitHub</a>.
          </p>
        </>
      )}
    </div>
  );
}
