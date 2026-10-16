// Browser regression check for unmet capability requirements in the Architecture What-if overlay. It drives a running
// frontend whose backend serves a fresh bootstrap of fixtures/food-delivery, switches event transport Kafka -> SQS, and
// asserts that the replay requirement appears under "Changes vs previous choice" and "Compared with repository choices",
// then disappears again on the switch back. What-if choices are temporary previews, so nothing is written.
// Usage: BASE_URL=http://127.0.0.1:4378 node e2e/capability.check.mjs
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
const THEME_KEY = 'switchplinth-theme'
const VIEWPORTS = [{ width: 1440, height: 900 }, { width: 375, height: 812 }]
const TIMEOUT = { timeout: 15000 }

const CHANGES = 'section[aria-label="Changes vs previous choice"]'
const OUTCOME = 'section[aria-label="Scenario comparison with repository choices"]'

async function api(page, route, body) {
  const response = body === undefined ? await page.request.get(`${BASE}/api/v1${route}`) : await page.request.post(`${BASE}/api/v1${route}`, { data: body })
  assert.ok(response.ok(), `${route} answered ${response.status()}`)
  return response.json()
}

function rows(page, scope) {
  return page.locator(`${scope} [data-unmet-requirement]`).evaluateAll((items) => items.map((item) => `${item.dataset.change ?? ''}|${item.dataset.unmetRequirement}`))
}

async function run(browser, viewport, theme) {
  const label = `${viewport.width}x${viewport.height} ${theme}`
  const page = await browser.newPage({ viewport })
  const errors = []
  page.on('pageerror', (error) => errors.push(String(error)))
  await page.addInitScript(([key, value]) => window.localStorage.setItem(key, value), [THEME_KEY, theme])
  await page.goto(`${BASE}/#architecture`, { waitUntil: 'networkidle' })
  await page.locator('.react-flow__node').first().waitFor({ state: 'attached' })
  const graph = await api(page, '/graph')
  const decision = graph.decisions.find((item) => item.title === EVENT_DELIVERY)
  const sqs = decision.options.find((option) => option.title === 'Amazon SQS')
  const kafka = decision.options.find((option) => option.title === decision.options.find((option) => option.id === decision.selected_option)?.title)
  const base = Object.fromEntries(graph.decisions.map((item) => [item.id, item.selected_option]).filter(([, option]) => option))
  const after = { ...base, [decision.id]: sqs.id }

  await page.locator('.graph-tools').getByRole('button', { name: 'What-if' }).click()
  await page.getByRole('button', { name: 'Close What-if panel' }).waitFor()
  assert.equal(await page.locator(`${OUTCOME} [data-unmet-count]`).getAttribute('data-unmet-count'), '0', `${label}: the repository choices have no unmet requirement`)

  const expected = (await api(page, '/scenarios/diff', { before_selections: base, after_selections: after })).unmet_requirements.appeared
  assert.ok(expected.some((item) => item.requirer_name === 'Order Service' && /replay/i.test(item.capability_name)), 'the API reports the replay requirement')

  await page.locator('.scenario-panel .decision-select').filter({ has: page.locator('.decision-name', { hasText: EVENT_DELIVERY }) }).locator('button[aria-pressed]', { hasText: 'Amazon SQS' }).click()
  await page.waitForFunction((selector) => document.querySelector(selector)?.getAttribute('aria-busy') === 'false' && document.querySelector(`${selector} [data-unmet-requirement]`), CHANGES, TIMEOUT)

  const appeared = await rows(page, CHANGES)
  assert.equal(appeared.length, expected.length, `${label}: one row per appeared requirement`)
  assert.ok(appeared.every((row) => row.startsWith('Appeared|')), `${label}: rows are marked Appeared`)
  const replay = appeared.find((row) => row.includes('Order Service'))
  assert.match(replay ?? '', /Order Service needs .*replay.*: Amazon SQS lacks it/i, `${label}: the row names requirer, capability, and the lacking provider`)

  await page.locator(`${OUTCOME} [data-unmet-requirement]`).first().waitFor(TIMEOUT)
  assert.equal(await page.locator(`${OUTCOME} [data-unmet-count]`).getAttribute('data-unmet-count'), String(expected.length), `${label}: the repository comparison counts the unmet requirements`)
  assert.match(await page.locator('section[aria-label="Preview summary"]').innerText(), new RegExp(`${expected.length} unmet requirements`), `${label}: the outcome summary counts them`)
  assert.ok((await rows(page, OUTCOME)).some((row) => row.includes('Order Service')), `${label}: the repository comparison lists the replay row`)

  const overflow = await page.evaluate(() => document.scrollingElement.scrollWidth - document.scrollingElement.clientWidth)
  assert.ok(overflow <= 0, `${label}: no horizontal overflow`)
  if (SCREENSHOT_DIR) {
    await page.locator(`${CHANGES} [data-unmet-requirement]`).first().scrollIntoViewIfNeeded()
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, `${viewport.width}-${theme}-changes.png`) })
    await page.locator(`${OUTCOME} [data-unmet-count]`).scrollIntoViewIfNeeded()
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, `${viewport.width}-${theme}-outcome.png`) })
  }

  await page.locator('.scenario-panel .decision-select').filter({ has: page.locator('.decision-name', { hasText: EVENT_DELIVERY }) }).locator('button[aria-pressed]', { hasText: kafka.title }).click()
  await page.waitForFunction((selector) => document.querySelector(selector)?.getAttribute('aria-busy') === 'false' && [...document.querySelectorAll(`${selector} [data-unmet-requirement]`)].every((row) => row.dataset.change === 'Disappeared'), CHANGES, TIMEOUT)
  const disappeared = await rows(page, CHANGES)
  assert.ok(disappeared.some((row) => row.startsWith('Disappeared|') && row.includes('Order Service')), `${label}: switching back marks the requirement Disappeared`)
  assert.equal(await page.locator(`${OUTCOME} [data-unmet-count]`).getAttribute('data-unmet-count'), '0', `${label}: the repository comparison is clean again`)
  assert.deepEqual(errors, [], `${label}: no page errors`)
  await page.close()
  console.log(`ok ${label}`)
}

const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM })
try {
  for (const viewport of VIEWPORTS) for (const theme of ['light', 'dark']) await run(browser, viewport, theme)
} finally {
  await browser.close()
}
