/**
 * Single source of truth for branding and public URLs.
 *
 * A rename edits this file only: `name`, plus the repository slug in
 * `repoUrl` and `basePath`.
 * Page titles, the OG image, llms.txt, JSON-LD, and the docs header read
 * from here; docs Markdown avoids the name.
 *
 * `siteUrl` is the production origin used for canonical URLs, the sitemap,
 * and Open Graph tags. CI may override it with the SITE_URL environment
 * variable, and `basePath` with BASE_PATH (use BASE_PATH=/ for a domain root,
 * e.g. Cloudflare Pages).
 */
export const site = {
  name: 'Switchplinth',
  tagline: 'Flip an architecture decision. See what moves.',
  description:
    'A local-first tool that reads the ADRs, RFCs, and design docs already in your repository, extracts decisions with cited evidence, and lets you explore what-if scenarios.',
  repoUrl: 'https://github.com/bcmyguest/switchplinth',
  /** GitHub Pages project site by default; a custom domain is undecided. */
  siteUrl: 'https://bcmyguest.github.io',
  basePath: '/switchplinth/',
  /** One-command demo shown in the Try-it section. `ready: false` labels it a placeholder. */
  demo: {
    ready: true,
    command: './scripts/demo.sh',
  },
} as const;

export type SiteConfig = typeof site;
