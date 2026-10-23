// Records the README workflow GIF: write an ADR, run Discover, read it in the Architecture log, find it on the map,
// and preview its alternative in What-if.
// Usage: node scripts/workflow-gif.mjs <appUrl> <repoDir> <outFile>
//
// <appUrl> is the frontend serving a fresh bootstrap of fixtures/food-delivery, and <repoDir> is that same repository
// on disk (for scripts/demo.sh, ~/.cache/switchplinth-demo/food-delivery). The script writes the ADR below into
// <repoDir>/decisions/ and runs Discover, so use a disposable copy. Every step after the editor frames is the running
// app; the editor frames show the file being written. Captions are drawn on top of the page.
// Set WORKFLOW_CONNECTION to a saved model connection ID (for example a local Lemonade server) to extract with that
// model and add two steps: a grounded Explore question and a model-proposed change to the ADR's alternative, which
// is discarded, not saved. Without it, Discover uses the sample's fixture-tuned mock extraction.
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
// A model may word titles differently from the mock, so the new decision and its card are found by this pattern.
const DECISION_PATTERN = /notification/i;
const CONNECTION_ID = process.env.WORKFLOW_CONNECTION ?? '';
const EXTRACTION_TIMEOUT_MS = 30 * 60 * 1000;
const QUESTION = 'Why did we choose Amazon SQS for restaurant notifications?';
const CHANGE_REQUEST = 'Add a dead-letter topic that the support dashboard reads';
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
  const dialog = page.getByRole('dialog', { name: 'Choose discovery mode' });
  await dialog.waitFor();
  if (CONNECTION_ID) {
    const connection = (await (await fetch(new URL('/api/v1/connections', base))).json()).find((item) => item.id === CONNECTION_ID);
    if (!connection) throw new Error(`No model connection ${CONNECTION_ID}`);
    await dialog.getByText('Configured model', { exact: true }).click();
    await dialog.getByLabel('Model connection').selectOption(CONNECTION_ID);
    await caption(page, `2 · Run Discover with a local model (${connection.name}: ${connection.model})`);
  } else {
    await caption(page, '2 · Run Discover (this sample uses fixture-tuned mock extraction; your repo can use a local model)');
  }
  await frame(page, STEP_FRAME_MS);
  await page.getByRole('button', { name: 'Run discovery' }).click();
  await page.locator('.scan-summary').waitFor({ timeout: CONNECTION_ID ? EXTRACTION_TIMEOUT_MS : 60000 });
  await page.waitForTimeout(SETTLE_MS);
}

async function architectureLog(page) {
  const entry = page.locator('.log-entry').filter({ has: page.locator('h3', { hasText: DECISION_PATTERN }) });
  await entry.waitFor();
  await scrollToTop(page, entry);
  await caption(page, `3 · ${CONNECTION_ID ? 'The model found the decision: its' : 'The decision,'} alternative and why it lost, each cited to the ADR`);
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
  await page.locator('.react-flow__node', { hasText: DECISION_PATTERN }).first().click();
  await page.waitForTimeout(SETTLE_MS);
  await caption(page, '4 · It joins the system map, with the reason and the alternative one click away');
  await frame(page, STEP_FRAME_MS);
}

/** Title of the new decision as extracted, for the What-if picker and the propose target. */
async function decisionTitle(page) {
  const titles = await page.locator('.decision-select .decision-name').evaluateAll((names) => names.map((name) => name.childNodes[1]?.textContent ?? ''));
  const title = titles.find((item) => DECISION_PATTERN.test(item));
  if (!title) throw new Error(`No decision matches ${DECISION_PATTERN}: ${titles.join(', ')}`);
  return title;
}

async function whatIf(page) {
  await page.locator('.graph-selection-summary.is-open').getByRole('button', { name: 'Close component details' }).click();
  await page.getByRole('button', { name: 'What-if', exact: true }).click();
  const title = await decisionTitle(page);
  await page.getByRole('button', { name: `Jump to ${title} options` }).click();
  await settled(page);
  await page.locator('.decision-select').filter({ has: page.locator('.decision-name', { hasText: title }) }).locator('button[aria-pressed="false"]').first().click();
  await settled(page);
  await page.getByRole('button', { name: `Jump to ${title} options` }).click();
  await settled(page);
  await caption(page, '5 · Preview the alternative: the map switches; the repository keeps its choice');
  await frame(page, CONNECTION_ID ? STEP_FRAME_MS : LAST_FRAME_MS);
  await page.getByRole('button', { name: 'Return to repository choices' }).click();
  await settled(page);
  return title;
}

/** Explore Ask is grounded search over cited passages; no model writes the answer. */
async function ask(page) {
  await page.getByRole('button', { name: 'Close What-if panel' }).click();
  await page.getByRole('button', { name: 'Exit full-screen map' }).click();
  await page.getByRole('button', { name: 'Explore', exact: true }).click();
  await page.getByRole('textbox').fill(QUESTION);
  await page.keyboard.press('Enter');
  const answer = page.locator('.answer-card').first();
  await answer.waitFor();
  await scrollToTop(page, answer);
  await caption(page, '6 · Ask why: the answer quotes the ADR passages it found');
  await frame(page, STEP_FRAME_MS);
}

/** Propose a delta sends the request to the model; the proposal is discarded, not saved. */
async function propose(page, title) {
  await page.getByRole('button', { name: 'Propose a delta' }).click();
  await page.getByLabel('Target decision').selectOption({ label: title });
  const options = await page.getByLabel('Target option').locator('option').allTextContents();
  const alternative = options.find((option) => !/amazon sqs/i.test(option)) ?? options[0];
  await page.getByLabel('Target option').selectOption({ label: alternative });
  await page.getByRole('textbox').fill(CHANGE_REQUEST);
  await page.keyboard.press('Enter');
  const proposal = page.locator('.proposal-card');
  await proposal.waitFor({ timeout: EXTRACTION_TIMEOUT_MS });
  await scrollToTop(page, proposal);
  await caption(page, `7 · Ask the model to change the ${alternative} option: it proposes a typed delta you review before applying`);
  await frame(page, LAST_FRAME_MS);
  await proposal.getByRole('button', { name: 'Discard' }).click();
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
  const title = await whatIf(page);
  if (CONNECTION_ID) {
    await ask(page);
    await propose(page, title);
  }
} finally {
  await browser.close();
}
encodeGif();
console.log(JSON.stringify({ outFile, frames: frames.length, seconds: frames.reduce((sum, item) => sum + item.delay, 0) / 1000, errors }));
