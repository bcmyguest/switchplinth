// Browser integration check for the primary task flows against a live backend. It drives a running frontend whose
// backend serves a fresh, disposable bootstrap of fixtures/food-delivery and exits non-zero on the first failed assertion.
// It writes to that repository: one claim review and its undo, and one named scenario under `.decision/scenarios/`.
// Usage: BASE_URL=http://127.0.0.1:5173 node e2e/use-cases.check.mjs
// Playwright is not a project dependency; set PLAYWRIGHT_MODULE to an installed `playwright` package directory when
// `playwright` does not resolve from this folder. Set SCREENSHOT_DIR to save screenshots.
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? 'playwright')
const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const SCREENSHOT_DIR = process.env.SCREENSHOT_DIR
const EVENT_DELIVERY = 'Event delivery for food orders'
const ORDER_DATA = 'RFC: durable order data'
const PAYMENT_RETRY = 'Payment retry delivery'
const KAFKA_STREAM = 'Order event stream (Apache Kafka)'
const SQS_STREAM = 'Order event stream (Amazon SQS)'
const REVIEWED_CLAIM = 'Apache Kafka provides capability Replay'
const DESKTOP = { width: 1440, height: 900 }
const MOBILE = { width: 375, height: 812 }
const PAGES = ['architecture', 'architecture-log', 'progress', 'facts', 'scenarios', 'explore']
const READY_TIMEOUT_MS = 15000

async function openPage(browser, hash, viewport = DESKTOP) {
  const page = await browser.newPage({ viewport })
  const errors = []
  const writes = []
  page.on('pageerror', (error) => errors.push(String(error)))
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('request', (request) => { if (request.url().includes('/api/') && request.method() !== 'GET') writes.push(`${request.method()} ${new URL(request.url()).pathname}`) })
  await page.goto(`${BASE}/#${hash}`, { waitUntil: 'networkidle' })
  await page.locator('.react-flow__node').first().waitFor({ state: 'attached', timeout: READY_TIMEOUT_MS })
  return { page, errors, writes }
}

async function capture(page, name) {
  if (SCREENSHOT_DIR) await page.screenshot({ path: path.join(SCREENSHOT_DIR, `${name}.png`) })
}

function mapNodeNames(page) {
  return page.locator('.react-flow__node .arch-node').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('title') ?? node.textContent))
}

/** The pressed option title per decision in the What-if panel. */
function pressedOptions(page) {
  return page.locator('.decision-select').evaluateAll((sections) => Object.fromEntries(sections.map((section) => [section.querySelector('.decision-name')?.childNodes[1]?.textContent ?? '', section.querySelector('button[aria-pressed="true"] span')?.textContent ?? null])))
}

/** Waits until the resolve and both comparisons have finished. */
async function waitForResolved(page) {
  await page.waitForFunction(() => !document.querySelector('.decision-select button[aria-pressed]:disabled') && !document.querySelector('.scenario-list-status') && !/Comparing with/.test(document.querySelector('.scenario-panel')?.textContent ?? ''), null, { timeout: READY_TIMEOUT_MS })
}

async function choose(page, decision, option) {
  await page.locator('.decision-select').filter({ has: page.locator('.decision-name', { hasText: decision }) }).getByRole('button', { name: new RegExp(`^${option}`) }).click()
  await waitForResolved(page)
}

function historyLabels(page) {
  return page.locator('.scenario-history-item').evaluateAll((items) => items.map((item) => `${item.getAttribute('aria-pressed') === 'true' ? '*' : ''}${item.textContent}`))
}

async function assertNoHorizontalOverflow(page, label) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  assert.ok(overflow <= 1, `${label}: no horizontal overflow (${overflow}px)`)
}

async function checkComponentEvidence(browser) {
  const { page, errors } = await openPage(browser, 'architecture')
  await page.locator('.react-flow__node', { hasText: 'Payment retry queue' }).first().click()
  const detail = page.locator('.graph-selection-summary.is-open')
  await detail.waitFor()
  assert.match(await detail.innerText(), /Payment retry delivery[\s\S]*managed retries/i, 'component details show the deciding rationale')
  await detail.getByRole('button', { name: /Open source passage|Open passage/ }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Source evidence' })
  await dialog.waitFor()
  assert.match(await dialog.innerText(), /payment-retries\.md/, 'the passage dialog shows the cited source')
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'hidden' })
  assert.ok(await detail.isVisible(), 'Escape closes the source dialog and keeps component details open')
  await page.keyboard.press('Escape')
  await detail.waitFor({ state: 'hidden' })
  assert.deepEqual(errors, [])
  await page.close()
  console.log('ok component-evidence')
}

