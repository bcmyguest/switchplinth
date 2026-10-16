import type { APIRoute } from 'astro';
import { site as brand } from '../site.config';
import { absolute } from '../lib/url';
import { orderedDocs, plainMarkdown } from '../lib/docs';

export const GET: APIRoute = async ({ site }) => {
  const docs = await orderedDocs();
  const sections = docs.map(
    (d) => `# ${d.data.title}\n\nSource: ${absolute(`${d.id}/`, site)}\n\n${plainMarkdown(d.body ?? '', (s) => absolute(`docs/${s}/`, site))}`,
  );
  const text = `# ${brand.name}: full documentation\n\n> ${brand.description}\n\n${sections.join('\n\n---\n\n')}\n`;
  return new Response(text, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
};
