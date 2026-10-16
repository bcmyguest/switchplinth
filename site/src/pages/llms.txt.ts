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

Source: ${brand.repoUrl} (${brand.license})

## Docs

${links}

## Works today

- Setup wizard (\`switchplinth setup\`): repository or sample, first scan, MCP registration with Claude Code, Claude Desktop, Cursor, or VS Code.
- One-command Docker demo of the food-delivery sample (\`./scripts/demo.sh\`).
- Deterministic mock extraction and local OpenAI-compatible model extraction; a local Qwen3.8 model with reasoning off found all 7 sample decisions.
- Review log with undo, layered architecture map, What-if previews, grounded "why" answers with cited passages.
- Scenario diffs between any two selection maps, with relationship-based downstream impact (API and MCP \`diff_scenarios\`).
- Input receipts on graph, scenario, search, and diff results; repeat a call and compare \`receipt.digest\` to detect stale results.
- Five read-only MCP tools over streamable HTTP (loopback, unauthenticated) and stdio: list_decisions, search_decisions, inspect_architecture, inspect_entity, diff_scenarios.

## Up next

- Test hosted providers (OpenAI, Anthropic); untested today.
- Measure extraction recall on more repositories.
- Extraction beyond the sample, whose demo uses fixture-tuned mock rules.
- Authentication for remote API and MCP access; loopback-only today.
- More source formats beyond Markdown.
- Conflict detection beyond same-ID writes.
- Scenario rename, update, and delete.

## Optional

- [Full docs in one file](${absolute('llms-full.txt', site)})
`;
  return new Response(text, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
};
