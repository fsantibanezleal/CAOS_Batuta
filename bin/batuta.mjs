#!/usr/bin/env node
// npx entry: find Python 3.10+ and run plugins/batuta/scripts/batuta.py with the same arguments and exit code.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const script = join(root, "plugins", "batuta", "scripts", "batuta.py");
const candidates = [["py", "-3"], ["python3"], ["python"]];
const probe = "import sys; print('%d.%d' % sys.version_info[:2])";

function usable(candidate) {
  const [cmd, ...pre] = candidate;
  const result = spawnSync(cmd, [...pre, "-c", probe], { encoding: "utf8" });
  if (result.error || result.status !== 0) return false;
  const [major, minor] = result.stdout.trim().split(".").map(Number);
  return major > 3 || (major === 3 && minor >= 10);
}

if (!existsSync(script)) {
  console.error(`batuta: cannot find ${script}`);
  process.exit(1);
}
const python = candidates.find(usable);
if (!python) {
  console.error("batuta: Python 3.10 or newer is required (tried: py -3, python3, python).");
  process.exit(1);
}
const [cmd, ...pre] = python;
const run = spawnSync(cmd, [...pre, script, ...process.argv.slice(2)], { stdio: "inherit" });
if (run.error) {
  console.error(`batuta: ${run.error.message}`);
  process.exit(1);
}
process.exit(run.status ?? 1);
