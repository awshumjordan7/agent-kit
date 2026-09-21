import fs from 'node:fs/promises'

const [modulePath, action, rawInput = '{}'] = process.argv.slice(2)
const input = JSON.parse(rawInput)

globalThis.args = {
  lane: 'quick',
  auto: true,
  runDir: '/tmp/forge-test-run',
  projectDir: '/tmp/forge-test-project',
  repo: 'example-api',
  noShip: true,
  dryRun: true,
  dryRunFindings: 1,
  fullySpecified: true,
  planText: '## Phases\n### Phase A1\nFiles: `src/app.py`\n',
  forgeConfig: {
    roles: {
      impl: { provider: 'codex', model: 'test', effort: 'high' },
      'quick-impl': { provider: 'codex', model: 'test', effort: 'high' },
      review: { provider: 'codex', model: 'test', effort: 'high' },
    },
    stages: { sandbox: false, ff_review: false, qa_login: false },
    thresholds: { quickReviewThreshold: 8, fixCap: 3 },
    lenses: { security: '(auth)', design: '\\.tsx?$' },
    ticketUrl: '',
    repos: input.repos || { frontend: 'example-ui', backend: 'example-api' },
  },
}
const runtimeAgent = async () => null
const runtimeParallel = async tasks => Promise.all(tasks.map(task => task()))
const runtimePipeline = async (rows, ...steps) => {
  let state = rows[0]
  for (const step of steps) state = await step(state)
  return [state]
}
const runtimePhase = () => {}
const sourcePath = new URL(`../${modulePath}`, import.meta.url)
let source = await fs.readFile(sourcePath, 'utf8')
source = source
  .replace('export const meta =', 'const meta =')
  .replace('export const __test =', 'const __test =')
  .replace('const runtimeAgent = agent', 'globalThis.__forgeTest = __test\nconst runtimeAgent = agent')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const run = new AsyncFunction('args', 'agent', 'parallel', 'pipeline', 'phase', source)
await run(globalThis.args, runtimeAgent, runtimeParallel, runtimePipeline, runtimePhase)
const api = globalThis.__forgeTest
let result
if (action === 'parse') result = api.parseCheckpoints(input.plan, input.checkpoints)
if (action === 'role') result = api.pickImplRole(input.lane, input.fullySpecified, input.plan, input.threshold)
if (action === 'triage') result = api.partitionTriage(input.findings, input.verdicts, input.auto)
if (action === 'sandbox') result = api.sandboxAllowed(input.stageOn, input.repo, input.repos)
if (action === 'sandbox-checks') {
  result = {
    frontend: api.sandboxCheck(true),
    backend: api.sandboxCheck(false),
  }
}
if (action === 'dry') result = api.dryRunJournal
process.stdout.write(`${JSON.stringify(result)}\n`)
