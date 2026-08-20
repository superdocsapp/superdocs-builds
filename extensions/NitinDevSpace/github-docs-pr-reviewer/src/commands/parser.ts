export const commandPrefix = "/superdocs";

export type ParsedCommand =
  | { verb: "review" }
  | { verb: "preview" }
  | { verb: "help" }
  | { verb: "apply"; target: { kind: "finding"; findingId: string } }
  | { verb: "apply"; target: { kind: "all-safe" } };

export type CommandParseFailure =
  | "not-a-command"
  | "unknown-verb"
  | "missing-finding-id"
  | "invalid-finding-id"
  | "unexpected-arguments";

export type CommandParseResult =
  | { ok: true; command: ParsedCommand }
  | { ok: false; failure: CommandParseFailure; detail: string };

const findingIdPattern = /^[0-9a-f]{10}$/;

/**
 * Parses a `/superdocs ...` command out of an issue comment body.
 *
 * The command must be the comment's first non-empty line, which is what keeps a
 * quoted command from running: a fence or a `>` arrives first and the comment is
 * read as discussion. Document and comment text routinely quotes commands while
 * talking about them, and quoting one must never execute it.
 */
export function parseCommand(body: string): CommandParseResult {
  const commandLine = findCommandLine(body);

  if (commandLine === undefined) {
    return {
      ok: false,
      failure: "not-a-command",
      detail: "The comment does not begin with a SuperDocs command."
    };
  }

  const tokens = commandLine.split(/\s+/).filter(Boolean);
  const [, rawVerb, ...args] = tokens;
  const verb = rawVerb?.toLowerCase();

  switch (verb) {
    case "review":
    case "preview":
    case "help":
      if (args.length > 0) {
        return {
          ok: false,
          failure: "unexpected-arguments",
          detail: `\`${commandPrefix} ${verb}\` takes no arguments.`
        };
      }
      return { ok: true, command: { verb } };

    case "apply":
      return parseApply(args);

    case undefined:
      return {
        ok: false,
        failure: "unknown-verb",
        detail: `Say what to do, for example \`${commandPrefix} help\`.`
      };

    default:
      return {
        ok: false,
        failure: "unknown-verb",
        detail: `\`${rawVerb}\` is not a SuperDocs command. Try \`${commandPrefix} help\`.`
      };
  }
}

export function formatHelp(): string {
  return [
    "**SuperDocs docs reviewer commands**",
    "",
    `- \`${commandPrefix} review\` - rerun the docs review on the current head commit`,
    `- \`${commandPrefix} preview\` - regenerate the export preview`,
    `- \`${commandPrefix} apply <finding-id>\` - apply one safe suggested fix as a commit`,
    `- \`${commandPrefix} apply all-safe\` - apply every safe suggested fix in one commit`,
    `- \`${commandPrefix} help\` - show this message`,
    "",
    "Finding IDs appear in each inline review comment. Applying a fix requires write access to the repository."
  ].join("\n");
}

function parseApply(args: string[]): CommandParseResult {
  const [target, ...rest] = args;

  if (!target) {
    return {
      ok: false,
      failure: "missing-finding-id",
      detail: `Name what to apply, for example \`${commandPrefix} apply a1b2c3d4e5\` or \`${commandPrefix} apply all-safe\`.`
    };
  }

  if (rest.length > 0) {
    return {
      ok: false,
      failure: "unexpected-arguments",
      detail: `\`${commandPrefix} apply\` takes one finding ID or \`all-safe\`.`
    };
  }

  if (target.toLowerCase() === "all-safe") {
    return { ok: true, command: { verb: "apply", target: { kind: "all-safe" } } };
  }

  const findingId = stripInlineCode(target).toLowerCase();

  if (!findingIdPattern.test(findingId)) {
    return {
      ok: false,
      failure: "invalid-finding-id",
      detail: `\`${target}\` is not a finding ID. Finding IDs are 10 hex characters, copied from a review comment.`
    };
  }

  return {
    ok: true,
    command: { verb: "apply", target: { kind: "finding", findingId } }
  };
}

/**
 * Returns the command line only when the comment leads with it. Text before the
 * command means the comment is a discussion, not an instruction.
 */
function findCommandLine(body: string): string | undefined {
  for (const rawLine of body.split(/\r?\n/)) {
    const line = rawLine.trim();

    if (line === "") continue;

    if (line.toLowerCase().startsWith(commandPrefix)) {
      return line;
    }

    return undefined;
  }

  return undefined;
}

function stripInlineCode(value: string): string {
  return value.replace(/^`+/, "").replace(/`+$/, "");
}
