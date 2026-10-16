import type { APIRoute } from 'astro';
import { site as brand } from '../site.config';
import { absolute } from '../lib/url';
import { orderedDocs } from '../lib/docs';

export const GET: APIRoute = async ({ site }) => {
  const docs = await orderedDocs();
  const links = docs
    .map((d) => `- [${d.data.title}](${absolute(`${d.id}.md`, site)}): ${d.data.description ?? ''}`)
    .join('\n');
  const text = `# ${brand.name}

> ${brand.description} Canonical data is portable YAML in a .decision/ folder beside the Markdown; it runs locally with Docker Compose and exposes an MCP server on localhost.

Source: ${brand.repoUrl}

## Docs

${links}

## Limits

- Hosted-provider interoperability (OpenAI, Anthropic) is untested.
- Extraction recall and claim-level repeatability are unmeasured.
- The food-delivery sample uses deterministic mock extraction tuned to its own text; it demonstrates the decision and what-if model, not extraction quality.
- The API and MCP endpoint are unauthenticated and bind to loopback only.
- Markdown only; no code parsing or other formats.
- Schema decision/v1 only; no migration path exists yet.

## Optional

- [Full docs in one file](${absolute('llms-full.txt', site)})
`;
  return new Response(text, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
};
