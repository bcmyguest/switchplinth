// Browser regression check for the What-if "Changes vs previous choice" and "Affected downstream" sections. It drives a
// running frontend whose backend serves a fresh bootstrap of fixtures/food-delivery and exits non-zero on the first failed
// assertion. What-if choices are temporary previews, so the check writes nothing to the repository.
// Usage: BASE_URL=http://127.0.0.1:4378 node e2e/scenario-diff.check.mjs
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
const PAYMENT_RETRY = 'Payment retry delivery'
const ORDER_SERVICE = 'Order Service'
const THEME_KEY = 'switchplinth-theme'
const VIEWPORTS = [{ width: 1440, height: 900 }, { width: 375, height: 812 }]
const READY_TIMEOUT_MS = 15000
/** Per page: the option title each decision showed after the last checked switch. */
const pressedTitlesCache = new Map()

async function openArchitecture(browser, viewport, theme) {
  const page = await browser.newPage({ viewport })
  await page.addInitScript(([key, value]) => window.localStorage.setItem(key, value), [THEME_KEY, theme])
  const errors = []
  page.on('pageerror', (error) => errors.push(String(error)))
  await page.goto(`${BASE}/#architecture`, { waitUntil: 'networkidle' })
  await page.locator('.react-flow__node').first().waitFor({ state: 'attached' })
  return { page, errors }
}

function canvasGeometry(page) {
  return page.locator('.graph-canvas').first().evaluate((element) => {
    const box = element.getBoundingClientRect()
    return { x: box.x, width: box.width, transform: element.querySelector('.react-flow__viewport')?.getAttribute('style') ?? '' }
  })
}

function whatIfButton(page) {
  return page.locator('.graph-tools').getByRole('button', { name: 'What-if' })
}

function decisionSection(page, title) {
  return page.locator('.scenario-panel .decision-select').filter({ has: page.locator('.decision-name', { hasText: title }) })
}

/** Full selection map shown by the What-if option buttons, keyed by decision title. */
async function pressedTitles(page) {
  return page.locator('.scenario-panel .decision-select').evaluateAll((sections) => Object.fromEntries(sections.map((section) => [
    [...section.querySelector('.decision-name').childNodes].filter((node) => node.nodeType === Node.TEXT_NODE).map((node) => node.textContent).join(''),
    section.querySelector('button[aria-pressed="true"] span')?.textContent ?? null,
  ])))
}

async function api(page, route, body) {
  const response = body === undefined ? await page.request.get(`${BASE}/api/v1${route}`) : await page.request.post(`${BASE}/api/v1${route}`, { data: body })
  assert.ok(response.ok(), `${route} answered ${response.status()}`)
  return response.json()
}

/** Waits until the previous-choice section shows a settled comparison of `switched` (one "Decision: A → B" line). */
async function waitForComparison(page, switched) {
  await page.waitForFunction((expected) => {
    const section = document.querySelector('section[aria-label="Changes vs previous choice"]')
    if (!section || section.getAttribute('aria-busy') === 'true') return false
    const lines = [...section.querySelectorAll('ul[aria-label="Switched decisions"] > li')].map((item) => item.textContent)
    return JSON.stringify(lines) === JSON.stringify(expected)
  }, switched, { timeout: READY_TIMEOUT_MS })
}

function readList(page, label) {
  return page.locator(`section[aria-label="Changes vs previous choice"] ul[aria-label="${label} vs previous choice"] > li`).evaluateAll((items) => items.map((item) => `${item.dataset.change ?? ''}|${item.lastElementChild.textContent}`))
}

/** What the UI must list for `diff`, built from the API response alone. */
function expectedLists(diff, names) {
  const name = (id) => names.get(id) ?? id
  const relationship = (item) => `${name(item.from)} → ${name(item.to)} (${item.kind.replaceAll('_', ' ')})`
  return {
    components: [...diff.entities.added.map((item) => `Added|${item.name}`), ...diff.entities.removed.map((item) => `Removed|${item.name}`)],
    relationships: [...diff.relationships.added.map((item) => `Added|${relationship(item)}`), ...diff.relationships.removed.map((item) => `Removed|${relationship(item)}`)],
    problems: [...diff.conflicts.appeared, ...diff.invalid_assumptions.appeared].length + [...diff.conflicts.disappeared, ...diff.invalid_assumptions.disappeared].length,
    decisions: diff.affected_decisions.map((item) => item.title),
  }
}

/** Switches `decisionTitle` to `optionTitle` and checks the rendered comparison against the page's own diff request and an
 * independent API call with the same selections. Returns the diff. */
