// Page names and their location hashes; the hash is the only navigation state the browser keeps.

export const PAGE_HASHES = { Architecture: '#architecture', 'Architecture log': '#architecture-log', Progress: '#progress', Facts: '#facts', Scenarios: '#scenarios', Explore: '#explore' } as const
const PAGE_BY_HASH = Object.fromEntries(Object.entries(PAGE_HASHES).map(([page, hash]) => [hash, page])) as Record<string, Page>

export type Page = keyof typeof PAGE_HASHES

export function pageFromLocation(): Page {
  return PAGE_BY_HASH[window.location.hash] ?? 'Architecture'
}
