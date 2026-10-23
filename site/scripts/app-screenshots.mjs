// Captures the README images from the running product, not from site illustrations.
// Usage: node scripts/app-screenshots.mjs <appUrl> <outDir>
//
// <appUrl> is the frontend (for example http://localhost:3000/) serving a fresh bootstrap of fixtures/food-delivery.
// The review-log shot confirms two aliases, so run it on a disposable copy. Writes 1280x800 light-theme PNGs and
// hero-loop.gif: the real map switching order events Kafka -> SQS -> Kafka in the What-if panel.
import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import { PNG } from 'pngjs';
import gifenc from 'gifenc';

const { GIFEncoder, quantize, applyPalette } = gifenc;
const [base = 'http://localhost:3000/', out = 'app-screenshots'] = process.argv.slice(2);
const VIEWPORT = { width: 1280, height: 800 };
const EVENT_DELIVERY = 'Event delivery for food orders';
const HERO_HOLD_MS = 2600;
const SETTLE_MS = 900;
const TOPBAR_CLEARANCE_PX = 72;
mkdirSync(out, { recursive: true });

// PLAYWRIGHT_CHROMIUM lets you reuse an already-installed Chromium binary.
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined });
const report = [];

async function open(hash) {
  const ctx = await browser.newContext({ viewport: VIEWPORT, reducedMotion: 'reduce' });
  await ctx.addInitScript(() => localStorage.setItem('switchplinth-theme', 'light'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(new URL(`#${hash}`, base).href, { waitUntil: 'networkidle' });
  await page.locator('.react-flow__node').first().waitFor({ state: 'attached' });
  await page.waitForTimeout(SETTLE_MS);
  return { page, errors, close: () => ctx.close() };
}

async function settled(page) {
  await page.waitForFunction(() => !/Comparing with|Resolving/.test(document.querySelector('.scenario-panel')?.textContent ?? ''));
  await page.mouse.move(0, 0);
  await page.waitForTimeout(SETTLE_MS);
}

async function chooseEventDelivery(page, option) {
  await page.locator('.decision-select').filter({ has: page.locator('.decision-name', { hasText: EVENT_DELIVERY }) }).getByRole('button', { name: new RegExp(`^${option}`) }).click();
  await settled(page);
  // The panel's sticky header grows while exploring; re-center so every frame frames the decision the same way.
  await page.getByRole('button', { name: `Jump to ${EVENT_DELIVERY} options` }).click();
  await settled(page);
}

/** Scrolls `locator` to the top of the page, below the sticky top bar. */
async function scrollToTop(page, locator) {
  await locator.evaluate((element, clearance) => window.scrollTo({ top: element.getBoundingClientRect().top + window.scrollY - clearance }), TOPBAR_CLEARANCE_PX);
  await page.waitForTimeout(SETTLE_MS);
}

async function shoot(name, session) {
  const file = `${out}/${name}.png`;
  await session.page.screenshot({ path: file });
  report.push({ file, errors: session.errors });
}

/** Full-screen map with What-if scrolled to Event delivery; Kafka is the repository choice. */
async function whatIfMap() {
  const session = await open('architecture');
  const { page } = session;
  await page.getByRole('button', { name: 'Open map full screen' }).click();
  await page.getByRole('button', { name: 'What-if', exact: true }).click();
  await page.getByRole('button', { name: `Jump to ${EVENT_DELIVERY} options` }).click();
  await settled(page);
  return session;
}

async function hero() {
  const session = await whatIfMap();
  const { page } = session;
  const frames = [await page.screenshot({ type: 'png' })];
  await chooseEventDelivery(page, 'Amazon SQS');
  frames.push(await page.screenshot({ type: 'png' }));
  await shoot('whatif-map', session);
  await chooseEventDelivery(page, 'Apache Kafka');
  const decoded = frames.map((frame) => PNG.sync.read(frame));
  const { width, height } = decoded[0];
  const sample = new Uint8Array(width * height * 4 * 2);
  decoded.forEach((image, index) => sample.set(image.data, index * width * height * 4));
  const palette = quantize(sample, 256);
  const gif = GIFEncoder();
  decoded.forEach((image, index) => gif.writeFrame(applyPalette(image.data, palette), width, height, { palette: index === 0 ? palette : undefined, delay: HERO_HOLD_MS, repeat: 0 }));
  gif.finish();
  writeFileSync(`${out}/hero-loop.gif`, gif.bytes());
  report.push({ file: `${out}/hero-loop.gif`, frames: frames.length, errors: session.errors });
  await session.close();
}

async function architectureLog() {
  const session = await open('architecture-log');
  await scrollToTop(session.page, session.page.locator('.log-entry').filter({ has: session.page.locator('h3', { hasText: EVENT_DELIVERY }) }));
  await shoot('architecture-log', session);
  await session.close();
}

async function reviewLog() {
  const session = await open('facts');
  const { page } = session;
  for (let index = 0; index < 2; index += 1) {
    const before = await page.locator('[data-review-entry]').count();
    await page.getByRole('button', { name: /^Confirm alias: / }).first().click();
    await page.waitForFunction((count) => document.querySelectorAll('[data-review-entry]').length > count, before);
  }
  await scrollToTop(page, page.locator('#review-log'));
  await shoot('review-log', session);
  await session.close();
}

async function whySearch() {
  const session = await open('explore');
  const { page } = session;
  await page.getByRole('textbox').fill('Why are we using Kafka?');
  await page.keyboard.press('Enter');
  await page.locator('.answer-card').waitFor();
  await scrollToTop(page, page.locator('.answer-card').first());
  await shoot('why-search', session);
  await session.close();
}

try {
  await hero();
  await architectureLog();
  await reviewLog();
  await whySearch();
} finally {
  await browser.close();
}
console.log(JSON.stringify(report, null, 2));