async function switchAndCompare(page, graph, decisionTitle, optionTitle) {
  const decision = graph.decisions.find((item) => item.title === decisionTitle)
  const before = decision.options.find((option) => option.title === (pressedTitlesCache.get(page)?.[decisionTitle]))
  const diffRequest = page.waitForRequest((request) => request.url().endsWith('/scenarios/diff') && request.method() === 'POST')
  await decisionSection(page, decisionTitle).locator('button[aria-pressed]', { hasText: optionTitle }).click()
  const body = (await diffRequest).postDataJSON()
  const option = decision.options.find((item) => item.title === optionTitle)
  assert.equal(body.after_selections[decision.id], option.id, 'the diff request compares against the new choice')
  if (before) assert.equal(body.before_selections[decision.id], before.id, 'the diff request starts from the previous choice')
  const diff = await api(page, '/scenarios/diff', body)
  const switched = diff.selection_changes.map((change) => {
    const changed = graph.decisions.find((item) => item.id === change.decision_id)
    const title = (id) => changed.options.find((item) => item.id === id)?.title ?? id
    return `${changed.title}: ${title(change.before_option)} → ${title(change.after_option)}`
  })
  assert.deepEqual(switched, [`${decisionTitle}: ${before?.title} → ${optionTitle}`], 'exactly one decision switched')
  await waitForComparison(page, switched)
  const resolvedBefore = await api(page, '/scenarios/resolve', { selections: body.before_selections })
  const resolvedAfter = await api(page, '/scenarios/resolve', { selections: body.after_selections })
  const names = new Map([...graph.entities, ...resolvedBefore.graph.entities, ...resolvedAfter.graph.entities].map((entity) => [entity.id, entity.name]))
  const expected = expectedLists(diff, names)
  assert.deepEqual(await readList(page, 'Components'), expected.components, 'component changes match the diff endpoint')
  assert.deepEqual(await readList(page, 'Relationships'), expected.relationships, 'relationship changes match the diff endpoint')
  assert.equal((await readList(page, 'Conflicts and assumptions')).length, expected.problems, 'conflict and assumption changes match the diff endpoint')
  const decisions = await page.locator('section[aria-label="Changes vs previous choice"] ul[aria-label="Decisions affected vs previous choice"] > li > span:first-child').allTextContents()
  assert.deepEqual(decisions, expected.decisions, 'affected decisions match the diff endpoint')
  pressedTitlesCache.set(page, await pressedTitles(page))
  return diff
}

async function downstreamStatus(page, dependentName) {
  return page.locator(`section[aria-label="Affected downstream"] li[data-dependent="${dependentName}"]`).evaluateAll((items) => items.map((item) => item.dataset.status))
}

async function assertNoOverflow(page, label) {
  const overflow = await page.evaluate(() => {
    const root = document.scrollingElement
    const panel = document.querySelector('.scenario-panel')
    const sections = [...document.querySelectorAll('section[aria-label="Changes vs previous choice"], section[aria-label="Affected downstream"]')]
    return {
      document: root.scrollWidth - root.clientWidth,
      panel: panel ? panel.scrollWidth - panel.clientWidth : 0,
      sections: sections.map((section) => section.scrollWidth - section.clientWidth),
      escaping: sections.flatMap((section) => [...section.querySelectorAll('*')].filter((element) => element.getBoundingClientRect().right > section.getBoundingClientRect().right + 1).map((element) => element.textContent.slice(0, 40))),
    }
  })
  assert.ok(overflow.document <= 0, `${label}: no document horizontal overflow (${overflow.document}px)`)
  assert.ok(overflow.panel <= 0, `${label}: no What-if panel horizontal overflow (${overflow.panel}px)`)
  assert.ok(overflow.sections.every((value) => value <= 0), `${label}: no section horizontal overflow`)
  assert.deepEqual(overflow.escaping, [], `${label}: no element extends past its section`)
}

async function screenshot(page, name) {
  if (!SCREENSHOT_DIR) return
  await page.locator('section[aria-label="Changes vs previous choice"]').scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, `${name}-changes.png`) })
  await page.locator('section[aria-label="Affected downstream"]').scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, `${name}-downstream.png`) })
}

