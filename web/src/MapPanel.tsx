import * as d3 from 'd3';
import { useMemo } from 'react';
import type { Row } from './data';
import gb from './gb.json';
import { lamp } from './GateChart';
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
const GREAT_BRITAIN = '826';   // the UK feature; Ireland (372) is drawn but not part of this grid

const mw = (x: number | null) => (x === null ? 'unknown' : `${Math.round(x).toLocaleString('en-GB')} MW`);
const signed = (x: number | null) => (x === null ? '' : x === 0 ? 'no change' : `${x > 0 ? '+' : '−'}${Math.round(Math.abs(x)).toLocaleString('en-GB')} MW`);

interface Props {
  decided: Row | null;   // the half hour decided at the latest gate
  pulseKey: number;      // changes at every gate, so the lamps pulse once per decision
}

/**
 * Great Britain, tinted with the forecast for the period just decided, with the offshore wind
 * farms lit by the latest revision to the national wind forecast; below, what the model saw.
 */
export default function MapPanel({ decided, pulseKey }: Props) {
  const [ref, { width, height }] = useSize<HTMLDivElement>({ width: 320, height: 420 });
  const path = useMemo(() => {
    const frame = { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [[-8.2, 49.8], [3.0, 59.3]] } };
    const projection = d3.geoMercator().fitExtent([[6, 6], [width - 6, height - 6]], frame as d3.GeoPermissibleObjects);
    return { projection, draw: d3.geoPath(projection) };
  }, [width, height]);

  const revision = decided?.wind_revision_mw ?? null;
  const cut = (revision ?? 0) < 0;
  const strength = Math.min(1, Math.abs(revision ?? 0) / 800);
  const windColour = cut ? 'var(--short)' : 'var(--long)';
  const forecast = decided ? lamp(decided.p_ours) : null;
  const indicated = decided?.indicated_latest_mw ?? null;

  return (
    <>
      <div ref={ref} className="fill">
        <svg width={width} height={height} role="img" aria-label="Great Britain, tinted with the forecast, and its offshore wind farms">
          {(gb as unknown as d3.ExtendedFeatureCollection).features.map((f) => (
            <g key={String(f.id)}>
              <path d={path.draw(f) ?? ''} fill="var(--land)" stroke="var(--rule)" strokeWidth={0.8} />
              {String(f.id) === GREAT_BRITAIN && forecast && (
                <path className="tint" d={path.draw(f) ?? ''} fill={forecast.fill} fillOpacity={0.08 + 0.45 * Math.abs(decided!.p_ours - 0.5) * 2} />
              )}
            </g>
          ))}
          {FARMS.map(([name, lon, lat, capacity]) => {
            const [cx, cy] = path.projection([lon, lat])!;
            const r = Math.max(2.5, Math.sqrt(capacity) / 5.5);
            return (
              <g key={name}>
                <title>{`${name}, about ${capacity} MW`}</title>
                <circle className="lamp" cx={cx} cy={cy} r={r} fill={windColour} opacity={0.3 + 0.7 * strength} />
                <circle key={pulseKey} className="pulse" cx={cx} cy={cy} r={r} stroke={windColour} />
              </g>
            );
          })}
        </svg>
      </div>
      <div className="readouts" aria-label="What the model saw at the gate">
        <span className="label">Wind forecast</span>
        <span className="value readout">{mw(decided?.wind_latest_mw ?? null)}</span>
        <span className="delta readout" style={revision ? { color: windColour } : undefined}>{signed(revision)}{revision ? ' revision' : ''}</span>
        <span className="label">Demand forecast</span>
        <span className="value readout">{mw(decided?.demand_latest_mw ?? null)}</span>
        <span className="delta readout">{signed(decided?.demand_revision_mw ?? null)}</span>
        <span className="label">NESO indicated</span>
        <span className="value readout">{indicated === null ? 'unknown' : mw(Math.abs(indicated))}</span>
        <span className="delta">{indicated === null ? '' : indicated > 0 ? 'surplus, long' : 'deficit, short'}</span>
        <div className="verdict">
          <span className="label">Our forecast for {decided ? decided.t.slice(11, 16) : 'the next half hour'}</span>
          {forecast && decided && (
            <span className="big readout" style={{ color: forecast.fill }}>
              {decided.p_ours >= 0.5 ? 'short' : 'long'} {(100 * Math.max(decided.p_ours, 1 - decided.p_ours)).toFixed(0)}%
            </span>
          )}
        </div>
      </div>
      <p className="note">
        Newest versions published before the gate. A late cut to the wind forecast is how the grid ends up short; the lamps
        mark major offshore wind farms at approximate positions, sized by capacity.
      </p>
    </>
  );
}
