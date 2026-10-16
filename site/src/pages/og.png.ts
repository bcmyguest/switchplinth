import type { APIRoute } from 'astro';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import satori from 'satori';
import { Resvg } from '@resvg/resvg-js';
import { site } from '../site.config';

// Build-time Open Graph image (1200x630). Re-renders when site.config changes.
const require = createRequire(import.meta.url);
const font = (weight: number) =>
  readFileSync(require.resolve(`@fontsource/dm-sans/files/dm-sans-latin-${weight}-normal.woff`));

type Node = { type: string; props: Record<string, unknown> };
const h = (type: string, style: Record<string, unknown>, children?: unknown): Node => ({
  type,
  props: { style, children },
});

const pill = (label: string, active: boolean) =>
  h(
    'div',
    {
      display: 'flex',
      marginRight: 16,
      padding: '10px 22px',
      borderRadius: 12,
      fontSize: 26,
      fontWeight: 700,
      border: `2px solid ${active ? '#a6d0ae' : '#3a4a3d'}`,
      background: active ? '#2b4933' : '#19211b',
      color: active ? '#edf4ee' : '#bdc8be',
    },
    label,
  );

export const GET: APIRoute = async () => {
  const tree = h(
    'div',
    {
      // Satori sizes boxes content-box: 1200x630 minus 2x72 padding.
      width: 1056,
      height: 486,
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'space-between',
      padding: 72,
      background: '#111713',
      color: '#edf4ee',
      fontFamily: 'DM Sans',
    },
    [
      h('div', { display: 'flex', fontSize: 34, fontWeight: 700, color: '#a6d0ae' }, site.name),
      h('div', { display: 'flex', fontSize: 60, fontWeight: 700, lineHeight: 1.15, maxWidth: 1000 }, site.tagline),
      h('div', { display: 'flex', flexDirection: 'row', alignItems: 'center', width: '100%' }, [
        h('div', { display: 'flex', fontSize: 24, color: '#bdc8be', marginRight: 18 }, 'Event transport:'),
        pill('Apache Kafka', false),
        pill('Amazon SQS', true),
        h('div', { display: 'flex', fontSize: 24, color: '#bdc8be', marginLeft: 'auto' }, 'Local-first · Markdown · MCP'),
      ]),
    ],
  );
  const svg = await satori(tree as never, {
    width: 1200,
    height: 630,
    fonts: [
      { name: 'DM Sans', data: font(400), weight: 400, style: 'normal' },
      { name: 'DM Sans', data: font(700), weight: 700, style: 'normal' },
    ],
  });
  const png = new Resvg(svg).render().asPng();
  return new Response(new Uint8Array(png), { headers: { 'Content-Type': 'image/png' } });
};
