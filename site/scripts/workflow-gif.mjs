// Records the README workflow GIF: write an ADR, run Discover, read it in the Architecture log, find it on the map,
// and preview its alternative in What-if.
// Usage: node scripts/workflow-gif.mjs <appUrl> <repoDir> <outFile>
//
// <appUrl> is the frontend serving a fresh bootstrap of fixtures/food-delivery, and <repoDir> is that same repository
// on disk (for scripts/demo.sh, ~/.cache/switchplinth-demo/food-delivery). The script writes the ADR below into
// <repoDir>/decisions/ and runs a mock Discover, so use a disposable copy. Every step after the editor frames is the
// running app; the editor frames show the file being written. Captions are drawn on top of the page.
import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { PNG } from 'pngjs';
import gifenc from 'gifenc';

const { GIFEncoder, quantize, applyPalette } = gifenc;
const [base = 'http://localhost:3000/', repoDir, outFile = 'workflow.gif'] = process.argv.slice(2);
if (!repoDir) throw new Error('Usage: node scripts/workflow-gif.mjs <appUrl> <repoDir> <outFile>');
const VIEWPORT = { width: 1280, height: 800 };
const ADR_PATH = 'decisions/restaurant-notifications.md';
const DECISION = 'Restaurant notification queue';
const ALTERNATIVE = 'Apache Kafka topic';
const SETTLE_MS = 900;
const TYPING_FRAME_MS = 900;
const STEP_FRAME_MS = 3200;
const LAST_FRAME_MS = 4200;
const TOPBAR_CLEARANCE_PX = 72;
// An empty stretch of the full-screen canvas between the resource and technology rows at 1280x800.
const PAN_FROM = { x: 700, y: 620 };
const PAN_LEFT_PX = 300;
// The mock extractor only knows the sample's technologies and services, so the ADR uses them.
const ADR = `# Restaurant notification queue

## Context

The Restaurant Service must tell restaurants about new orders even when a kitchen tablet is offline for a few minutes. Each notification stands alone, so delivery does not need ordering or replay.

## Decision

We chose Amazon SQS because each notification can be retried on its own and a dead-letter queue keeps failed deliveries visible to support.

## Alternative: Apache Kafka topic

A Kafka topic would reuse the existing broker, but every kitchen tablet would need its own consumer offsets, which the restaurant team does not want to operate.

## Consequences

Support reviews the dead-letter queue each morning and replays nothing automatically.
`;
const CAPTION_STYLE = 'position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:2147483647;max-width:1040px;padding:12px 18px;border-radius:12px;background:#17271dee;color:#f4f8f4;font:600 17px/1.35 "DM Sans",system-ui,sans-serif;box-shadow:0 6px 24px #0005;pointer-events:none';
const EDITOR_STYLE = `body{margin:0;background:#f3f4f1;font-family:"DM Sans",system-ui,sans-serif}
.window{margin:48px auto;width:1040px;border:1px solid #d6ddd6;border-radius:12px;background:#fff;box-shadow:0 8px 30px #1d33221c;overflow:hidden}
.tab{padding:12px 18px;border-bottom:1px solid #e3e8e3;background:#f8faf7;color:#405d46;font:600 14px "DM Mono",ui-monospace,monospace}
pre{margin:0;padding:22px 26px;min-height:520px;white-space:pre-wrap;color:#202522;font:15px/1.6 "DM Mono",ui-monospace,monospace}
.h{color:#2f6b43;font-weight:700}`;

const frames = [];

async function caption(page, text) {
  await page.evaluate(({ text, style }) => {
    let element = document.getElementById('workflow-caption');
    if (!element) {
      element = document.createElement('div');
      element.id = 'workflow-caption';
      element.setAttribute('style', style);
      document.body.append(element);
    }
    element.textContent = text;
  }, { text, style: CAPTION_STYLE });
}

async function frame(page, delay) {
  await page.mouse.move(0, 0);
  frames.push({ png: await page.screenshot({ type: 'png' }), delay });
}

async function settled(page) {
  await page.waitForFunction(() => !/Comparing with|Resolving/.test(document.querySelector('.scenario-panel')?.textContent ?? ''));
  await page.waitForTimeout(SETTLE_MS);
}

async function scrollToTop(page, locator) {
  await locator.evaluate((element, clearance) => window.scrollTo({ top: element.getBoundingClientRect().top + window.scrollY - clearance }), TOPBAR_CLEARANCE_PX);
  await page.waitForTimeout(SETTLE_MS);
}

