# Switchplinth website

Static marketing and docs site for Switchplinth, a local-first tool that maps architecture decisions from repository Markdown.

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
| `repoUrl` | `https://github.com/bcmyguest/switchplinth` | repository rename in progress |
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
```

## Hero loop

`scripts/hero-loop.mjs` renders a 6-second, 1200px-wide loop of the hero's Kafka/SQS switch for READMEs and posts. It pauses and seeks the CSS animations frame by frame, writes a frame-diffed GIF with `gifenc`, and replays the frames on a canvas through the browser's `MediaRecorder` to produce WebM and, where Chromium supports it, MP4. It needs no ffmpeg. The sheet's title block shows `name` from `site.config.ts`, so re-render after a rename.

## Privacy check

`scripts/check-privacy.mjs` fails the build when `dist/` contains home-directory paths, private or link-local IPv4 addresses, email addresses, or LAN hostnames. Pagefind's bundled translator-credit emails are exempt from the email pattern only. Add personal literals (names, user names, machine names) one per line to `.privacy-deny.local`, which Git ignores, or pass them in `PRIVACY_DENY` as a comma-separated list. In CI, store that list in a secret.

## Generated files

| Path | Source |
| --- | --- |
| `/og.png` | `src/pages/og.png.ts` (Satori + resvg at build time) |
| `/robots.txt`, `/sitemap-index.xml` | `src/pages/robots.txt.ts`, Starlight's sitemap |
| `/llms.txt`, `/llms-full.txt` | `src/pages/llms*.txt.ts` |
| `/docs/<page>.md` | `src/pages/docs/[slug].md.ts`: plain Markdown of each docs page |

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

## Content rules

Every docs statement comes from the product repository's README and `docs/`. Unverified behavior carries a label. Do not add features, numbers, testimonials, logos, or user counts that the product repository does not record.
