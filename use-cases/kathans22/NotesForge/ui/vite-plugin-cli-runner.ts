import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import type { Plugin } from "vite";

// Dev-server only (registered on configureServer, never configurePreviewServer)
// — this endpoint does not exist in `vite build` output or `vite preview`.
// It exists so the console's own buttons can trigger the real CLI instead of
// a person typing commands in a terminal during a demo; it never recomputes
// anything itself, it just runs the same `compliance` subcommands the CLI
// already has, then the same sync script `npm run sync` already runs.

const PROJECT_ROOT = fileURLToPath(new URL("..", import.meta.url)); // NotesForge/
const UI_ROOT = fileURLToPath(new URL(".", import.meta.url)); // NotesForge/ui/

const COMMANDS: Record<string, string[]> = {
  coverage: ["compliance", "--coverage"],
  generate: ["compliance", "--generate"],
  matrix: ["compliance", "--matrix"],
  amend: ["compliance", "--amend"],
  "registry-seed": ["compliance", "--registry-seed"],
};

const IS_WIN = process.platform === "win32";

export function cliRunnerPlugin(): Plugin {
  return {
    name: "notesforge-cli-runner",
    configureServer(server) {
      server.middlewares.use("/api/run", (req, res) => {
        const url = new URL(req.url ?? "", "http://localhost");
        const cmd = url.searchParams.get("cmd") ?? "";
        const args = COMMANDS[cmd];

        if (!args) {
          res.statusCode = 400;
          res.end(`unknown command "${cmd}"`);
          return;
        }

        res.writeHead(200, {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
        });

        const send = (event: string, data: string) => {
          res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
        };
        const streamOutput = (chunk: Buffer) => {
          for (const line of chunk.toString("utf8").split(/\r?\n/)) {
            if (line.length > 0) send("log", line);
          }
        };

        send("log", `$ npm run dev -- ${args.join(" ")}`);
        const child = spawn(IS_WIN ? "npm.cmd" : "npm", ["run", "dev", "--", ...args], {
          cwd: PROJECT_ROOT,
          shell: IS_WIN,
        });
        child.stdout.on("data", streamOutput);
        child.stderr.on("data", streamOutput);

        const cleanup = () => {
          req.removeListener("close", onClientClose);
        };
        const onClientClose = () => {
          child.kill();
          cleanup();
        };
        req.on("close", onClientClose);

        child.on("close", (code) => {
          cleanup();
          send("log", `[compliance --${cmd} exited: ${code}]`);

          if (code !== 0) {
            send("done", "failed");
            res.end();
            return;
          }

          // Refresh public/data/ so the screen has something new to show —
          // the same `npm run sync` step the README tells a person to run
          // by hand after a CLI command.
          send("log", "$ npm run sync");
          const sync = spawn(IS_WIN ? "npx.cmd" : "npx", ["tsx", "scripts/sync-artifacts.ts"], {
            cwd: UI_ROOT,
            shell: IS_WIN,
          });
          sync.stdout.on("data", streamOutput);
          sync.stderr.on("data", streamOutput);
          sync.on("close", (syncCode) => {
            send("log", `[sync exited: ${syncCode}]`);
            send("done", syncCode === 0 ? "ok" : "sync-failed");
            res.end();
          });
        });
      });
    },
  };
}