function editorHtml(text) {
  const escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/^(#.*)$/gm, '<span class="h">$1</span>');
  return `<style>${EDITOR_STYLE}</style><div class="window"><div class="tab">${ADR_PATH}</div><pre>${escaped}</pre></div>`;
}

/** Step 1: the ADR appears section by section, then is saved into the repository. */
async function writeAdr(page) {
  const sections = ADR.split(/\n(?=## )/);
  for (let count = 1; count <= sections.length; count += 1) {
    await page.setContent(editorHtml(sections.slice(0, count).join('\n')));
    await caption(page, '1 · Write an ADR in your repository, in plain Markdown with no template');
    await frame(page, count === sections.length ? STEP_FRAME_MS : TYPING_FRAME_MS);
  }
  mkdirSync(path.join(repoDir, path.dirname(ADR_PATH)), { recursive: true });
  writeFileSync(path.join(repoDir, ADR_PATH), ADR);
}

async function discover(page) {
  await page.goto(new URL('#architecture-log', base).href, { waitUntil: 'networkidle' });
  await page.waitForTimeout(SETTLE_MS);
  await page.getByRole('button', { name: 'Discover decisions' }).first().click();
  await page.getByRole('dialog', { name: 'Choose discovery mode' }).waitFor();
  await caption(page, '2 · Run Discover (this sample uses fixture-tuned mock extraction; your repo can use a local model)');
  await frame(page, STEP_FRAME_MS);
  await page.getByRole('button', { name: 'Run discovery' }).click();
  await page.locator('.scan-summary').waitFor({ timeout: 60000 });
  await page.waitForTimeout(SETTLE_MS);
}

async function architectureLog(page) {
  const entry = page.locator('.log-entry').filter({ has: page.locator('h3', { hasText: DECISION }) });
  await entry.waitFor();
  await scrollToTop(page, entry);
  await caption(page, '3 · The decision, its alternative, and why it lost, each cited to the ADR');
  await frame(page, STEP_FRAME_MS);
}

async function map(page) {
  await page.getByRole('button', { name: 'Architecture', exact: true }).click();
  await page.getByRole('button', { name: 'Open map full screen' }).click();
  await page.waitForTimeout(SETTLE_MS);
  // Drag the canvas left, as a reader would, so the new card clears the details panel that opens on the right.
  await page.mouse.move(PAN_FROM.x, PAN_FROM.y);
  await page.mouse.down();
  await page.mouse.move(PAN_FROM.x - PAN_LEFT_PX, PAN_FROM.y, { steps: 10 });
  await page.mouse.up();
  await page.waitForTimeout(SETTLE_MS);
  await page.locator('.react-flow__node', { hasText: DECISION }).first().click();
  await page.waitForTimeout(SETTLE_MS);
  await caption(page, '4 · It joins the system map: Restaurant Service queues notifications on Amazon SQS');
  await frame(page, STEP_FRAME_MS);
}

async function whatIf(page) {
  await page.locator('.graph-selection-summary.is-open').getByRole('button', { name: 'Close component details' }).click();
  await page.getByRole('button', { name: 'What-if', exact: true }).click();
  await page.getByRole('button', { name: `Jump to ${DECISION} options` }).click();
  await settled(page);
  await page.locator('.decision-select').filter({ has: page.locator('.decision-name', { hasText: DECISION }) }).getByRole('button', { name: new RegExp(`^${ALTERNATIVE}`) }).click();
  await settled(page);
  await page.getByRole('button', { name: `Jump to ${DECISION} options` }).click();
  await settled(page);
  await caption(page, '5 · Preview the alternative: the map switches to Kafka; the repository keeps SQS');
  await frame(page, LAST_FRAME_MS);
}

function encodeGif() {
  const gif = GIFEncoder();
  for (const { png, delay } of frames) {
    const { data, width, height } = PNG.sync.read(png);
    const palette = quantize(data, 256);
    gif.writeFrame(applyPalette(data, palette), width, height, { palette, delay, repeat: 0 });
  }
  gif.finish();
  writeFileSync(outFile, gif.bytes());
}

// PLAYWRIGHT_CHROMIUM lets you reuse an already-installed Chromium binary.
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined });
const errors = [];
try {
  const ctx = await browser.newContext({ viewport: VIEWPORT, reducedMotion: 'reduce' });
  await ctx.addInitScript(() => { try { localStorage.setItem('switchplinth-theme', 'light'); } catch { /* about:blank editor frames have no storage. */ } });
  const page = await ctx.newPage();
  page.on('pageerror', (error) => errors.push(error.message));
  await writeAdr(page);
  await discover(page);
  await architectureLog(page);
  await map(page);
  await whatIf(page);
} finally {
  await browser.close();
}
encodeGif();
console.log(JSON.stringify({ outFile, frames: frames.length, seconds: frames.reduce((sum, item) => sum + item.delay, 0) / 1000, errors }));
