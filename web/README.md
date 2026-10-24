The demo: one week of the GB grid replayed at gate closure, in React and d3.

`npm run build` writes `dist/index.html`, a single self-contained page (data, fonts and code inlined), so it opens
offline by double-clicking it. `npm run dev` serves it with live reload.

The data is `public/replay.json`, written by `python -m gclose.export` from the pipeline's results; `src/data.ts` types
it and precomputes the cumulative series the animation reads. The coastline in `src/gb.json` comes from the
world-atlas package (Natural Earth, public domain) via `scripts/gb-outline.mjs`. The live record table fetches
`ledger/decisions.jsonl` from GitHub each minute and says so when it cannot.

Files: `App.tsx` (the clock, keys and layout), `GateChart.tsx` (prices, the gate and the lamps), `MapPanel.tsx`
(wind revisions on the map), `Battery.tsx` (state of charge and the week's money), `Skill.tsx` (what accuracy is
worth), `MoneyLadder.tsx` (every policy's money, with the ceilings), `Receipts.tsx` (the poison check and the live
record).
