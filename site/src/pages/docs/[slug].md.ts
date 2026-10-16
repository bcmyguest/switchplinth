import type { APIRoute, GetStaticPaths } from 'astro';
import { orderedDocs, plainMarkdown } from '../../lib/docs';
import { absolute } from "../../lib/url";

// Clean Markdown copy of each docs page for agents: /docs/<slug>.md
export const getStaticPaths: GetStaticPaths = async () =>
  (await orderedDocs()).map((d) => ({ params: { slug: d.id.replace(/^docs\//, '') }, props: { d } }));

export const GET: APIRoute = ({ props, site }) => {
  const { d } = props as { d: Awaited<ReturnType<typeof orderedDocs>>[number] };
  const text = `# ${d.data.title}\n\n${d.data.description ?? ''}\n\n${plainMarkdown(d.body ?? '', (s) => absolute(`docs/${s}/`, site))}\n`;
  return new Response(text, { headers: { 'Content-Type': 'text/markdown; charset=utf-8' } });
};
