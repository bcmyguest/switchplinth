// Captures site screenshots with Playwright.
// Usage: node scripts/screenshots.mjs <baseUrl> <outDir>
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const [base = 'http://localhost:4321/', out = 'screenshots'] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const url = (p) => new URL(p, base).href;

const shots = [
  { name: 'landing', path: '', w: 1440, h: 900, full: true },
  { name: 'landing', path: '', w: 375, h: 812, full: true },
  { name: 'landing-sqs', path: '', w: 1440, h: 900, click: '[data-pick="sqs"]' },
  { name: 'docs-concepts', path: 'docs/concepts/', w: 1440, h: 900 },
  { name: 'docs-concepts', path: 'docs/concepts/', w: 375, h: 812 },
  { name: 'docs-roadmap', path: 'docs/roadmap/', w: 1440, h: 900 },
];

// PLAYWRIGHT_CHROMIUM lets you reuse an already-installed Chromium binary.
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined });
const report = [];
for (const theme of ['light', 'dark']) {
  for (const s of shots) {
    const ctx = await browser.newContext({ viewport: { width: s.w, height: s.h }, reducedMotion: 'no-preference' });
    await ctx.addInitScript((t) => localStorage.setItem('starlight-theme', t), theme);
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
    await page.goto(url(s.path), { waitUntil: 'networkidle' });
    await page.waitForTimeout(1200); // let the hero route draw in (auto-cycle starts after 4.2s)
    if (s.click) {
      await page.click(s.click);
      await page.mouse.move(0, 0);
      await page.waitForTimeout(1500);
    }
    const overflow = await page.evaluate(() => {
      if (document.documentElement.scrollWidth <= window.innerWidth) return false;
      const wide = [...document.querySelectorAll('body *')].find((el) => el.getBoundingClientRect().right > window.innerWidth + 1);
      return wide ? `${wide.tagName}.${wide.className}`.slice(0, 120) : true;
    });
    const file = `${out}/${theme}-${s.w}x${s.h}-${s.name}${s.full ? '-full' : ''}.png`;
    await page.screenshot({ path: file, fullPage: !!s.full });
    if (s.full) await page.screenshot({ path: file.replace('-full', '-top') });
    report.push({ file, theme: await page.evaluate(() => document.documentElement.dataset.theme), horizontalOverflow: overflow, errors });
    await ctx.close();
  }
}
await browser.close();
console.log(JSON.stringify(report, null, 2));
