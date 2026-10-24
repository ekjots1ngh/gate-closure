Scaffold for the demo, not built yet. What exists: Vite + React + d3 config, and `src/data.ts`, which types
`public/replay.json` (written by `python -m gclose.export`) and precomputes the cumulative series the animation
reads. `src/App.tsx` and `src/styles.css`, imported by `src/main.tsx`, are still to be written, so `npm run build`
fails until they are.

Once built: `cd web && npm install && npm run build`, then `cd dist && python -m http.server 8000` and open
http://localhost:8000 (works offline).
