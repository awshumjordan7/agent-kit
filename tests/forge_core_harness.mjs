import fs from 'node:fs/promises'

const [modulePath, action, rawInput = '{}'] = process.argv.slice(2)
const input = JSON.parse(rawInput)

globalThis.args = {
  lane: 'build',
  auto: true,
  runDir: '/tmp/forge-test-run',
  projectDir: '/tmp/forge-test-project',
  repo: 'example-api',
  noShip: action !== 'dry',
  dryRun: action !== 'codex-budget',
  dryRunFindings: 1,
  dryRunStubborn: input.dryRunStubborn === true,
  dryRunFailGate: input.dryRunFailGate || null,
  fullySpecified: true,
  planText: '## Phases\n### Phase A1\nFiles: `src/app.py`\n',
  forgeConfig: {
    roles: {
      impl: { provider: 'codex', model: 'test', effort: 'high' },
      'quick-impl': { provider: 'codex', model: 'test', effort: 'high' },
      review: { provider: 'codex', model: 'test', effort: 'high' },
    },
    stages: { sandbox: false, ff_review: false, qa_login: false },
    thresholds: { quickReviewThreshold: 8 },
    lenses: { security: '(auth)', design: '\\.tsx?$' },
    ticketUrl: '',
    repos: input.repos || { frontend: 'example-ui', backend: 'example-api' },
  },
}
const runtimeAgent = async () => {
  if (action === 'codex-budget') {
    return {
      codexInvoked: true,
      threadMode: 'start',
      threadExists: true,
      filesChanged: [],
      testsWritten: 0,
      summary: 'test result',
      error: 'CODEX_BUDGET_EXCEEDED: test terminal error',
    }
  }
  return null
}
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
if (action === 'codex-budget') {
  source = source.replace(
    'await loadForgeConfig()',
    "return await globalThis.__forgeTest.codexAgent('test prompt', { label: 'codex-budget' })\nawait loadForgeConfig()",
  )
}
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const run = new AsyncFunction('args', 'agent', 'parallel', 'pipeline', 'phase', source)
const executionResult = await run(globalThis.args, runtimeAgent, runtimeParallel, runtimePipeline, runtimePhase)
const api = globalThis.__forgeTest
let result
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
if (action === 'codex-budget') result = executionResult
process.stdout.write(`${JSON.stringify(result)}\n`)
