// Browser regression check for cross-page navigation buttons. It drives a running frontend whose backend serves the
// fixtures/food-delivery repository and exits non-zero on the first failed assertion.
// Usage: BASE_URL=http://127.0.0.1:4339 node e2e/navigation.check.mjs
// Playwright is not a project dependency; set PLAYWRIGHT_MODULE to an installed `playwright` package directory when
// `playwright` does not resolve from this folder.
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? 'playwright')
const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const FOCUS_TIMEOUT_MS = 10000

async function openPage(browser, hash) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const errors = []
  page.on('pageerror', (error) => errors.push(String(error)))
  await page.goto(`${BASE}/#${hash}`, { waitUntil: 'networkidle' })
  await page.locator('.react-flow__node').first().waitFor({ state: 'attached' })
  return { page, errors }
}

function heading(page) {
  return page.locator('.page-heading h1').innerText()
}

function viewportTransform(page) {
  return page.locator('.react-flow__viewport').first().getAttribute('style')
}

/** The selected option title per decision, read from the What-if option buttons (rendered even while hidden). */
function pressedOptions(page) {
  return page.locator('.decision-select').evaluateAll((sections) => sections.map((section) => section.querySelector('button[aria-pressed="true"] span')?.textContent ?? null))
}

/** Waits until the picker marks `title` as the current location, its active option has focus, and the smooth scroll has
 * brought every option of that decision inside the What-if panel. */
function waitForDecisionFocused(page, title) {
  return page.waitForFunction((title) => {
    const picker = [...document.querySelectorAll('button[aria-current="location"]')].some((button) => button.getAttribute('aria-label') === `Jump to ${title} options`)
    const section = [...document.querySelectorAll('.decision-select')].find((element) => [...(element.querySelector('.decision-name')?.childNodes ?? [])].some((node) => node.nodeType === Node.TEXT_NODE && node.textContent === title))
    if (!picker || !section) return false
    const active = document.activeElement
    if (!section.contains(active) || active.getAttribute('aria-pressed') !== 'true') return false
    const panel = section.closest('.scenario-panel').getBoundingClientRect()
    const options = [...section.querySelectorAll('button[aria-pressed]')].map((button) => button.getBoundingClientRect())
    return options.length > 0 && options.every((box) => box.height > 0 && box.top >= Math.max(panel.top, 0) && box.bottom <= Math.min(panel.bottom, window.innerHeight))
  }, title, { timeout: FOCUS_TIMEOUT_MS })
}

async function assertDecisionFocused(page, title) {
  assert.equal(await page.getByRole('button', { name: `Jump to ${title} options` }).getAttribute('aria-current'), 'location', `${title} is the current picker entry`)
  const section = page.locator('.decision-select').filter({ has: page.locator('.decision-name', { hasText: title }) })
  const visible = await section.evaluate((element) => {
    const panel = element.closest('.scenario-panel').getBoundingClientRect()
    const options = [...element.querySelectorAll('button[aria-pressed]')].map((button) => button.getBoundingClientRect())
    return options.length > 0 && options.every((box) => box.height > 0 && box.top >= Math.max(panel.top, 0) && box.bottom <= Math.min(panel.bottom, window.innerHeight))
  })
  assert.ok(visible, `${title} options are scrolled into view`)
  const focused = await section.evaluate((element) => element.contains(document.activeElement) && document.activeElement.getAttribute('aria-pressed') === 'true')
  assert.ok(focused, `the active ${title} option has focus`)
}

async function checkExploreFullScenario(browser) {
  const { page, errors } = await openPage(browser, 'architecture')
  const transformBefore = await viewportTransform(page)
  await page.getByRole('button', { name: 'Architecture log', exact: true }).click()
  const selectionsBefore = await pressedOptions(page)
  assert.ok(selectionsBefore.length > 0 && selectionsBefore.every(Boolean), 'every decision has a selected option')
  const entries = page.locator('.log-entry')
  const title = await entries.last().locator('h3').evaluate((element) => element.firstChild.textContent)
  await entries.last().getByRole('button', { name: /Explore full scenario/ }).click()
  await waitForDecisionFocused(page, title)
  assert.equal(await heading(page), 'Architecture', 'Explore full scenario opens the Architecture map')
  assert.ok(await page.locator('.react-flow').first().isVisible(), 'the system map is visible')
  assert.ok(await page.getByRole('button', { name: 'Close What-if panel' }).isVisible(), 'the What-if panel is open')
  await assertDecisionFocused(page, title)
  assert.equal(await viewportTransform(page), transformBefore, 'the map viewport is unchanged')
  assert.deepEqual(await pressedOptions(page), selectionsBefore, 'scenario selections are unchanged')
  assert.deepEqual(errors, [])
  await page.close()
}

const CHECKS = { 'explore-full-scenario': checkExploreFullScenario }

const browser = await chromium.launch()
let failed = false
try {
  for (const [name, check] of Object.entries(CHECKS)) {
    try {
      await check(browser)
      console.log(`ok ${name}`)
    } catch (error) {
      failed = true
      console.log(`FAIL ${name}: ${error.message}`)
    }
  }
} finally {
  await browser.close()
}
process.exit(failed ? 1 : 0)
