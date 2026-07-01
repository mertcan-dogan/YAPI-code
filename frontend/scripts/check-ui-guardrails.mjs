#!/usr/bin/env node
// CR-028-D — UI guardrail check (dependency-free; the project lints via `tsc`,
// so this is the "documented check" the spec allows instead of a full ESLint
// toolchain). It flags the two drift sources the design system forbids in NEW
// page/feature code:
//   1. raw <button> elements  → use the Button primitive (components/ui)
//   2. inline hex colors       → use tokens (Tailwind color classes / CSS vars)
//
// Advisory by default (warns, exit 0) so it never fails the build on the existing
// ~108-button backlog. Run `node scripts/check-ui-guardrails.mjs --strict` (or a
// future pre-commit hook scoped to changed files) to make NEW violations blocking.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

// fileURLToPath handles spaces (%20) and Windows drive letters correctly.
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "src");
const STRICT = process.argv.includes("--strict");

// Files where a raw <button> is legitimate: the primitive/shell definitions
// themselves (Button lives here; overlays own their close buttons).
const ALLOW_BUTTON = [
  "components/ui/index.tsx",
  "components/SideDrawer.tsx",
  "components/CommandPalette.tsx",
];

const HEX = /(?:className|style)=[^>]*#[0-9a-fA-F]{3,8}\b/;
const RAW_BUTTON = /<button(\s|>)/;

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}

let rawButtons = 0;
let hexColors = 0;
const findings = [];

for (const file of walk(ROOT)) {
  const rel = relative(ROOT, file).replace(/\\/g, "/");
  const lines = readFileSync(file, "utf8").split("\n");
  lines.forEach((line, i) => {
    if (RAW_BUTTON.test(line) && !ALLOW_BUTTON.includes(rel)) {
      rawButtons++;
      findings.push(`  ${rel}:${i + 1}  raw <button> — use the Button primitive`);
    }
    if (HEX.test(line)) {
      hexColors++;
      findings.push(`  ${rel}:${i + 1}  inline hex color — use a token/class`);
    }
  });
}

if (findings.length) {
  console.log(`UI guardrails: ${rawButtons} raw <button>, ${hexColors} inline hex (advisory backlog).`);
  if (STRICT) {
    console.log(findings.join("\n"));
    console.error("\n--strict: failing on UI guardrail violations.");
    process.exit(1);
  }
} else {
  console.log("UI guardrails: clean.");
}
process.exit(0);
