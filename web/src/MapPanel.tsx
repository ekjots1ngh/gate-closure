import * as d3 from 'd3';
import { useMemo } from 'react';
import gb from './gb.json';
import { useWidth } from './useSize';

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

const HEIGHT = 560;

interface Props {
  revisionMw: number | null;   // the national wind forecast revision at the latest gate
  pulseKey: number;            // changes at every gate, so the lamps pulse once per decision
}

/** Offshore wind around Great Britain, lit by the latest revision to the national wind forecast. */
export default function MapPanel({ revisionMw, pulseKey }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>(300);
  const path = useMemo(() => {
    const frame = { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [[-8.2, 49.8], [3.0, 59.3]] } };
    const projection = d3.geoMercator().fitExtent([[4, 4], [width - 4, HEIGHT - 4]], frame as d3.GeoPermissibleObjects);
    return { projection, draw: d3.geoPath(projection) };
  }, [width]);

  const cut = (revisionMw ?? 0) < 0;
  const strength = Math.min(1, Math.abs(revisionMw ?? 0) / 800);
  const colour = cut ? 'var(--short)' : 'var(--long)';

  return (
    <div ref={ref}>
      <svg width={width} height={HEIGHT} role="img" aria-label="Offshore wind farms around Great Britain">
        {(gb as unknown as d3.ExtendedFeatureCollection).features.map((f) => (
          <path key={String(f.id)} d={path.draw(f) ?? ''} fill="#36423c" stroke="var(--rule)" strokeWidth={0.8} />
        ))}
        {FARMS.map(([name, lon, lat, mw]) => {
          const [cx, cy] = path.projection([lon, lat])!;
          const r = Math.max(2.5, Math.sqrt(mw) / 5.5);
          return (
            <g key={name}>
              <title>{`${name}, about ${mw} MW`}</title>
              <circle className="lamp" cx={cx} cy={cy} r={r} fill={colour} opacity={0.3 + 0.7 * strength} />
              <circle key={pulseKey} className="pulse" cx={cx} cy={cy} r={r} stroke={colour} />
            </g>
          );
        })}
      </svg>
      <p className="readout-line">
        Wind forecast revision at the gate:{' '}
        <strong style={{ color: colour }}>{revisionMw === null ? 'none' : `${revisionMw > 0 ? '+' : '−'}${Math.abs(revisionMw).toLocaleString('en-GB')} MW`}</strong>
      </p>
      <p className="note">
        A late cut to the wind forecast is how the grid ends up short. The revision is national; the lamps mark
        major offshore wind farms at approximate positions, sized by capacity.
      </p>
    </div>
  );
}
