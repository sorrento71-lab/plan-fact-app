/**
 * Convert a legacy (format v0) DSH session log into the current (v3) generation
 * artifact, using the harness's own format catalog for decoding + migration.
 *
 * Usage:
 *   node convert-v0.mjs --in <session.jsonl.zstd> --out <session.v3.jsonl.zstd> [--harness <dir>]
 *
 * The original file is never modified: only the new v3 generation is written.
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import zlib from 'node:zlib';

const HARNESS_DEFAULT = 'C:/Users/Admin1/AppData/Roaming/DeepSeek Harness/harness-versions/f9c7d9178383adfd';
const ZSTD_MAGIC = 4247762216;
const CHECKSUM_OPTIONS = { params: { [zlib.constants.ZSTD_c_checksumFlag]: 1 } };

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i === -1 ? fallback : process.argv[i + 1];
}
const inputPath = arg('in');
const outputPath = arg('out');
const HARNESS = arg('harness', HARNESS_DEFAULT);
if (!inputPath || !outputPath) {
  console.error('usage: node convert-v0.mjs --in <v0 file> --out <v3 file> [--harness <dir>]');
  process.exit(64);
}

/** Verbatim port of the backend's structural frame scanner (session-persistence-jsonl). */
function scanZstdFrames(buffer) {
  const frames = [];
  let offset = 0;
  while (offset < buffer.length) {
    const start = offset;
    if (buffer.length - offset < 4) return { frames, tornStart: start };
    if (buffer.readUInt32LE(offset) !== ZSTD_MAGIC) throw new Error(`invalid frame magic at byte ${offset}`);
    offset += 4;
    if (offset === buffer.length) return { frames, tornStart: start };
    const descriptor = buffer.readUInt8(offset);
    offset += 1;
    if ((descriptor & 24) !== 0) throw new Error(`reserved frame-header bit at byte ${offset - 1}`);
    const contentSizeFlag = descriptor >>> 6;
    const singleSegment = (descriptor & 32) !== 0;
    const checksum = (descriptor & 4) !== 0;
    const dictionaryFlag = descriptor & 3;
    const dictionaryBytes = dictionaryFlag === 3 ? 4 : dictionaryFlag;
    const contentSizeBytes = contentSizeFlag === 0 ? (singleSegment ? 1 : 0) : 1 << contentSizeFlag;
    const remainingHeaderBytes = (singleSegment ? 0 : 1) + dictionaryBytes + contentSizeBytes;
    if (buffer.length - offset < remainingHeaderBytes) return { frames, tornStart: start };
    offset += remainingHeaderBytes;
    for (;;) {
      if (buffer.length - offset < 3) return { frames, tornStart: start };
      const blockHeader = buffer.readUIntLE(offset, 3);
      offset += 3;
      if ((blockHeader >>> 1 & 3) === 3) throw new Error(`reserved block type at byte ${offset - 3}`);
      const payloadBytes = (blockHeader >>> 1 & 3) === 1 ? 1 : blockHeader >>> 3;
      if (buffer.length - offset < payloadBytes) return { frames, tornStart: start };
      offset += payloadBytes;
      if ((blockHeader & 1) !== 0) break;
    }
    if (checksum) {
      if (buffer.length - offset < 4) return { frames, tornStart: start };
      offset += 4;
    }
    frames.push({ start, end: offset });
  }
  return { frames };
}

function readRows(path) {
  const buf = readFileSync(path);
  const { frames, tornStart } = scanZstdFrames(buf);
  if (tornStart !== undefined) throw new Error(`torn final frame at byte ${tornStart}`);
  const parts = frames.map((f) => zlib.zstdDecompressSync(buf.subarray(f.start, f.end)));
  const text = Buffer.concat(parts).toString('utf8');
  const rows = text.split('\n').filter((l) => l.length > 0).map((l) => JSON.parse(l));
  return { bytes: buf.length, frames: frames.length, rows };
}

const catalogMod = await import(`file:///${HARNESS}/packages/session/session-format-catalog/lib/index.js`);
const catalog = catalogMod.sessionFormatCatalog ?? catalogMod.default?.sessionFormatCatalog ?? catalogMod.default;

const source = readRows(inputPath);
console.log(`[read] ${inputPath}`);
console.log(`[read] frames=${source.frames} bytes=${source.bytes} rows=${source.rows.length}`);
const header = source.rows[0];
console.log(`[read] header version=${header.version} id=${header.id} cwd=${header.cwd}`);
if (header.version !== 0) throw new Error(`expected a format v0 source, got v${header.version}`);
console.log(`[catalog] currentVersion=${catalog.currentVersion}`);
console.log(`[catalog] readHeader status=${catalog.readHeader(header).status}`);

/** type -> members the released v0 codec refuses (present in this legacy log). */
const dropFromData = new Map();
/** type -> member overrides for legacy shapes the released v0 codec knows under another revision. */
const patchData = new Map([['subagent/descriptor', { version: 3 }]]);
const patchedCounts = new Map();

