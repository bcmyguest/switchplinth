// Fails (exit 1) if the built site leaks personal or environment details.
// Usage: node scripts/check-privacy.mjs [dir=dist]
//
// Built-in patterns: home-directory paths, private/LAN IPv4 addresses, email
// addresses, and LAN-style hostnames. Add personal literals (names, user
// names, machine names) one per line to .privacy-deny.local (gitignored), or
// pass them comma-separated in PRIVACY_DENY. Keep those values out of Git.
import { readdirSync, readFileSync, existsSync, statSync } from 'node:fs';
import { join, extname, relative } from 'node:path';

const dir = process.argv[2] ?? 'dist';
const TEXT = new Set(['.html', '.txt', '.xml', '.js', '.mjs', '.css', '.json', '.md', '.svg', '.webmanifest', '']);

const patterns = [
  { name: 'home path', re: /\/home\/[A-Za-z0-9._-]+/g },
  { name: 'macOS user path', re: /\/Users\/[A-Za-z0-9._-]+/g },
  { name: 'Windows user path', re: /[A-Za-z]:\\Users\\[A-Za-z0-9._-]+/g },
  { name: 'private IPv4 (10/8)', re: /\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b/g },
  { name: 'private IPv4 (192.168/16)', re: /\b192\.168\.\d{1,3}\.\d{1,3}\b/g },
  { name: 'private IPv4 (172.16/12)', re: /\b172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b/g },
  { name: 'link-local IPv4', re: /\b169\.254\.\d{1,3}\.\d{1,3}\b/g },
  { name: 'email address', re: /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}/g },
  { name: 'LAN hostname', re: /\b[A-Za-z0-9-]+\.(local|lan|home\.arpa|localdomain)\b/g },
];

// Pagefind (Starlight search) bundles its translators' credit emails. Those
// files skip only the email pattern; every other check still applies.
const EMAIL_EXEMPT = /(^|[\\/])(pagefind[\\/][^\\/]+\.js|_astro[\\/]ui-core\.[^\\/]+\.js)$/;

const deny = [
  ...(existsSync('.privacy-deny.local') ? readFileSync('.privacy-deny.local', 'utf8').split('\n') : []),
  ...(process.env.PRIVACY_DENY ?? '').split(','),
]
  .map((s) => s.trim())
  .filter((s) => s && !s.startsWith('#'));

function* walk(d) {
  for (const name of readdirSync(d)) {
    const p = join(d, name);
    if (statSync(p).isDirectory()) yield* walk(p);
    else if (TEXT.has(extname(name).toLowerCase())) yield p;
  }
}

if (!existsSync(dir)) {
  console.error(`check-privacy: ${dir} does not exist; build first.`);
  process.exit(2);
}

const hits = [];
let files = 0;
for (const file of walk(dir)) {
  files++;
  const text = readFileSync(file, 'utf8');
  for (const { name, re } of patterns) {
    if (name === 'email address' && EMAIL_EXEMPT.test(file)) continue;
    for (const m of text.matchAll(re)) hits.push({ file, name, match: m[0] });
  }
  const lower = text.toLowerCase();
  for (const literal of deny) {
    if (lower.includes(literal.toLowerCase())) hits.push({ file, name: 'deny-list literal', match: '<redacted>' });
  }
}

if (hits.length) {
  console.error(`check-privacy: ${hits.length} finding(s) in ${files} files:`);
  for (const h of hits.slice(0, 50)) console.error(`  ${relative('.', h.file)}  [${h.name}]  ${h.match}`);
  process.exit(1);
}
console.log(`check-privacy: OK (${files} text files, ${patterns.length} patterns, ${deny.length} deny-list literals)`);
