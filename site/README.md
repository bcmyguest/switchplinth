# Switchplinth website

Static marketing and docs site for [Switchplinth](https://github.com/bcmyguest/switchplinth) (Apache-2.0), a local-first tool that maps architecture decisions from repository Markdown.

## Stack

- [Astro](https://astro.build) 7 with [Starlight](https://starlight.astro.build) for `/docs/`.
- Tailwind CSS 4 on the landing page, with shadcn-style `Button`, `Card`, and `Badge` components in `src/components/ui/`.
- Colors come from `src/theme.yml`, a copy of the app's `frontend/theme.yml`. `scripts/gen-theme.mjs` turns it into `src/styles/tokens.css` for both the landing page and Starlight.

**Deviation: no React islands.** The landing hero is SVG and CSS with a 1 KB script, so the landing page ships no framework runtime. Add `@astrojs/react` when a component needs client-side state that plain scripts cannot handle.

## Naming and URLs

`src/site.config.ts` holds every brand-dependent value. A rename edits that file only: `name` (page titles, header, OG image, `llms.txt`, JSON-LD) and the repository slug in `repoUrl` and `basePath`. Docs Markdown never names the product; the MCP page cites the `switchplinth` CLI command (upcoming release).

| Field | Current value | Status |
| --- | --- | --- |
| `name` | `Switchplinth` | decided |
| `repoUrl`, `license` | `https://github.com/bcmyguest/switchplinth`, `Apache-2.0` | public |
| `siteUrl` + `basePath` | `https://bcmyguest.github.io` + `/switchplinth/` | host: GitHub Pages; custom domain undecided |
| `demo` | `./scripts/demo.sh`, `ready: true` | set `ready: false` to label the Try-it command a placeholder |

`SITE_URL` and `BASE_PATH` environment variables override the origin and base path at build time.

## Commands

```sh
pnpm install
pnpm dev            # local dev server
pnpm build          # theme tokens -> astro build -> privacy check
pnpm check:privacy  # re-run the dist/ privacy scan
pnpm preview        # serve dist/
PLAYWRIGHT_CHROMIUM=/path/to/chrome pnpm screenshots http://localhost:4321/switchplinth/ out/
PLAYWRIGHT_CHROMIUM=/path/to/chrome pnpm hero-loop http://localhost:4321/switchplinth/ out/hero-loop light
PLAYWRIGHT_CHROMIUM=/path/to/chrome pnpm app-screenshots http://localhost:3000/ ../docs/assets   # running app on a fresh food-delivery sample
PLAYWRIGHT_CHROMIUM=/path/to/chrome pnpm workflow-gif http://localhost:3000/ ~/.cache/switchplinth-demo/food-delivery ../docs/assets/workflow.gif
PLAYWRIGHT_CHROMIUM=/path/to/chrome pnpm export-architecture ../adrs/docs/assets   # after pnpm build
```

## Hero loop

`scripts/hero-loop.mjs` renders a 6-second, 1200px-wide loop of the landing hero's Kafka/SQS illustration for posts. The repository README uses images of the running product instead: `scripts/app-screenshots.mjs` drives the app on a fresh `fixtures/food-delivery` bootstrap and writes `hero-loop.gif` (the real map and What-if panel switching order events Kafka → SQS), `whatif-map.png`, `architecture-log.png`, `review-log.png`, and `why-search.png` at 1280×800 in the light theme. It confirms two aliases for the review-log shot, so point it at a disposable copy (`scripts/demo.sh --reset` gives a fresh one). `scripts/workflow-gif.mjs` records `workflow.gif`: it shows an ADR being written, saves that file into the repository directory it is given, runs a mock Discover in the app, and captures the Architecture log entry, the new map card, and a What-if preview of the ADR's alternative, with a caption per step. The ADR names only technologies the mock extractor knows. Run it on a fresh sample too; with `scripts/demo.sh` the backend writes root-owned files, so reset with `--reset`. It pauses and seeks the CSS animations frame by frame, writes a frame-diffed GIF with `gifenc`, and replays the frames on a canvas through the browser's `MediaRecorder` to produce WebM and, where Chromium supports it, MP4. It needs no ffmpeg. The sheet's title block shows `name` from `site.config.ts`, so re-render after a rename.

## Pipeline diagram

`/docs/architecture/` ("How it works") draws the Markdown-to-decisions pipeline with `src/components/docs/PipelineDiagram.astro`: a wide sheet when the figure is at least 680px wide and a stacked sheet below that, colored by the same tokens as the hero. `scripts/export-architecture.mjs` copies both sheets from `dist/` into standalone SVGs (light tokens, dark under `prefers-color-scheme`) and light PNGs: the wide sheet at 1600px, the stacked sheet at 720px. Extra arguments are directories that receive copies, such as the product repository's `docs/assets/`. In `llms-full.txt` and `/docs/architecture.md`, `plainMarkdown()` replaces the component with the wide PNG.

## Privacy check

`scripts/check-privacy.mjs` fails the build when `dist/` contains home-directory paths, private or link-local IPv4 addresses, email addresses, or LAN hostnames. Pagefind's bundled translator-credit emails are exempt from the email pattern only. Add personal literals (names, user names, machine names) one per line to `.privacy-deny.local`, which Git ignores, or pass them in `PRIVACY_DENY` as a comma-separated list. In CI, store that list in a secret.

## Generated files

| Path | Source |
| --- | --- |
| `/og.png` | `src/pages/og.png.ts` (Satori + resvg at build time) |
| `/robots.txt`, `/sitemap-index.xml` | `src/pages/robots.txt.ts`, Starlight's sitemap |
| `/llms.txt`, `/llms-full.txt` | `src/pages/llms*.txt.ts` |
| `/docs/<page>.md` | `src/pages/docs/[slug].md.ts`: plain Markdown of each docs page |
| `/diagrams/architecture-pipeline{,-vertical}.{svg,png}` | `scripts/export-architecture.mjs`, from `src/components/docs/PipelineDiagram.astro` in the built `/docs/architecture/` page. Committed in `public/diagrams/`; re-run after editing the diagram |

## Deploy (not executed)

The chosen host is GitHub Pages. Cloudflare Pages settings stay documented as an alternative.

**GitHub Pages:** `.github/workflows/pages.yml` builds on pushes to `main`. `actions/configure-pages` supplies `SITE_URL` and `BASE_PATH`. Enable Pages with "Source: GitHub Actions".

**Cloudflare Pages:**

| Setting | Value |
| --- | --- |
| Build command | `pnpm build` |
| Output directory | `dist` |
| Environment | `SITE_URL=https://<your-domain>`, `BASE_PATH=/`, `NODE_VERSION=24` |

`public/_headers` sets immutable caching for `/_astro/*` on Cloudflare; GitHub Pages ignores it.

## Up next page

`/docs/roadmap/` ("Up next") replaced the former limits page. `astro.config.ts` redirects `/docs/limits/` there, prefixed with the base path.

## Content rules

Every docs statement comes from the product repository's README and `docs/`. Unverified behavior carries a label. Do not add features, numbers, testimonials, logos, or user counts that the product repository does not record.
