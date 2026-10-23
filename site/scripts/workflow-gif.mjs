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
// A model may or may not attach a graph change to the decision (the ADR names no component IDs, and extraction never
// invents them), so the decision may have no card of its own. In model mode step 4 shows the chosen technology's card
// and steps 4 and 5 caption what the panel actually shows.
const MODEL_MAP_CARD = /Amazon SQS/;
const CONNECTION_ID = process.env.WORKFLOW_CONNECTION ?? '';
const EXTRACTION_TIMEOUT_MS = 30 * 60 * 1000;
const QUESTION = 'Why did we choose Amazon SQS for restaurant notifications?';
const CHANGE_REQUEST = 'Add a dead-letter topic that the support dashboard reads';
const PROPOSE_ATTEMPTS = 3;
const SETTLE_MS = 900;
const TYPING_FRAME_MS = 900;
const STEP_FRAME_MS = 3200;
const LAST_FRAME_MS = 4200;
const TOPBAR_CLEARANCE_PX = 72;
// An empty stretch of the full-screen canvas between the resource and technology rows at 1280x800.
const PAN_FROM = { x: 700, y: 620 };
const PAN_LEFT_PX = 300;
// Where model mode drags the chosen card: left of the details panel that opens on the right.
const CARD_TARGET = { x: 430, y: 450 };
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

/** Picks `option` in one of the app's Radix select comboboxes (they are buttons, not native selects). */
async function choose(page, label, option) {
  await page.getByRole('combobox', { name: label }).click();
  await page.getByRole('option', { name: option }).click();
}

/** The option names a combobox offers, read by opening and closing it. */
async function optionNames(page, label) {
  await page.getByRole('combobox', { name: label }).click();
  const names = await page.getByRole('option').allTextContents();
  await page.keyboard.press('Escape');
  return names;
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
    await choose(page, 'Model connection', new RegExp(`^${connection.name} · `));
    await caption(page, `2 · Run Discover with a local model (${connection.name}: ${connection.model})`);
  } else {
    await caption(page, '2 · Run Discover (this sample uses fixture-tuned mock extraction; your repo can use a local model)');
  }
  await frame(page, STEP_FRAME_MS);
  await page.getByRole('button', { name: 'Run discovery' }).click();
  await page.locator('.scan-summary').waitFor({ timeout: CONNECTION_ID ? EXTRACTION_TIMEOUT_MS : 60000 });
  // The result banner stays on every page; without Qdrant it also reports the unavailable vector index.
  await page.getByRole('button', { name: 'Dismiss discovery result' }).click();
  await page.waitForTimeout(SETTLE_MS);
}

async function architectureLog(page) {
  const entry = page.locator('.log-entry').filter({ has: page.locator('h3', { hasText: DECISION_PATTERN }) });
  await entry.waitFor();
  await scrollToTop(page, entry);
  await caption(page, `3 · ${CONNECTION_ID ? 'The model found the decision: its' : 'The decision,'} alternative and why it lost, each cited to the ADR`);
  await frame(page, STEP_FRAME_MS);
}

/** Drag the canvas from `from` by (dx, dy), as a reader would. */
async function pan(page, from, dx, dy) {
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(from.x + dx, from.y + dy, { steps: 10 });
  await page.mouse.up();
  await page.waitForTimeout(SETTLE_MS);
}

/** Model extraction lays the map out differently each run, so drag `card` to CARD_TARGET from an empty spot of the canvas. */
async function panToCard(page, card) {
  const box = await card.boundingBox();
  if (!box) throw new Error('Map card has no layout box');
  const from = await page.evaluate(() => {
    for (let y = 120; y < 740; y += 20) {
      for (let x = 20; x < 840; x += 20) {
        if (document.elementFromPoint(x, y)?.classList.contains('react-flow__pane')) return { x, y };
      }
    }
    return null;
  });
  if (!from) throw new Error('No empty canvas to drag the map from');
  await pan(page, from, CARD_TARGET.x - (box.x + box.width / 2), CARD_TARGET.y - (box.y + box.height / 2));
}

async function map(page) {
  await page.getByRole('button', { name: 'Architecture', exact: true }).click();
  await page.getByRole('button', { name: 'Open map full screen' }).click();
  await page.waitForTimeout(SETTLE_MS);
  const card = page.locator('.react-flow__node', { hasText: CONNECTION_ID ? MODEL_MAP_CARD : DECISION_PATTERN }).first();
  // Drag the canvas left, as a reader would, so the new card clears the details panel that opens on the right.
  if (CONNECTION_ID) await panToCard(page, card);
  else await pan(page, PAN_FROM, -PAN_LEFT_PX, 0);
  await card.click();
  await page.waitForTimeout(SETTLE_MS);
  const linked = CONNECTION_ID
    && DECISION_PATTERN.test(await page.locator('.graph-selection-summary.is-open').innerText());
  await caption(page, !CONNECTION_ID
    ? '4 · It joins the system map, with the reason and the alternative one click away'
    : linked
      ? '4 · On the map, Amazon SQS links the decision, with the reason and the alternative one click away'
      : '4 · Amazon SQS is on the map with its source passage; the model attached no graph change to the decision');
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
  const unchanged = CONNECTION_ID
    && /(^|\D)0 changes/.test(await page.locator('.scenario-panel').innerText());
  await caption(page, unchanged
    ? '5 · Preview the alternative: with no graph change extracted for it, the map stays as it is'
    : '5 · Preview the alternative: the map switches; the repository keeps its choice');
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
  await caption(page, '6 · Ask why: the answer quotes the repository passages it found');
  await frame(page, STEP_FRAME_MS);
}

/** Propose a delta sends the request to the model; the proposal is discarded, not saved. */
async function propose(page, title) {
  await page.getByRole('button', { name: 'Propose a delta' }).click();
  await choose(page, 'Target decision', title);
  const options = await optionNames(page, 'Target option');
  const alternative = options.find((option) => !/amazon sqs/i.test(option)) ?? options[0];
  await choose(page, 'Target option', alternative);
  const proposal = page.locator('.proposal-card');
  // A model's delta can fail validation (for example an unexpected field); ask again rather than record the error.
  // The failure card stays on screen during a retry, so each attempt waits for its own response.
  for (let attempt = 1; ; attempt += 1) {
    const response = page.waitForResponse((item) => item.url().includes('/api/v1/scenarios/propose'), { timeout: EXTRACTION_TIMEOUT_MS });
    await page.getByRole('textbox').fill(CHANGE_REQUEST);
    await page.keyboard.press('Enter');
    const result = await response;
    if (result.ok()) break;
    if (attempt === PROPOSE_ATTEMPTS) throw new Error(`No valid proposal after ${PROPOSE_ATTEMPTS} attempts: ${result.status()} ${await result.text()}`);
    await page.waitForTimeout(SETTLE_MS);
  }
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
