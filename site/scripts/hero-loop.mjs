// Renders a seamless loop of the hero's Kafka <-> SQS switch.
// Usage: node scripts/hero-loop.mjs <pageUrl> <outPrefix> [light|dark]
//
// Frames are captured deterministically: CSS transitions and animations are
// paused and seeked through the Web Animations API, so the loop has no
// dropped frames. Outputs <outPrefix>.gif (gifenc, frame-diffed) and, by
// replaying the frames on a canvas through MediaRecorder, <outPrefix>.webm
// and <outPrefix>.mp4 when the browser supports those containers.
import { chromium } from 'playwright';
import { writeFileSync } from 'node:fs';
import { PNG } from 'pngjs';
import gifenc from 'gifenc';

const { GIFEncoder, quantize, applyPalette } = gifenc;
const [pageUrl, out = 'hero-loop', theme = 'light'] = process.argv.slice(2);
const WIDTH = 1200; // output pixels
const CSS_WIDTH = 720; // layout width; deviceScaleFactor scales it to WIDTH
const FPS = 12;
const HALF = 3; // seconds per state; the loop is 2 * HALF
const frames = FPS * HALF * 2;

const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined });
const ctx = await browser.newContext({ viewport: { width: CSS_WIDTH, height: 900 }, deviceScaleFactor: WIDTH / CSS_WIDTH, reducedMotion: 'no-preference' });
await ctx.addInitScript((t) => localStorage.setItem('starlight-theme', t), theme);
const page = await ctx.newPage();
await page.goto(pageUrl, { waitUntil: 'networkidle' });

// Isolate the diagram and legend at CSS_WIDTH px; stop the page's auto-cycle.
const height = await page.evaluate((w) => {
  const fig = document.querySelector('.hero-map');
  const surface = fig.querySelector('.map-surface');
  const clone = fig.cloneNode(false); // drops the original's event listeners and timer target
  clone.append(surface);
  document.body.replaceChildren(clone);
  Object.assign(document.body.style, { margin: '0', padding: '0', background: 'var(--c-canvas)' });
  Object.assign(clone.style, { width: `${w}px`, margin: '0' });
  surface.style.borderRadius = '0';
  return Math.ceil(surface.getBoundingClientRect().height);
}, CSS_WIDTH);
await page.setViewportSize({ width: CSS_WIDTH, height });

// Switch option at t=0 (to kafka) and t=HALF (to sqs); seek all animations to t.
async function renderAt(t) {
  await page.evaluate(
    ({ t, half }) => {
      const fig = document.querySelector('.hero-map');
      const state = t < half ? 'kafka' : 'sqs';
      const since = (t < half ? t : t - half) * 1000;
      // Start every frame from the opposite steady state, then switch, so transitions restart.
      fig.dataset.option = state === 'kafka' ? 'sqs' : 'kafka';
      document.getAnimations().forEach((a) => a.cancel());
      void fig.getBoundingClientRect();
      fig.dataset.option = state;
      void fig.getBoundingClientRect();
      for (const a of document.getAnimations()) {
        a.pause();
        a.currentTime = a instanceof CSSTransition ? since : t * 1000;
      }
    },
    { t, half: HALF },
  );
  return page.screenshot({ type: 'png' });
}

const pngs = [];
for (let i = 0; i < frames; i++) pngs.push(await renderAt(i / FPS));
// HERO_FRAMES_DIR=dir keeps the PNG frames for inspection.
if (process.env.HERO_FRAMES_DIR) pngs.forEach((b, i) => writeFileSync(`${process.env.HERO_FRAMES_DIR}/frame-${String(i).padStart(3, '0')}.png`, b));

// GIF: one shared palette, unchanged pixels encoded as transparent.
const decoded = pngs.map((b) => PNG.sync.read(b));
const { width, height: h } = decoded[0];
const sample = new Uint8Array(width * h * 4 * 2);
sample.set(decoded[0].data, 0);
sample.set(decoded[FPS * HALF + FPS].data, width * h * 4);
const palette = quantize(sample, 255);
const TRANSPARENT = palette.length;
const fullPalette = [...palette, [0, 0, 0]];
const gif = GIFEncoder();
let prev = null;
for (const img of decoded) {
  const index = applyPalette(img.data, palette);
  if (prev) {
    for (let p = 0; p < index.length; p++) if (index[p] === prev[p]) index[p] = TRANSPARENT;
  }
  gif.writeFrame(index, width, h, {
    palette: prev ? undefined : fullPalette,
    delay: Math.round(1000 / FPS),
    transparent: !!prev,
    transparentIndex: TRANSPARENT,
    dispose: 1,
    repeat: 0,
  });
  prev = applyPalette(img.data, palette);
}
gif.finish();
writeFileSync(`${out}.gif`, gif.bytes());

// Video: replay the frames on a canvas in real time and record it.
const videoPage = await ctx.newPage();
await videoPage.setContent('<canvas></canvas>');
const urls = pngs.map((b) => `data:image/png;base64,${b.toString('base64')}`);
for (const [ext, mime] of [
  ['webm', 'video/webm;codecs=vp9'],
  ['mp4', 'video/mp4;codecs=avc1'],
]) {
  const b64 = await videoPage.evaluate(
    async ({ urls, fps, mime, w, h }) => {
      if (!MediaRecorder.isTypeSupported(mime)) return null;
      const images = await Promise.all(
        urls.map((u) => new Promise((r) => { const i = new Image(); i.onload = () => r(i); i.src = u; })),
      );
      const canvas = document.querySelector('canvas');
      canvas.width = w;
      canvas.height = h;
      const g = canvas.getContext('2d');
      g.drawImage(images[0], 0, 0);
      const rec = new MediaRecorder(canvas.captureStream(fps), { mimeType: mime, videoBitsPerSecond: 1_500_000 });
      const chunks = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      const done = new Promise((r) => (rec.onstop = r));
      rec.start();
      for (const img of images) {
        g.drawImage(img, 0, 0);
        await new Promise((r) => setTimeout(r, 1000 / fps));
      }
      rec.stop();
      await done;
      const buf = new Uint8Array(await new Blob(chunks).arrayBuffer());
      let s = '';
      for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode(...buf.subarray(i, i + 0x8000));
      return btoa(s);
    },
    { urls, fps: FPS, mime, w: width, h },
  );
  if (b64) writeFileSync(`${out}.${ext}`, Buffer.from(b64, 'base64'));
  else console.log(`${ext}: ${mime} not supported by this browser; skipped`);
}

await browser.close();
console.log(JSON.stringify({ width, height: h, frames, fps: FPS, seconds: frames / FPS }));
