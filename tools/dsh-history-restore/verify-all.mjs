/**
 * Audit every DSH session directory the way the jsonl persistence backend resolves it:
 * pick the numerically highest canonical generation and read its header with the
 * harness's own format catalog. Reports any session that would still render empty.
 *
 * Usage: node verify-all.mjs [--harness <dir>]
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, basename } from 'node:path';
import zlib from 'node:zlib';

const HARNESS = process.argv.includes('--harness')
  ? process.argv[process.argv.indexOf('--harness') + 1]
  : 'C:/Users/Admin1/AppData/Roaming/DeepSeek Harness/harness-versions/f9c7d9178383adfd';
const ROOT = process.env.DSH_SESSIONS
  ?? join(process.env.APPDATA, 'DeepSeek Harness', 'dsh-home', 'sessions');

const CATALOG = `file:///${HARNESS}/packages/session/session-format-catalog/lib/index.js`;
const mod = await import(CATALOG);
const catalog = mod.sessionFormatCatalog ?? mod.default?.sessionFormatCatalog ?? mod.default;

const CANONICAL = /^session(?:\.v([1-9][0-9]*))?\.jsonl\.zstd$/u;
const ZSTD_MAGIC = 4247762216;

function firstFramePlaintext(path) {
  const buf = readFileSync(path);
  if (buf.readUInt32LE(0) !== ZSTD_MAGIC) throw new Error('not a zstd frame');
  const descriptor = buf.readUInt8(4);
  const contentSizeFlag = descriptor >>> 6;
  const singleSegment = (descriptor & 32) !== 0;
  const checksum = (descriptor & 4) !== 0;
  const dictionaryFlag = descriptor & 3;
  const dictionaryBytes = dictionaryFlag === 3 ? 4 : dictionaryFlag;
  const contentSizeBytes = contentSizeFlag === 0 ? (singleSegment ? 1 : 0) : 1 << contentSizeFlag;
  let offset = 5 + (singleSegment ? 0 : 1) + dictionaryBytes + contentSizeBytes;
  for (;;) {
    const blockHeader = buf.readUIntLE(offset, 3);
    offset += 3;
    const blockType = (blockHeader >>> 1) & 3;
    const lastBlock = (blockHeader & 1) !== 0;
    offset += blockType === 1 ? 1 : blockHeader >>> 3;
    if (lastBlock) break;
  }
  if (checksum) offset += 4;
  return zlib.zstdDecompressSync(buf.subarray(0, offset)).toString('utf8');
}

const report = [];
for (const project of readdirSync(ROOT, { withFileTypes: true }).filter((e) => e.isDirectory())) {
  for (const session of readdirSync(join(ROOT, project.name), { withFileTypes: true }).filter((e) => e.isDirectory())) {
    const dir = join(ROOT, project.name, session.name);
    const generations = [];
    for (const entry of readdirSync(dir)) {
      const match = CANONICAL.exec(entry);
      if (match !== null) generations.push({ name: entry, version: match[1] === undefined ? 0 : Number(match[1]) });
    }
    if (generations.length === 0) {
      report.push({ project: project.name, session: session.name, generation: '-', status: 'NO-ARTIFACT' });
      continue;
    }
    const latest = generations.sort((a, b) => b.version - a.version)[0];
    let status;
    try {
      const line = firstFramePlaintext(join(dir, latest.name));
      const header = JSON.parse(line);
      const read = catalog.readHeader(header);
      status = read.status === 'current' ? `ok v${header.version}` : `UNREADABLE (${read.status})`;
      if (header.id !== session.name) status += ' ID-MISMATCH';
    } catch (error) {
      status = `ERROR ${error.message}`;
    }
    report.push({
      project: project.name,
      session: session.name,
      generation: `v${latest.version}/${generations.length}`,
      status,
    });
  }
}

for (const row of report) console.log(`${row.status.padEnd(22)} ${row.generation.padEnd(7)} ${row.project}/${row.session}`);
const bad = report.filter((r) => !r.status.startsWith('ok'));
console.log(`\ntotal=${report.length} readable=${report.length - bad.length} problematic=${bad.length}`);
for (const row of bad) console.log(`PROBLEM: ${row.project}/${row.session} -> ${row.status}`);