async function checkMapWhatIf(browser) {
  const { page, errors, writes } = await openPage(browser, 'architecture')
  assert.ok((await mapNodeNames(page)).some((name) => name.includes(KAFKA_STREAM)), 'the map starts with the Kafka order stream')
  await page.getByRole('button', { name: 'What-if', exact: true }).click()
  await page.getByRole('button', { name: 'Close What-if panel' }).waitFor()
  await choose(page, EVENT_DELIVERY, 'Amazon SQS')
  let names = await mapNodeNames(page)
  assert.ok(names.some((name) => name.includes(SQS_STREAM)) && !names.some((name) => name.includes(KAFKA_STREAM)), 'choosing SQS replaces the order stream on the map')
  assert.match(await page.locator('.scenario-sticky-summary').innerText(), /changes? · 1 decision affected vs repository choices/, 'the sticky summary counts the preview against the repository choices')
  await page.getByRole('heading', { name: 'Changes vs previous choice' }).or(page.getByText('Changes vs previous choice', { exact: true })).first().waitFor()
  await capture(page, 'map-what-if-sqs')
  await page.getByRole('button', { name: 'Return to repository choices' }).click()
  await waitForResolved(page)
  names = await mapNodeNames(page)
  assert.ok(names.some((name) => name.includes(KAFKA_STREAM)), 'returning to repository choices restores the Kafka stream')
  const history = await historyLabels(page)
  assert.equal(history.filter((label) => label.includes('Original choices')).length, 1, `the base appears once in history: ${history}`)
  assert.equal(new Set(history.map((label) => label.replace('*', ''))).size, history.length, 'history entries are unique')
  assert.ok(history[0].startsWith('*'), 'the base entry is marked current after returning')
  assert.ok(writes.every((write) => /\/scenarios\/(resolve|diff)$|\/entities\//.test(write)), `temporary choices write nothing: ${writes}`)
  assert.deepEqual(errors, [], 'no React or page errors')
  await page.close()
  console.log('ok map-what-if')
}

async function checkHistoryAndSavedScenario(browser) {
  const { page, errors, writes } = await openPage(browser, 'scenarios')
  await choose(page, EVENT_DELIVERY, 'Amazon SQS')
  await choose(page, ORDER_DATA, 'Redis')
  const combined = await pressedOptions(page)
  await choose(page, ORDER_DATA, 'PostgreSQL')
  const sqsOnly = await pressedOptions(page)
  const results = page.locator('.scenario-results')
  const box = await results.boundingBox()
  assert.ok(box && box.y < DESKTOP.height && box.x > DESKTOP.width / 2, 'the Scenarios page shows results beside the options on desktop')
  await capture(page, 'scenarios-results-column')
  await page.locator('.scenario-history-item', { hasText: 'Redis' }).click()
  await waitForResolved(page)
  assert.deepEqual(await pressedOptions(page), combined, 'a history entry reapplies its exact combination')
  await page.locator('.scenario-history-item').filter({ hasNotText: 'Redis' }).filter({ hasNotText: 'Original choices' }).click()
  await waitForResolved(page)
  assert.deepEqual(await pressedOptions(page), sqsOnly, 'switching back reapplies the other combination')
  assert.ok(!writes.some((write) => write.endsWith('/api/v1/scenarios')), 'exploring saves no scenario')

  await page.locator('.scenario-history-item', { hasText: 'Redis' }).click()
  await waitForResolved(page)
  const name = `Use-case check ${Date.now()}`
  await page.getByRole('button', { name: /Save or reopen a named scenario/ }).click()
  await page.getByRole('button', { name: 'Save as named scenario' }).click()
  await page.getByLabel('Scenario name').fill(name)
  await page.getByRole('button', { name: 'Save scenario' }).click()
  await page.getByRole('button', { name: `Load scenario ${name}` }).waitFor({ timeout: READY_TIMEOUT_MS })
  assert.equal(writes.filter((write) => write.endsWith('/api/v1/scenarios')).length, 1, 'the named save writes exactly one scenario')
  assert.deepEqual(errors, [])
  await page.close()

  const reopened = await openPage(browser, 'scenarios')
  const baseline = await pressedOptions(reopened.page)
  assert.notDeepEqual(baseline, combined, 'a reload starts from the repository choices')
  await reopened.page.getByRole('button', { name: /Save or reopen a named scenario/ }).click()
  await reopened.page.getByRole('button', { name: `Load scenario ${name}` }).click()
  await waitForResolved(reopened.page)
  assert.deepEqual(await pressedOptions(reopened.page), combined, 'the saved scenario reopens with its choices')
  assert.match(await reopened.page.locator('.scenario-panel').innerText(), new RegExp(`Loaded scenario “${name}”`))
  assert.deepEqual(reopened.errors, [])
  await reopened.page.close()
  console.log('ok history-and-saved-scenario')
}

async function checkFactsReviewAndUndo(browser) {
  const { page, errors } = await openPage(browser, 'facts')
  const pending = async () => Number(await page.locator('#review-section h2 span').innerText())
  const before = await pending()
  await page.getByRole('button', { name: `Confirm claim: ${REVIEWED_CLAIM}` }).click()
  await page.waitForFunction((count) => Number(document.querySelector('#review-section h2 span')?.textContent) === count - 1, before, { timeout: READY_TIMEOUT_MS })
  const undo = page.getByRole('button', { name: new RegExp(`^Undo: .*${REVIEWED_CLAIM}`) }).and(page.locator(':enabled')).first()
  await undo.waitFor({ timeout: READY_TIMEOUT_MS })
  await undo.click()
  await page.waitForFunction((count) => Number(document.querySelector('#review-section h2 span')?.textContent) === count, before, { timeout: READY_TIMEOUT_MS })
  assert.equal(await pending(), before, 'undo restores the pending count')
  assert.deepEqual(errors, [])
  await page.close()
  console.log('ok facts-review-undo')
}

async function checkExplore(browser) {
  const { page, errors } = await openPage(browser, 'explore')
  const suggestion = page.locator('.suggestions button').first()
  const question = await suggestion.innerText()
  assert.match(question, /^Why .+\?$/, 'suggestions are questions about the current choices')
  const search = page.waitForRequest((request) => request.url().endsWith('/api/v1/search'))
  await suggestion.click()
  await search
  await page.locator('.answer-card').waitFor({ timeout: READY_TIMEOUT_MS })
  assert.match(await page.locator('.answer-label').innerText(), /GROUNDED/, `"${question}" gets a grounded answer`)
  await page.getByRole('textbox').fill('Which decisions mention replay?')
  await page.keyboard.press('Enter')
  await page.waitForFunction(() => document.querySelector('.answer-card p')?.textContent?.includes('Evidence found'), null, { timeout: READY_TIMEOUT_MS })
  assert.ok(await page.locator('.answer-source').count() > 0, 'a punctuated question still finds passages')
  await page.locator('.answer-source').first().click()
  await page.getByRole('dialog', { name: 'Source evidence' }).waitFor()
  await page.keyboard.press('Escape')
  assert.deepEqual(errors, [])
  await page.close()
  console.log('ok explore')
}

async function checkCanvasEditTarget(browser) {
  const { page, errors, writes } = await openPage(browser, 'architecture')
  await page.locator('.react-flow__node', { hasText: 'Payment retry queue' }).first().click()
  await page.locator('.graph-selection-summary.is-open').getByRole('button', { name: 'Close component details' }).click()
  await page.getByRole('button', { name: 'Remove selected' }).click()
  const notice = page.locator('.canvas-edit-notice')
  await notice.waitFor()
  assert.match(await notice.innerText(), new RegExp(`“${PAYMENT_RETRY}” → “Amazon SQS”`), 'a canvas edit lands in the decision that created the component')
  await page.locator('.delta-editor').getByRole('button', { name: 'Close option editor' }).click()
  assert.ok(!writes.some((write) => write.includes('/delta')), 'staging an edit writes nothing')
  assert.deepEqual(errors, [])
  await page.close()
  console.log('ok canvas-edit-target')
}

async function checkMobilePages(browser) {
  for (const hash of PAGES) {
    const { page, errors } = await openPage(browser, hash, MOBILE)
    await assertNoHorizontalOverflow(page, `${hash} at 375px`)
    await capture(page, `mobile-${hash}`)
    assert.deepEqual(errors, [], `${hash} renders without errors`)
    await page.close()
  }
  console.log('ok mobile-pages')
}

const browser = await chromium.launch()
try {
  await checkComponentEvidence(browser)
  await checkMapWhatIf(browser)
  await checkHistoryAndSavedScenario(browser)
  await checkFactsReviewAndUndo(browser)
  await checkExplore(browser)
  await checkCanvasEditTarget(browser)
  await checkMobilePages(browser)
} finally {
  await browser.close()
}
