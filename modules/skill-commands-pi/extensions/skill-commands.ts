/**
 * skill-commands — `/name args` for skills that declare `user-invocable: true`.
 *
 * pi already exposes every skill as `/skill:name` (docs/skills.md, "Skill
 * Commands"). This extension adds the short alias for the subset of skills that
 * are written as commands, so a marketplace module's `SKILL.md` is invoked the
 * same way on pi as `/name` is on Claude Code.
 *
 * The expansion is pi's own, replicated rather than called: `pi.sendUserMessage`
 * routes through `AgentSession.prompt(text, { expandPromptTemplates: false })`
 * (dist/core/agent-session.js:1128-1132), so sending "/skill:name args" through
 * it would NOT expand — the text would reach the model verbatim. The block built
 * below is byte-for-byte `AgentSession._expandSkillCommand`
 * (dist/core/agent-session.js:949-975). Keep them in sync.
 *
 * Event-only apart from the commands themselves: 0 tokens per turn.
 */

import { readFileSync } from "node:fs";
import { dirname } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** One line, one channel. Never throws. */
function warn(message: string, ctx?: any): void {
	const line = `[skill-commands] ${message}`;
	try {
		process.stderr.write(`${line}\n`);
	} catch {
		/* ignore */
	}
	try {
		ctx?.ui?.notify?.(line, "warning");
	} catch {
		/* ignore */
	}
}

/**
 * Minimal frontmatter read: only the top `---` block, only `key: value` scalars.
 * pi's own `Skill` object drops unknown frontmatter fields
 * (dist/core/skills.d.ts `SkillFrontmatter` is kept, `Skill` is not), so
 * `user-invocable` has to come from the file.
 */
export function frontmatter(source: string): Record<string, string> {
	const match = /^---\r?\n([\s\S]*?)\r?\n---/.exec(source);
	if (!match) return {};
	const fields: Record<string, string> = {};
	for (const line of match[1].split(/\r?\n/)) {
		const kv = /^([A-Za-z0-9_-]+):\s*(.*)$/.exec(line);
		if (!kv) continue;
		fields[kv[1]] = kv[2].trim().replace(/^["']|["']$/g, "");
	}
	return fields;
}

export function isUserInvocable(source: string): boolean {
	return frontmatter(source)["user-invocable"] === "true";
}

/** `AgentSession._expandSkillCommand`, replicated (see the file header). */
export function skillPrompt(name: string, filePath: string, source: string, args: string): string {
	const body = source.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "").trim();
	const block = `<skill name="${name}" location="${filePath}">\nReferences are relative to ${dirname(filePath)}.\n\n${body}\n</skill>`;
	return args ? `${block}\n\n${args}` : block;
}

export default function (pi: ExtensionAPI): void {
	// session_start, not load time: pi.getCommands() needs the session's resources
	// resolved, and it is the only enumeration of loaded skills available to an
	// extension that also carries each skill's SKILL.md path (agent-session.js
	// :1837-1842 maps skills to `skill:<name>` with `sourceInfo.path`).
	pi.on("session_start", async (_event: any, ctx: any) => {
		try {
			const commands = pi.getCommands();
			const taken = new Set(commands.map((c: any) => c.name));

			for (const command of commands) {
				if (command.source !== "skill") continue;
				const name = command.name.replace(/^skill:/, "");
				const filePath = command.sourceInfo?.path;
				if (!filePath) continue;

				let source: string;
				try {
					source = readFileSync(filePath, "utf-8");
				} catch (err) {
					warn(`cannot read ${filePath}: ${err instanceof Error ? err.message : String(err)}`, ctx);
					continue;
				}
				if (!isUserInvocable(source)) continue;

				// pi would keep both and suffix ours `/name:1`, which is not the
				// alias anyone typed. Decline instead, once, loudly.
				if (taken.has(name)) {
					warn(`/${name} is already taken; use /skill:${name}`, ctx);
					continue;
				}
				taken.add(name);

				const description = command.description ?? `Run the ${name} skill`;
				pi.registerCommand(name, {
					description,
					handler: async (args: string, commandCtx: any) => {
						try {
							// Re-read at invocation: the skill may have been edited mid-session.
							const latest = readFileSync(filePath, "utf-8");
							// pi.sendUserMessage, not commandCtx.sendUserMessage: that method
							// exists only on ReplacedSessionContext (types.d.ts:296-305), not
							// on the ExtensionCommandContext a handler receives.
							pi.sendUserMessage(skillPrompt(name, filePath, latest, (args ?? "").trim()));
						} catch (err) {
							warn(`/${name} failed: ${err instanceof Error ? err.message : String(err)}`, commandCtx);
						}
					},
				});
			}
		} catch (err) {
			warn(`registration failed: ${err instanceof Error ? err.message : String(err)}`, ctx);
		}
	});
}
