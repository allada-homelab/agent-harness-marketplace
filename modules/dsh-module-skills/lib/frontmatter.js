/**
 * YAML front matter for Agent Skills, parsed without a YAML dependency.
 *
 * Why not `yaml`: this repo installs with no third-party runtime packages, and
 * a dsh profile bundle that drags one in makes the whole marketplace gate need
 * a network install. Skill front matter is a flat map of scalars plus three
 * shapes the format actually uses — flow sequences (`harness: [claude, dsh]`),
 * block sequences, and one nested map (`metadata:`) — so the subset below is
 * the whole grammar in practice.
 *
 * Deliberate subset. Anything outside it (anchors, multi-document streams,
 * deep nesting beyond `metadata:`) parses to a string or is dropped; unknown
 * keys are carried through untouched and ignored by the caller. Values that
 * matter to dsh (`name`, `description`) are validated by the caller, so a
 * misparse drops the skill with a warning instead of registering a bad one.
 */

const OPEN_RE = /^---[ \t]*\r?\n/;

/**
 * Split a Markdown file into its front matter map and body.
 * @param {string} text - complete file text.
 * @returns {{data: Record<string, unknown>, body: string} | undefined} the
 *   parsed pair, or `undefined` when the file has no closing front matter.
 */
export function parseFrontmatter(text) {
  const open = OPEN_RE.exec(text);
  if (!open) return undefined;
  const start = open[0].length;
  const close = findClose(text, start);
  if (close === undefined) return undefined;
  return {
    data: parseBlock(text.slice(start, close.end).split(/\r?\n/), 0).value,
    body: text.slice(close.bodyStart),
  };
}

/** Locate the closing `---` line, mirroring dsh's own line-exact scan. */
function findClose(text, start) {
  let lineStart = start;
  while (lineStart <= text.length) {
    const nl = text.indexOf('\n', lineStart);
    const lineEnd = nl < 0 ? text.length : nl;
    if (text.slice(lineStart, lineEnd).replace(/\r$/, '') === '---') {
      return { end: lineStart, bodyStart: nl < 0 ? text.length : nl + 1 };
    }
    if (nl < 0) return undefined;
    lineStart = nl + 1;
  }
  return undefined;
}

/** Indentation width of a line, or -1 for a blank/comment line. */
function indentOf(line) {
  if (line.trim() === '' || /^\s*#/.test(line)) return -1;
  return line.length - line.trimStart().length;
}

/**
 * Parse one indented block of `key: value` pairs starting at `i`.
 * @returns {{value: Record<string, unknown>, next: number}}
 */
function parseBlock(lines, from) {
  const map = {};
  let i = from;
  let indent;
  while (i < lines.length) {
    const raw = lines[i];
    const level = indentOf(raw);
    if (level < 0) { i += 1; continue; }
    indent ??= level;
    if (level < indent) break;
    const match = /^\s*([^:\s][^:]*):(?:[ \t]+(.*))?$/.exec(raw);
    if (!match) { i += 1; continue; }
    const key = match[1].trim();
    const inline = match[2]?.trim() ?? '';
    if (inline === '' || inline === '>' || inline === '|' || /^[>|][-+]?$/.test(inline)) {
      const nested = parseNested(lines, i + 1, indent, inline);
      map[key] = nested.value;
      i = nested.next;
      continue;
    }
    map[key] = scalar(stripComment(inline));
    i += 1;
  }
  return { value: map, next: i };
}

/** A key with no inline value: block scalar, block sequence, or nested map. */
function parseNested(lines, from, parentIndent, marker) {
  let i = from;
  while (i < lines.length && indentOf(lines[i]) < 0) i += 1;
  const level = i < lines.length ? indentOf(lines[i]) : -1;
  if (level <= parentIndent) return { value: marker.startsWith('>') || marker.startsWith('|') ? '' : null, next: i };
  if (marker.startsWith('>') || marker.startsWith('|')) return blockScalar(lines, i, level, marker);
  if (lines[i].trimStart().startsWith('- ')) {
    const items = [];
    while (i < lines.length) {
      const width = indentOf(lines[i]);
      if (width < 0) { i += 1; continue; }
      if (width < level || !lines[i].trimStart().startsWith('- ')) break;
      items.push(scalar(stripComment(lines[i].trimStart().slice(2).trim())));
      i += 1;
    }
    return { value: items, next: i };
  }
  return parseBlock(lines, i);
}

/** Folded (`>`) and literal (`|`) block scalars with `-`/`+` chomping. */
function blockScalar(lines, from, level, marker) {
  const collected = [];
  let i = from;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() !== '' && indentOf(line) < level) break;
    collected.push(line.slice(level));
    i += 1;
  }
  while (collected.length > 0 && collected[collected.length - 1].trim() === '') collected.pop();
  const folded = marker.startsWith('>')
    ? collected.reduce((text, line) => {
      if (line.trim() === '') return `${text}\n`;
      return text === '' || text.endsWith('\n') ? text + line.trim() : `${text} ${line.trim()}`;
    }, '')
    : collected.join('\n');
  return { value: marker.endsWith('+') ? `${folded}\n` : folded, next: i };
}

/** Drop a trailing ` # comment` outside quotes. */
function stripComment(value) {
  if (value.startsWith('"') || value.startsWith("'")) return value;
  const hash = value.search(/\s#/);
  return hash < 0 ? value : value.slice(0, hash).trim();
}

/** One scalar or flow sequence. */
function scalar(raw) {
  if (raw.startsWith('[') && raw.endsWith(']')) {
    const inner = raw.slice(1, -1).trim();
    return inner === '' ? [] : inner.split(',').map((item) => scalar(item.trim()));
  }
  if (raw.length >= 2 && raw.startsWith('"') && raw.endsWith('"')) {
    return raw.slice(1, -1).replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\');
  }
  if (raw.length >= 2 && raw.startsWith("'") && raw.endsWith("'")) return raw.slice(1, -1).replace(/''/g, "'");
  if (raw === 'true' || raw === 'yes' || raw === 'on') return true;
  if (raw === 'false' || raw === 'no' || raw === 'off') return false;
  if (raw === 'null' || raw === '~' || raw === '') return null;
  if (/^-?\d+$/.test(raw)) return Number(raw);
  if (/^-?\d*\.\d+$/.test(raw)) return Number(raw);
  return raw;
}
