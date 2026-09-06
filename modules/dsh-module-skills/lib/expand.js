/**
 * `$ARGUMENTS` / `$N` substitution — the one thing dsh's native slash path
 * does not do.
 *
 * Verified in dsh 0.1.1-rc.2: picking a skill from the `/` menu only types
 * `/<name> ` into the composer (dsh-client-ui-skill lib/client.js, the source's
 * `onPick` returns `{ text: "/" + candidate.name + " " }`), and the server
 * matches the bare gesture `/(^|\s)\/([a-z0-9]+(?:-[a-z0-9]+)*)(?=\s|$)/`
 * (dsh-tool-skill lib/index.js:352, `invokedSkillNames` :360) and injects the
 * body VERBATIM through `renderSkillContent` (:163-170). The user's typed
 * arguments ride along only as their own plain user message; nothing ever
 * substitutes them into the body. That is the gap this module fills.
 */

/**
 * Split a raw argument string into words, honoring single and double quotes.
 * @param {string} raw - text following the command name.
 * @returns {string[]} the positional words, quotes removed.
 */
export function splitArgs(raw) {
  const words = [];
  let current = '';
  let quote;
  let started = false;
  for (const char of raw) {
    if (quote !== undefined) {
      if (char === quote) quote = undefined;
      else current += char;
      continue;
    }
    if (char === '"' || char === "'") { quote = char; started = true; continue; }
    if (/\s/.test(char)) {
      if (started) { words.push(current); current = ''; started = false; }
      continue;
    }
    current += char;
    started = true;
  }
  if (started) words.push(current);
  return words;
}

/** Tokens that make a body worth shadowing with a real command. */
const TOKEN_RE = /\$ARGUMENTS\b|\$\{\d+(?::-[^}]*)?\}|\$\d+/;

/**
 * Whether a skill body uses any substitution token.
 * @param {string} body - the SKILL.md body.
 * @returns {boolean} true when expansion would change the text.
 */
export function usesArguments(body) {
  return TOKEN_RE.test(body);
}

/**
 * Substitute argument tokens into a skill body.
 *
 * - `$ARGUMENTS` — the whole argument string, trimmed (empty when none given).
 * - `$N` — the N-th word (1-based). Left VERBATIM when that word was not
 *   supplied, so a body that mentions `$1` in a shell snippet still reads
 *   correctly when the skill is invoked bare.
 * - `${N:-default}` — the N-th word, or the default when absent.
 *
 * `$FOO` and every other shell-looking text is never touched.
 *
 * @param {string} body - the SKILL.md body.
 * @param {string} raw - text following the command name.
 * @returns {string} the expanded body.
 */
export function expandArguments(body, raw) {
  const all = raw.trim();
  const words = splitArgs(raw);
  return body.replace(/\$ARGUMENTS\b|\$\{(\d+)(?::-([^}]*))?\}|\$(\d+)/g, (token, braced, fallback, bare) => {
    if (token.startsWith('$ARGUMENTS')) return all;
    const index = Number(braced ?? bare);
    if (index < 1) return token;
    const word = words[index - 1];
    if (word !== undefined) return word;
    return fallback ?? (braced !== undefined ? '' : token);
  });
}