function normalize(row) {
  const drop = dropFromData.get(row.type);
  const patch = patchData.get(row.type);
  if (typeof row.data !== 'object' || row.data === null) return row;
  let copy = row;
  if (drop !== undefined) {
    copy = { ...copy, data: { ...copy.data } };
    for (const member of drop) delete copy.data[member];
  }
  if (patch !== undefined && copy.data.version === 2) {
    if (copy === row) copy = { ...copy, data: { ...copy.data } };
    Object.assign(copy.data, patch);
    patchedCounts.set(row.type, (patchedCounts.get(row.type) ?? 0) + 1);
  }
  return copy;
}

function runMigration() {
  const restore = catalog.createRestore(header, { recovery: 'recoverable', validation: 'transformed' });
  for (let i = 1; i < source.rows.length; i++) restore.decodeRow(normalize(source.rows[i]));
  return restore.finish();
}

let artifact;
let rounds = 0;
for (;;) {
  try {
    artifact = runMigration();
    break;
  } catch (error) {
    const message = String(error?.message ?? error);
    const match = /refuses this format v0 Session: (.*?) has unexpected member "([^"]+)"/.exec(message);
    rounds += 1;
    if (match === null || rounds > 200) {
      console.error(`[migrate] FAILED after ${rounds - 1} normalizations: ${error.name}: ${message}`);
      process.exit(3);
    }
    const label = match[1];
    const type = label.split(' ')[0];
    const member = match[2];
    const scope = label.endsWith(' data') ? 'data' : 'row';
    if (scope !== 'data') {
      console.error(`[migrate] unsupported offender scope at "${label}" (member ${member})`);
      process.exit(4);
    }
    if (!dropFromData.has(type)) dropFromData.set(type, new Set());
    dropFromData.get(type).add(member);
    console.log(`[normalize] ${type}: dropping legacy member "${member}"`);
  }
}

console.log(`[migrate] OK -> v${artifact.header.version}, events=${artifact.events.length}, inheritedEventCount=${artifact.inheritedEventCount}`);
console.log(`[normalize] applied=${[...dropFromData].map(([t, s]) => `${t}(${[...s].join(',')})`).join(' ') || 'none'}`);
console.log(`[normalize] patched=${[...patchedCounts].map(([t, n]) => `${t}.version 2->3 x${n}`).join(' ') || 'none'}`);

// Report the descriptor the migrated session carries, when it has one.
for (const event of artifact.events) {
  if (event?.type === 'subagent/descriptor') {
    console.log(`[descriptor] ${JSON.stringify(event.data)}`);
    break;
  }
}

// Encode exactly as the backend's writeSyncedTemp does.
const headerLine = Buffer.from(`${JSON.stringify(catalog.encodeCurrentHeader(artifact.header, artifact.inheritedEventCount))}\n`);
const headerFrame = zlib.zstdCompressSync(headerLine, CHECKSUM_OPTIONS);
const body = artifact.events.map((e) => `${JSON.stringify(catalog.encodeCurrentEvent(e))}\n`).join('');
const bodyFrame = body.length === 0 ? Buffer.alloc(0) : zlib.zstdCompressSync(Buffer.from(body), CHECKSUM_OPTIONS);
const outBytes = Buffer.concat([headerFrame, bodyFrame]);
mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(outputPath, outBytes);
console.log(`[write] ${outputPath} bytes=${outBytes.length}`);

// Verify by reading the produced artifact exactly as the backend reads a generation.
const check = readRows(outputPath);
const readHeader = catalog.readHeader(check.rows[0]);
console.log(`[verify] frames=${check.frames} rows=${check.rows.length} readHeader=${readHeader.status} version=${check.rows[0].version}`);
if (readHeader.status !== 'current') throw new Error(`produced artifact is not current: ${readHeader.status}`);
const verifier = catalog.createRestore(check.rows[0], { recovery: 'recoverable', validation: 'transformed' });
for (let i = 1; i < check.rows.length; i++) verifier.decodeRow(check.rows[i]);
const verified = verifier.finish();
console.log(`[verify] events=${verified.events.length} (expected ${artifact.events.length})`);
if (verified.events.length !== artifact.events.length) throw new Error('event count mismatch after re-read');
if (check.rows[0].id !== header.id || check.rows[0].cwd !== header.cwd) throw new Error('identity mismatch after conversion');
console.log('[verify] OK');

function histogram(rows, pick) {
  const map = new Map();
  for (const r of rows) {
    const key = pick(r);
    map.set(key, (map.get(key) ?? 0) + 1);
  }
  return [...map].sort((a, b) => b[1] - a[1]);
}
const v0Hist = histogram(source.rows.slice(1), (r) => r.type);
const v3Hist = histogram(verified.events, (e) => e?.type ?? '(untyped)');
console.log('[hist v0]', v0Hist.map(([k, n]) => `${k}=${n}`).join(' '));
console.log('[hist v3]', v3Hist.map(([k, n]) => `${k}=${n}`).join(' '));
const count = (h, k) => h.find(([t]) => t === k)?.[1] ?? 0;
console.log(`[check] user/message v0=${count(v0Hist, 'user/message')} v3=${count(v3Hist, 'user/message')}`);
console.log(`[check] surface rows v0=${source.rows.filter((r) => r.surfaceOp !== undefined).length} v3=${verified.events.filter((e) => e?.surfaceOp !== undefined).length}`);
