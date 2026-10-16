// Exports the docs pipeline diagram as standalone SVG and PNG files for the
// product README, docs, and articles. Run after `pnpm build`.
// Usage: node scripts/export-architecture.mjs [outDir ...]
//   Writes public/diagrams/ plus a copy in each outDir.
//   PLAYWRIGHT_CHROMIUM=/path/to/chrome reuses an installed Chromium.
//
// Each SVG carries its own <style>: the light tokens from src/theme.yml on the
// root, dark tokens under prefers-color-scheme, and src/styles/pipeline.css.
// PNGs use the light theme with DM Sans embedded; the wide sheet renders
// 1600px wide, the stacked sheet 720px wide.
import { chromium } from 'playwright';
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { parse } from 'yaml';

const root = new URL('..', import.meta.url);
const read = (p) => readFileSync(new URL(p, root), 'utf8');
const outDirs = process.argv.slice(2);
const publicDir = new URL('public/diagrams/', root).pathname;
mkdirSync(publicDir, { recursive: true });

const html = read('dist/docs/architecture/index.html');
const { light, dark } = parse(read('src/theme.yml')).theme.semantic;
const vars = (tokens) => Object.entries(tokens).map(([k, v]) => `--c-${k}:${v};`).join('');
// Figure layout rules only apply inside the docs page.
const sheetCss = read('src/styles/pipeline.css').split('/* Wide sheet in a figure')[0].replace(/\/\*[\s\S]*?\*\//g, '').trim();
const style = `svg{${vars(light)}}@media (prefers-color-scheme: dark){svg{${vars(dark)}}}\n${sheetCss}`;

const sheets = [
  { id: 'wide', file: 'architecture-pipeline', pngWidth: 1600 },
  { id: 'tall', file: 'architecture-pipeline-vertical', pngWidth: 720 },
];

const font = (weight) =>
  `@font-face{font-family:'DM Sans';font-weight:${weight};src:url(data:font/woff2;base64,${readFileSync(
    new URL(`node_modules/@fontsource/dm-sans/files/dm-sans-latin-${weight}-normal.woff2`, root),
  ).toString('base64')}) format('woff2');}`;

const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined });
for (const sheet of sheets) {
  const match = html.match(new RegExp(`<svg class="pl-sheet pl-${sheet.id}"[\\s\\S]*?</svg>`));
  if (!match) throw new Error(`No ${sheet.id} sheet in dist/docs/architecture/index.html; run pnpm build first.`);
  const [, w, h] = match[0].match(/viewBox="0 0 (\d+) (\d+)"/);
  const svg = match[0]
    .replace(/<svg class="pl-sheet pl-\w+"[^>]*>/, `<svg xmlns="http://www.w3.org/2000/svg" class="pl-sheet" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-labelledby="pl-title-${sheet.id} pl-desc-${sheet.id}">`)
    .replace(/(<\/desc>)/, `$1<style>${style}</style>`);
  const svgPath = join(publicDir, `${sheet.file}.svg`);
  writeFileSync(svgPath, `${svg}\n`);

  const page = await browser.newPage({ viewport: { width: sheet.pngWidth, height: 800 }, colorScheme: 'light' });
  await page.setContent(
    `<!doctype html><style>${font(400)}${font(600)}html,body{margin:0;background:${light.canvas}}svg{display:block;width:100%;height:auto}</style>${svg}`,
  );
  await page.evaluate(() => document.fonts.ready);
  const pngPath = join(publicDir, `${sheet.file}.png`);
  await page.locator('svg.pl-sheet').screenshot({ path: pngPath });
  await page.close();

  for (const dir of outDirs) {
    mkdirSync(dir, { recursive: true });
    copyFileSync(svgPath, join(dir, `${sheet.file}.svg`));
    copyFileSync(pngPath, join(dir, `${sheet.file}.png`));
  }
  console.log(`${sheet.file}: ${w}x${h} SVG, ${sheet.pngWidth}px PNG`);
}
await browser.close();
