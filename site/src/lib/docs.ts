import { getCollection, type CollectionEntry } from 'astro:content';

/** Docs pages in sidebar order (matches astro.config.ts). */
export const DOC_ORDER = ['getting-started', 'roadmap', 'concepts', 'portable-format', 'providers', 'mcp', 'faq'];

export async function orderedDocs(): Promise<CollectionEntry<'docs'>[]> {
  const docs = (await getCollection('docs')).filter((d) => d.id.startsWith('docs/'));
  const rank = (d: CollectionEntry<'docs'>) => DOC_ORDER.indexOf(d.id.replace(/^docs\//, ''));
  return docs.sort((a, b) => rank(a) - rank(b));
}

/**
 * Starlight admonitions (:::note[Title]) become plain Markdown blockquotes, and
 * relative doc links (../slug/) become absolute when `docUrl` is given.
 */
export function plainMarkdown(body: string, docUrl?: (slug: string) => string): string {
  return body
    .replace(/\]\(\.\.\/([\w-]+)\/\)/g, (m, slug: string) => (docUrl ? `](${docUrl(slug)})` : m))
    .replace(/^:::(\w+)(?:\[([^\]]*)\])?\n([\s\S]*?)^:::\n?/gm, (_m, kind: string, label: string | undefined, text: string) => {
      const heading = label ?? kind[0].toUpperCase() + kind.slice(1);
      return text.trim().split('\n').map((l, i) => (i === 0 ? `> **${heading}:** ${l}` : `> ${l}`)).join('\n') + '\n';
    })
    .trim();
}
