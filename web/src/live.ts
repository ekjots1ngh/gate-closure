import { useEffect, useState } from 'react';

/** The live record as pushed to GitHub: the ledger of calls, each call's commit, and what each half hour turned out to be. */

export const REPO = 'https://github.com/ekjots1ngh/gate-closure';
const RAW = 'https://raw.githubusercontent.com/ekjots1ngh/gate-closure/main/ledger';
const LEDGER = `${RAW}/decisions.jsonl`;
const OUTCOMES = `${RAW}/outcomes.json`;
const COMMITS = 'https://api.github.com/repos/ekjots1ngh/gate-closure/commits?path=ledger/decisions.jsonl&per_page=100';
const RAW_REFRESH_MS = 60_000;
const COMMITS_REFRESH_MS = 5 * 60_000;   // GitHub allows 60 unauthenticated API calls an hour

export interface Decision {
  target_start: string;
  gate: string;
  decided_at: string;
  p_short: number;
  action: number;
  soc_after: number;
  model_sha256: string;
  inputs: Record<string, number | null>;
}
export interface Outcome { target_start: string; price: number; short: boolean; printed_at: string; pnl: number }
export interface Commit { url: string; at: string }

// Mirrors gclose/live.py: lines from the code before PROTOCOL amendment 8 carry its bug's signature,
// a side for the newest period although its volume had not printed. They stay in the ledger and are not scored.
export const preFix = (row: Decision) => row.inputs.short_newest !== null && row.inputs.niv_newest === null;

/** Fetch `url` now and every `ms`, keeping the last good result; null until the first answer. */
export function usePolled<T>(url: string, ms: number, parse: (body: string) => T): { data: T | null; failed: boolean } {
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
const parseOutcomes = (body: string): Outcome[] => JSON.parse(body);

/** Each ledger commit's GitHub page and commit time, keyed by "target|decided_at" from its message.
 *  The author date is when the laptop committed the call; the committer date moves when a pull rebases it. */
const parseCommits = (body: string): Map<string, Commit> => {
  const commits = new Map<string, Commit>();
  for (const c of JSON.parse(body) as { html_url: string; commit: { message: string; author: { date: string } } }[]) {
    const match = /^ledger: (\S+) decided at (\S+)/.exec(c.commit.message);
    if (match) commits.set(`${match[1]}|${match[2]}`, { url: c.html_url, at: new Date(c.commit.author.date).toISOString() });
  }
  return commits;
};

export interface Live {
  rows: Decision[] | null;          // every ledger line, as pushed
  clean: Decision[];                // one call per half hour, old-code lines left out
  outcomes: Map<string, Outcome>;   // by target_start
  commits: Map<string, Commit> | null;
  committedAt: (row: Decision) => string | undefined;
  inTime: (row: Decision) => boolean;   // committed before its gate, so it counts
  failed: boolean;
}

export function useLive(): Live {
  const ledger = usePolled(LEDGER, RAW_REFRESH_MS, parseLedger);
  const outcomes = usePolled(OUTCOMES, RAW_REFRESH_MS, parseOutcomes);
  const commits = usePolled(COMMITS, COMMITS_REFRESH_MS, parseCommits);
  const rows = ledger.data;
  // Two live processes once made the same call within a millisecond; each half hour counts once.
  const clean = (rows?.filter((row) => !preFix(row)) ?? []).filter(
    (row, i, all) => all.findIndex((other) => other.target_start === row.target_start) === i,
  );
  const committedAt = (row: Decision) => commits.data?.get(`${row.target_start}|${row.decided_at}`)?.at;
  const inTime = (row: Decision) => Date.parse(committedAt(row) ?? row.decided_at) < Date.parse(row.gate);
  return {
    rows, clean, commits: commits.data, committedAt, inTime, failed: ledger.failed,
    outcomes: new Map((outcomes.data ?? []).map((o) => [o.target_start, o])),
  };
}
