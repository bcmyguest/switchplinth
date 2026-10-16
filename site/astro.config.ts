import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import tailwindcss from '@tailwindcss/vite';
import { site as brand } from './src/site.config';

// SITE_URL / BASE_PATH let one build target either host:
//   GitHub Pages project site (default, from site.config.ts): SITE_URL=https://bcmyguest.github.io BASE_PATH=/switchplinth/
//   Cloudflare Pages / custom domain: SITE_URL=https://your.domain BASE_PATH=/
const siteUrl = process.env.SITE_URL || brand.siteUrl;
const basePath = process.env.BASE_PATH || brand.basePath;

export default defineConfig({
  site: siteUrl,
  base: basePath,
  trailingSlash: 'ignore',
  // The roadmap page used to be the limits page; keep the old URL working.
  // Astro does not prefix redirect targets with the base path.
  redirects: { '/docs/limits': `${basePath.replace(/\/$/, '')}/docs/roadmap/` },
  integrations: [
    starlight({
      title: brand.name,
      description: brand.description,
      favicon: '/favicon.svg',
      customCss: ['@fontsource/dm-sans/400.css', '@fontsource/dm-sans/600.css', './src/styles/tokens.css', './src/styles/docs.css'],
      social: [{ icon: 'github', label: 'Source repository', href: brand.repoUrl }],
      head: [
        { tag: 'meta', attrs: { property: 'og:image', content: new URL(`${basePath.replace(/\/$/, '')}/og.png`, siteUrl).href } },
        { tag: 'meta', attrs: { name: 'twitter:card', content: 'summary_large_image' } },
        { tag: 'meta', attrs: { name: 'twitter:image', content: new URL(`${basePath.replace(/\/$/, '')}/og.png`, siteUrl).href } },
      ],
      sidebar: [
        {
          label: 'Start',
          items: [
            { label: 'Getting started', slug: 'docs/getting-started' },
            { label: 'Up next', slug: 'docs/roadmap' },
          ],
        },
        {
          label: 'Learn',
          items: [
            { label: 'Concepts', slug: 'docs/concepts' },
            { label: 'Portable format', slug: 'docs/portable-format' },
          ],
        },
        {
          label: 'Integrate',
          items: [
            { label: 'Model providers', slug: 'docs/providers' },
            { label: 'MCP tools', slug: 'docs/mcp' },
          ],
        },
        { label: 'FAQ', slug: 'docs/faq' },
      ],
      routeMiddleware: './src/routeData.ts',
      lastUpdated: false,
      pagination: true,
    }),
  ],
  vite: {
    plugins: [tailwindcss()],
  },
});
