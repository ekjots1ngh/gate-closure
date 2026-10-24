// Writes src/gb.json: the coastlines of Great Britain and Ireland from Natural Earth (via
// world-atlas), cut to the map's frame. Run once with `node scripts/gb-outline.mjs`.
import { readFileSync, writeFileSync } from 'node:fs';
import { feature } from 'topojson-client';

const world = JSON.parse(readFileSync('node_modules/world-atlas/countries-10m.json', 'utf8'));
const countries = feature(world, world.objects.countries);
const keep = new Set(['826', '372']); // United Kingdom, Ireland
const round = (coords) => Array.isArray(coords[0]) ? coords.map(round) : coords.map((c) => Math.round(c * 1000) / 1000);
const shapes = countries.features
  .filter((f) => keep.has(String(f.id)))
  .map((f) => ({ type: 'Feature', id: String(f.id), properties: {}, geometry: { ...f.geometry, coordinates: round(f.geometry.coordinates) } }));
writeFileSync('src/gb.json', JSON.stringify({ type: 'FeatureCollection', features: shapes }));
console.log('wrote src/gb.json', shapes.map((s) => s.id), Math.round(JSON.stringify(shapes).length / 1024), 'kB');
