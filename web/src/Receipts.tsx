import { hhmm, side, sure, verb, type Replay } from './data';
import { preFix, REPO, useLive, type Decision } from './live';

const SHOWN_ROWS = 8;

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
            <div><span className="check soft">{p.later_rows_poisoned}</span><span className="label">rows after the cutoff did change</span></div>
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
            July to 23 October 2026 was sealed until after the freeze, then opened once with the frozen recipe. The
            forecast held: Brier 0.232 against 0.242 for persistence and 0.247 for NESO, passing the test written before
            any result. The money did not: record price spreads made the fixed schedule earn £86 a day, and ours £72.
          </p>
        </div>
      </div>
      <LiveRecord />
    </>
  );
}

function LiveRecord() {
  const live = useLive();
  const { rows, clean, inTime, committedAt } = live;
  const oldCode = rows?.filter(preFix).length ?? 0;
  const copies = (rows?.length ?? 0) - oldCode - clean.length;
  const recent = clean.slice(-SHOWN_ROWS).reverse();
  const counted = clean.filter(inTime).length;
  const trades = clean.filter((row) => row.action !== 0).length;
  const commitOf = (row: Decision) => (committedAt(row) ? { at: committedAt(row)!, url: live.commits?.get(`${row.target_start}|${row.decided_at}`)?.url ?? '' } : undefined);

  return (
    <div className="inset receipt">
      <h2>The live record</h2>
      <p className="proves">Proves each call was made before anyone could know the answer.</p>
      <p>
        The model was frozen on Saturday afternoon. Since then a laptop makes the call for each half hour six minutes
        before its gate and commits it to GitHub. A call counts only if it was committed before its gate.
      </p>
      {live.failed && !rows && <p className="note">GitHub is out of reach from here; the record is in ledger/decisions.jsonl.</p>}
      {rows && (
        <>
          <p className="live-line">
            <span className="live-lamp" /> {clean.length} calls since the freeze, {counted} committed in time; the latest for{' '}
            {recent[0]?.target_start.slice(11, 16) ?? 'none'} UTC. {trades === 0 ? 'The battery started empty and has held so far.' : `${trades} trades so far.`}
          </p>
          <table className="ledger-table">
            <thead><tr><th>half hour, UTC</th><th>called</th><th>trade</th><th>decided</th><th>committed</th><th>before the gate</th></tr></thead>
            <tbody>
              {recent.map((row) => {
                const commit = commitOf(row);
                const lead = (Date.parse(row.gate) - Date.parse(commit?.at ?? row.decided_at)) / 60_000;
                return (
                  <tr key={`${row.target_start}|${row.decided_at}`} className={inTime(row) ? undefined : 'late'}>
                    <td>{row.target_start.slice(5, 16).replace('T', ' ')}</td>
                    <td>{side(row.p_short)} {sure(row.p_short)}%</td>
                    <td>{verb(row.action)}</td>
                    <td>{row.decided_at.slice(11, 16)}</td>
                    <td>{commit ? <a href={commit.url} target="_blank" rel="noreferrer">{commit.at.slice(11, 16)}</a> : 'on GitHub'}</td>
                    <td>{lead > 0 ? `${lead.toFixed(0)} min` : `after the gate, not counted`}</td>
                  </tr>
                );
              })}
              {oldCode + copies > 0 && (
                <tr className="folded"><td colSpan={6}>
                  Not shown, kept unedited and not counted: {oldCode} calls from a process still running the code before the fix
                  {copies > 0 ? `, and ${copies} duplicate${copies > 1 ? 's' : ''} from two processes running at once` : ''}
                </td></tr>
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
