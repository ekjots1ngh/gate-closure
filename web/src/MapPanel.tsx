import * as d3 from 'd3';
import { useMemo } from 'react';
import { gbp, hhmm, PERIOD_MS, printedCount, tone, type Derived, type Replay } from './data';
import gb from './gb.json';
import { useSize } from './useSize';

/** Major offshore wind farms: approximate positions and capacities in MW, for orientation only. */
const FARMS: [string, number, number, number][] = [
  ['Hornsea One', 1.79, 53.88, 1218], ['Hornsea Two', 1.67, 53.94, 1386], ['Dogger Bank', 1.9, 54.75, 2400],
  ['East Anglia One', 2.49, 52.24, 714], ['London Array', 1.5, 51.63, 630], ['Greater Gabbard', 1.94, 51.88, 504],
  ['Galloper', 2.03, 51.89, 353], ['Thanet', 1.63, 51.43, 300], ['Rampion', -0.27, 50.67, 400],
  ['Race Bank', 0.85, 53.27, 573], ['Triton Knoll', 0.83, 53.49, 857], ['Dudgeon', 1.38, 53.27, 402],
  ['Sheringham Shoal', 1.15, 53.13, 317], ['Lincs', 0.48, 53.18, 270], ['Humber Gateway', 0.29, 53.64, 219],
  ['Walney', -3.6, 54.06, 1026], ['West of Duddon Sands', -3.46, 53.98, 389], ['Burbo Bank', -3.27, 53.48, 258],
  ['Gwynt y Môr', -3.58, 53.45, 576], ['Moray East', -2.72, 58.19, 950], ['Moray West', -3.0, 58.1, 882],
  ['Beatrice', -3.09, 58.25, 588], ['Seagreen', -1.76, 56.58, 1075], ['Neart na Gaoithe', -2.32, 56.27, 450],
  ['Kincardine', -1.85, 57.01, 50], ['Hywind Scotland', -1.35, 57.48, 30], ['Robin Rigg', -3.72, 54.75, 174],
];
const WIND_FULL_MW = 15_000;   // a national wind forecast this high lights the farms fully

const mw = (x: number | null) => (x === null ? 'unknown' : `${Math.round(x).toLocaleString('en-GB')} MW`);
const revised = (x: number | null) =>
  x === null ? '' : x === 0 ? 'unrevised' : `${x > 0 ? '+' : '−'}${Math.round(Math.abs(x)).toLocaleString('en-GB')} revised`;

interface Props {
  r: Replay;
  d: Derived;
  now: number;
}

/** What the model saw at the latest gate: the newest price and the forecasts, and the wind across Great Britain. */
export default function MapPanel({ r, d, now }: Props) {
  const [ref, { width, height }] = useSize<HTMLDivElement>({ width: 280, height: 260 });
  const path = useMemo(() => {
    const frame = { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [[-8.2, 49.8], [3.0, 59.3]] } };
    const projection = d3.geoMercator().fitExtent([[4, 4], [width - 4, height - 4]], frame as d3.GeoPermissibleObjects);
    return { projection, draw: d3.geoPath(projection) };
  }, [width, height]);

  const gate = Math.floor(now / PERIOD_MS) * PERIOD_MS;
  const row = r.tape[(gate + 2 * PERIOD_MS - d.t0) / PERIOD_MS] ?? null;   // the period decided at this gate
  const known = printedCount(d, gate) - 1;                                                  // the newest price public at the gate
  const newest = known >= 0 ? r.tape[known] : null;
  const wind = row?.wind_latest_mw ?? null;
  const strength = Math.min(1, (wind ?? 0) / WIND_FULL_MW);
  const indicated = row?.indicated_latest_mw ?? null;

  return (
    <>
      <h2>What the model saw at the {hhmm(gate)} gate</h2>
      <div className="readouts">
        <span className="label">Newest price</span>
        <span className="value readout">{newest ? gbp(newest.price) : 'unknown'}</span>
        <span className="delta">
          {newest && <>{hhmm(d.starts[known])}, <span style={{ color: tone(newest.short ? 'short' : 'long') }}>{newest.short ? 'short' : 'long'}</span></>}
        </span>
        <span className="label">Wind forecast</span>
        <span className="value readout">{mw(wind)}</span>
        <span className="delta readout">{revised(row?.wind_revision_mw ?? null)}</span>
        <span className="label">Demand forecast</span>
        <span className="value readout">{mw(row?.demand_latest_mw ?? null)}</span>
        <span className="delta readout">{revised(row?.demand_revision_mw ?? null)}</span>
        <span className="label">NESO imbalance</span>
        <span className="value readout">{indicated === null ? 'unknown' : mw(Math.abs(indicated))}</span>
        <span className="delta">
          {indicated !== null && <span style={{ color: tone(indicated > 0 ? 'long' : 'short') }}>{indicated > 0 ? 'surplus, long' : 'deficit, short'}</span>}
        </span>
      </div>
      <div ref={ref} className="fill map-frame">
        <svg width={width} height={height} role="img" aria-label="Great Britain and its offshore wind farms, lit by the national wind forecast">
          {(gb as unknown as d3.ExtendedFeatureCollection).features.map((f) => (
            <path key={String(f.id)} d={path.draw(f) ?? ''} fill="var(--land)" stroke="var(--rule)" strokeWidth={0.8} />
          ))}
          {FARMS.map(([name, lon, lat, capacity]) => {
            const [cx, cy] = path.projection([lon, lat])!;
            return (
              <circle key={name} className="lamp" cx={cx} cy={cy} r={Math.max(2.2, Math.sqrt(capacity) / 6)}
                fill="var(--ink)" opacity={0.18 + 0.72 * strength}>
                <title>{`${name}, about ${capacity} MW`}</title>
              </circle>
            );
          })}
        </svg>
      </div>
      <p className="legend">Offshore wind farms, sized by capacity, lit by the national wind forecast.</p>
    </>
  );
}
