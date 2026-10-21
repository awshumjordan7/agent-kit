#!/usr/bin/env node
// Parse-check Workflow scripts the way the Workflow runtime loads them.
//
// Usage: node .github/scripts/check_workflow_js.mjs [file ...]
// With no files, checks every tracked *.js under core/ and modules/.
//
// `node --check` is not enough: a file with `export` is detected as ESM, and an
// unescaped backtick inside a template literal can still pass. `--input-type=module
// --check` rejects every valid script because of the top-level `return {`.
// So each file is parsed as an async function body with the first column-0 `export ` removed.
// Exit 1 lists the files that fail to parse; exit 1 also when no file is found, exit 0 otherwise. Node built-ins only.

import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor

function trackedScripts() {
  const out = execFileSync('git', ['ls-files', '-z', '--', 'core/*.js', 'modules/*.js'], { encoding: 'utf8' })
  return out.split('\0').filter(Boolean)
}

const files = process.argv.length > 2 ? process.argv.slice(2) : trackedScripts()
let failed = 0
for (const file of files) {
  const body = readFileSync(file, 'utf8').replace(/^export\s+/m, '')
  try {
    new AsyncFunction(body)
    console.log(`ok   ${file}`)
  } catch (err) {
    failed += 1
    console.error(`FAIL ${file}: ${err.name}: ${err.message}`)
  }
}
if (files.length === 0) { console.error('FAIL no Workflow scripts found'); process.exit(1) }
process.exit(failed ? 1 : 0)
