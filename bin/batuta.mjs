#!/usr/bin/env node
// npx entry: find Python 3.10+ and run plugins/batuta/scripts/batuta.py with the same arguments and exit code.
//
// Discovery order: the command in BATUTA_PYTHON (when set), then on Windows `py -3`, then `python3`, then `python`.
// The first that reports version 3.10 or newer wins; one that is older, cannot run or is missing is skipped. When none
// is suitable the entry exits 1 and names every candidate it tried and how to set BATUTA_PYTHON.
import { spawnSync } from "node:child_process";
import { existsSync, realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const MIN = [3, 10];
const PROBE = "import sys; print('%d.%d' % sys.version_info[:2])";

function probe(cmd, args) {
  return spawnSync(cmd, [...args, "-c", PROBE], { encoding: "utf8", timeout: 15000 });
}

function atLeast(version) {
  const [major, minor] = version.split(".").map(Number);
  return major > MIN[0] || (major === MIN[0] && minor >= MIN[1]);
}

// BATUTA_PYTHON names one command; a value that is an existing file is one executable even with spaces in its path,
// anything else is split on white space so `py -3` works.
function fromEnvironment(value) {
  if (existsSync(value)) return [value];
  return value.trim().split(/\s+/).filter(Boolean);
}

export function findPython({ env = process.env, platform = process.platform, run = probe } = {}) {
  const candidates = [];
  if (env.BATUTA_PYTHON && env.BATUTA_PYTHON.trim()) {
    candidates.push({ command: fromEnvironment(env.BATUTA_PYTHON), label: `BATUTA_PYTHON=${env.BATUTA_PYTHON}` });
  }
  if (platform === "win32") candidates.push({ command: ["py", "-3"], label: "py -3" });
  candidates.push({ command: ["python3"], label: "python3" });
  candidates.push({ command: ["python"], label: "python" });
  const tried = [];
  for (const { command, label } of candidates) {
    const [cmd, ...pre] = command;
    const result = run(cmd, pre);
    const text = result && !result.error && result.status === 0 ? String(result.stdout || "").trim() : "";
    if (/^\d+\.\d+$/.test(text)) {
      if (atLeast(text)) return { python: command, tried };
      tried.push(`${label} (${text})`);
    } else {
      tried.push(`${label} (not found)`);
    }
  }
  return { python: null, tried };
}

function main() {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..");
  const script = join(root, "plugins", "batuta", "scripts", "batuta.py");
  if (!existsSync(script)) {
    console.error(`batuta: cannot find ${script}`);
    process.exit(1);
  }
  const { python, tried } = findPython();
  if (!python) {
    console.error(
      `batuta: Python ${MIN.join(".")} or newer is required (tried: ${tried.join(", ")}). ` +
        "Install it, or set BATUTA_PYTHON to its command, for example BATUTA_PYTHON=\"py -3\" or the full path of the interpreter.",
    );
    process.exit(1);
  }
  const [cmd, ...pre] = python;
  const run = spawnSync(cmd, [...pre, script, ...process.argv.slice(2)], { stdio: "inherit" });
  if (run.error) {
    console.error(`batuta: ${run.error.message}`);
    process.exit(1);
  }
  process.exit(run.status ?? 1);
}

const entry = process.argv[1];
if (entry && import.meta.url === pathToFileURL(realpathSync(entry)).href) main();
