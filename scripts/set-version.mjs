// Sets the release version in pyproject.toml. Usage: node scripts/set-version.mjs 1.2.3
import { readFileSync, writeFileSync } from 'node:fs';

const version = process.argv[2];
if (!/^\d+\.\d+\.\d+$/.test(version ?? '')) {
  console.error('usage: node scripts/set-version.mjs <major.minor.patch>');
  process.exit(1);
}
const path = 'pyproject.toml';
writeFileSync(path, readFileSync(path, 'utf8').replace(/^(version\s*=\s*")[^"]*"/m, `$1${version}"`));
console.log(`version set to ${version}`);
