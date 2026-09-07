// The cordis-shaped strict ctx shared by the conformance suite and the dsh smoke.
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const ROOT = resolve(new URL("../..", import.meta.url).pathname);

// What cordis hands every plugin without an inject declaration.
export const CORE = new Set([
  "get", "on", "once", "off", "emit", "parallel", "serial", "bail", "waterfall",
  "effect", "logger", "cmdlineArgs", "root", "scope", "plugin", "inject",
  "name", "reflect", "fiber", "runtime", "baseUrl", "config", "then", "constructor",
]);

/** A cordis-shaped ctx: declared services are stubs that record; anything else throws like cordis does. */
export function strictCtx(inject, log, overrides = {}) {
  const services = {
    on: (event, handler) => { log.push(`on:${event}`); return () => {}; },
    once: (event) => { log.push(`once:${event}`); return () => {}; },
    off: () => {},
    emit: () => {},
    parallel: async () => {},
    serial: async () => {},
    effect: (fn) => { log.push("effect"); return fn?.(); },
    logger: { info() {}, warn() {}, error() {}, debug() {} },
    baseUrl: overrides.baseUrl ?? pathToFileURL(join(ROOT, "modules")).href + "/",
    config: {},
    // Declared services: minimal recording stubs.
    skills: { registerProvider: (create) => { log.push("skills.registerProvider"); return () => {}; } },
    commands: { register: (def) => { log.push(`commands.register:${def?.name}`); return () => {}; } },
    systemPrompt: {
      context: (p) => { log.push(`systemPrompt.context:${p?.name}`); return () => {}; },
      section: (p) => { log.push(`systemPrompt.section:${p?.name}`); return () => {}; },
    },
    tools: { register: () => { log.push("tools.register"); return () => {}; } },
    subagents: { register: () => () => {} },
    settings: { mutate: async () => {} },
    authorization: { registerFlow: () => () => {} },
    mcp: {},
  };
  Object.assign(services, overrides);
  const declared = new Set([...CORE, ...inject]);
  return new Proxy(services, {
    get(target, prop) {
      if (typeof prop === "symbol") return undefined;
      if (!declared.has(prop)) {
        throw new Error(`cannot get property "${String(prop)}" without inject`);
      }
      return target[prop];
    },
  });
}