/** Opens What-if, checks canvas geometry and Escape/focus, then switches Kafka -> SQS -> Kafka and a second decision. */
async function checkPreviousChoiceDiff(browser, viewport, theme) {
  const label = `${viewport.width}x${viewport.height} ${theme}`
  const { page, errors } = await openArchitecture(browser, viewport, theme)
  const graph = await api(page, '/graph')
  const geometry = await canvasGeometry(page)

  await whatIfButton(page).click()
  await page.getByRole('button', { name: 'Close What-if panel' }).waitFor()
  assert.deepEqual(await canvasGeometry(page), geometry, `${label}: opening What-if leaves the canvas position and width unchanged`)
  await page.keyboard.press('Escape')
  await page.waitForFunction(() => document.activeElement?.textContent?.trim() === 'What-if')
  assert.equal(await page.getByRole('button', { name: 'Close What-if panel' }).count(), 0, `${label}: Escape closes What-if`)
  await whatIfButton(page).click()
  await page.getByRole('button', { name: 'Close What-if panel' }).waitFor()
  assert.match(await page.locator('section[aria-label="Changes vs previous choice"]').innerText(), /Switch an option/, `${label}: the section starts idle`)
  assert.match(await page.locator('section[aria-label="Scenario comparison with repository choices"]').innerText(), /Compared with repository choices/, `${label}: the repository outcome names its baseline`)
  pressedTitlesCache.set(page, await pressedTitles(page))

  const toSqs = await switchAndCompare(page, graph, EVENT_DELIVERY, 'Amazon SQS')
  assert.deepEqual(await downstreamStatus(page, ORDER_SERVICE), ['Rewired'], `${label}: Order Service is rewired after Kafka -> SQS`)
  assert.ok(toSqs.impact.items.some((item) => item.dependents.some((dependent) => dependent.name === ORDER_SERVICE && dependent.rewired)), 'the API reports Order Service rewired')
  assert.match(await page.locator('section[aria-label="Affected downstream"]').innerText(), /rewired” is a heuristic/, `${label}: the limits line is shown`)
  await assertNoOverflow(page, `${label} after Kafka -> SQS`)
  await screenshot(page, `${viewport.width}-${theme}-kafka-to-sqs`)
  assert.deepEqual(await canvasGeometry(page).then(({ x, width }) => ({ x, width })), { x: geometry.x, width: geometry.width }, `${label}: the comparison leaves the canvas position and width unchanged`)

  await switchAndCompare(page, graph, EVENT_DELIVERY, 'Apache Kafka')
  assert.deepEqual(await downstreamStatus(page, ORDER_SERVICE), ['Rewired'], `${label}: Order Service is rewired after SQS -> Kafka`)
  await switchAndCompare(page, graph, PAYMENT_RETRY, 'Apache Kafka')
  await assertNoOverflow(page, `${label} after the second decision`)
  await screenshot(page, `${viewport.width}-${theme}-payment-retry`)
  await switchAndCompare(page, graph, PAYMENT_RETRY, 'Amazon SQS')

  await page.keyboard.press('Escape')
  await page.waitForFunction(() => document.activeElement?.textContent?.trim() === 'What-if')
  assert.deepEqual(errors, [], `${label}: no page errors`)
  await page.close()
}

/** A slow diff for an earlier switch must not replace the diff of a later one. */
async function checkStaleDiffIgnored(browser) {
  const { page, errors } = await openArchitecture(browser, VIEWPORTS[0], 'light')
  const graph = await api(page, '/graph')
  await whatIfButton(page).click()
  await page.getByRole('button', { name: 'Close What-if panel' }).waitFor()
  let delayed = false
  let releaseDelayed
  const delayedDone = new Promise((resolve) => { releaseDelayed = resolve })
  await page.route('**/api/v1/scenarios/diff', async (route) => {
    if (!delayed) {
      delayed = true
      await new Promise((resolve) => setTimeout(resolve, 2500))
      await route.continue().catch(() => {})
      releaseDelayed()
      return
    }
    await route.continue()
  })
  const decision = decisionSection(page, EVENT_DELIVERY)
  await decision.locator('button[aria-pressed]', { hasText: 'Amazon SQS' }).click()
  await page.waitForFunction(() => document.querySelector('.scenario-panel button[aria-pressed="true"]:not(:disabled)'))
  await decision.locator('button[aria-pressed="false"]', { hasText: 'Apache Kafka' }).click()
  await waitForComparison(page, [`${EVENT_DELIVERY}: Amazon SQS → Apache Kafka`])
  await delayedDone
  await page.waitForTimeout(300)
  const lines = await page.locator('ul[aria-label="Switched decisions"] > li').allTextContents()
  assert.deepEqual(lines, [`${EVENT_DELIVERY}: Amazon SQS → Apache Kafka`], 'the late Kafka -> SQS diff did not replace the later one')
  assert.ok(graph.decisions.length > 0)
  assert.deepEqual(errors, [])
  await page.close()
}

const CHECKS = {
  ...Object.fromEntries(VIEWPORTS.flatMap((viewport) => ['light', 'dark'].map((theme) => [`previous-choice-diff ${viewport.width}x${viewport.height} ${theme}`, (browser) => checkPreviousChoiceDiff(browser, viewport, theme)]))),
  'stale-diff-ignored': checkStaleDiffIgnored,
}

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
