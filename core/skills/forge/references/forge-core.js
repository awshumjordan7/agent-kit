// forge-core.js runs inside the Workflow sandbox; filesystem work belongs to agents.

export const meta = {
  name: 'forge-core',
  description: 'Forge orchestration: implement, gate, ship, sandbox, independent review, bounded fixes, and handoff',
  phases: [
    { title: 'Implement', detail: 'Codex implementation on a persistent thread' },
    { title: 'Gate', detail: 'Repository-native tests, lint, Semgrep, and migration checks' },
    { title: 'Ship', detail: 'Branch, commit, push, and non-draft pull request' },
    { title: 'Sandbox', detail: 'Platform sandbox tests, signed-out and sign-in check, and criterion-driven smoke checks' },
    { title: 'Review', detail: 'Independent Codex, optional Claude, and path-selected lenses' },
    { title: 'Fix', detail: 'One Codex fix round, gate, verify' },
    { title: 'Handoff', detail: 'Run status, evidence, decisions, and manual QA' },
  ],
}

const TIERS = {
  fable: {
    implementer: { model: 'opus', effort: 'high' },
    reviewer: { model: 'fable', effort: 'high' },
    spotReviewer: { model: 'opus', effort: 'high' },
    codexWrap: { model: 'sonnet', effort: 'low' },
    qa: { model: 'sonnet', effort: 'medium' },
    gate: { model: 'haiku', effort: 'low' },
    sandboxQA: { model: 'sonnet', effort: 'medium' },
    qaDraft: { model: 'sonnet', effort: 'low' },
    smoke: { model: 'sonnet', effort: 'medium' },
    trim: { model: 'sonnet', effort: 'medium' },
    lens: { model: 'sonnet', effort: 'high' },
    shipper: { model: 'sonnet', effort: 'low' },
    handoff: { model: 'sonnet', effort: 'low' },
    changedFiles: { model: 'sonnet', effort: 'low' },
    readConfig: { model: 'haiku', effort: 'low' },
  },
  opus: {
    implementer: { model: 'opus', effort: 'high' },
    reviewer: { model: 'opus', effort: 'high' },
    spotReviewer: { model: 'opus', effort: 'high' },
    codexWrap: { model: 'sonnet', effort: 'low' },
    qa: { model: 'sonnet', effort: 'medium' },
    gate: { model: 'haiku', effort: 'low' },
    sandboxQA: { model: 'sonnet', effort: 'medium' },
    qaDraft: { model: 'sonnet', effort: 'low' },
    smoke: { model: 'sonnet', effort: 'medium' },
    trim: { model: 'sonnet', effort: 'medium' },
    lens: { model: 'sonnet', effort: 'high' },
    shipper: { model: 'sonnet', effort: 'low' },
    handoff: { model: 'sonnet', effort: 'low' },
    changedFiles: { model: 'sonnet', effort: 'low' },
    readConfig: { model: 'haiku', effort: 'low' },
  },
}

const ROLE_MAP = {
  implementer: ['impl', 'quick-impl'],
  reviewer: ['review'],
  spotReviewer: ['spot-review'],
  qa: ['qa'],
  qaDraft: ['qa'],
  smoke: ['qa'],
}

const PARAMS = {
  lane: args.lane || 'dev',
  auto: args.auto === true,
  runDir: args.runDir,
  projectDir: args.projectDir,
  repo: args.repo || '',
  ticket: args.ticket || 'forge',
  tickets: Array.isArray(args.tickets) && args.tickets.length ? args.tickets.map(String) : [args.ticket || 'forge'],
  criteria: Array.isArray(args.criteria) ? args.criteria : [],
  tier: TIERS[args.tier] ? args.tier : 'fable',
  tierSandbox: args.tier_sandbox || 'sandbox',
  // Reuse a fork another run built (companion repo run): {sandboxId, loginUrl, previewUrl}.
  // Changed files are uploaded into it instead of creating a second sandbox.
  existingSandbox: args.existingSandbox && typeof args.existingSandbox.sandboxId === 'string' ? args.existingSandbox : null,
  noShip: args.noShip === true,
  spawnCap: Number.isInteger(args.spawnCap) && args.spawnCap >= 1 ? args.spawnCap : 32,
  rulings: Array.isArray(args.rulings) ? args.rulings : null,
  checkpoints: Array.isArray(args.checkpoints) ? args.checkpoints : null,
  planText: typeof args.planText === 'string' ? args.planText : null,
  planPath: typeof args.planPath === 'string' && args.planPath ? args.planPath : `${args.runDir}/plan.md`,
  dependsOnGate: typeof args.dependsOnGate === 'string' && args.dependsOnGate.startsWith('/') ? args.dependsOnGate : null,
  dryRun: args.dryRun === true,
  dryRunFailGate: typeof args.dryRunFailGate === 'string' ? args.dryRunFailGate : null,
  dryRunFindings: Number.isInteger(args.dryRunFindings) && args.dryRunFindings > 0 ? args.dryRunFindings : 0,
  forgeConfig: args.forgeConfig && typeof args.forgeConfig === 'object' ? args.forgeConfig : null,
}

let FORGE_CONFIG = PARAMS.forgeConfig

// Codex model/effort/budget per role live in ~/.claude/skills/forge/forge.config.json and are
// resolved by codex-exec.sh from `--role`. The Workflow only passes explicit --model/--effort
// when args override them (codexModelImpl / codexModelReview / codexModel, codexEffortImpl /
// codexEffortReview). Quick-lane implement and fix rounds use quick-impl; other implementation
// uses impl, while reviewer and verifier rounds use review.
// codex-exec.sh prepends references/codex-prompt-contract.md (ranged reads only, no web/MCP,
// the tool-call and output-byte budget) to every prompt and kills a session that exceeds the
// budget, so prompts written here carry their inputs inline and never say "read file X".
function codexFlags(role, model, effort) {
  return `--role ${role}` + (model ? ` --model ${model}` : '') + (effort ? ` --effort ${effort}` : '')
}
const CODEX_IMPL_FLAGS = codexFlags(PARAMS.lane === 'quick' ? 'quick-impl' : 'impl', args.codexModelImpl || args.codexModel, args.codexEffortImpl)
const CODEX_REVIEW_FLAGS = codexFlags('review', args.codexModelReview || args.codexModel, args.codexEffortReview)
const CODEX_SH = '~/.claude/skills/forge/scripts/codex-exec.sh'
const PLAN = PARAMS.planPath

// Persistent Codex thread files:
// CODEX_PLAN_THREAD / codex-plan.thread is reserved for Phase 3 plan review outside this script.
// Each implementation segment owns its thread and its checkpoint fixes.
// CODEX_FIX_THREAD / codex-fix.thread owns final review fixes.
// CODEX_REVIEW_THREAD / codex-review.thread owns review and all fix verification.
const CODEX_PLAN_THREAD = `${PARAMS.runDir}/codex-plan.thread`
const CODEX_IMPL_THREAD = `${PARAMS.runDir}/codex-impl.thread`
const CODEX_FIX_THREAD = `${PARAMS.runDir}/codex-fix.thread`
const CODEX_REVIEW_THREAD = `${PARAMS.runDir}/codex-review.thread`

if (!PARAMS.runDir || !PARAMS.projectDir) {
  throw new Error('forge-core requires args.runDir and args.projectDir')
}
if (!['quick', 'dev', 'review'].includes(PARAMS.lane)) {
  throw new Error(`unsupported forge lane: ${PARAMS.lane}`)
}

const FINDING = {
  type: 'object', additionalProperties: false,
  properties: {
    file: { type: 'string' }, line: { type: 'integer' },
    severity: { type: 'string', enum: ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'] },
    claim: { type: 'string' }, fix_hint: { type: 'string' },
  },
  required: ['file', 'line', 'severity', 'claim', 'fix_hint'],
}
const REVIEW_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    verdict: { type: 'string', enum: ['approve', 'request_changes'] },
    score: { type: 'integer', minimum: 1, maximum: 5 },
    findings: { type: 'array', items: FINDING },
    disputes: {
      type: 'array', items: {
        type: 'object', additionalProperties: false,
        properties: { file: { type: 'string' }, line: { type: 'integer' }, reason: { type: 'string' } },
        required: ['file', 'line', 'reason'],
      },
    },
  },
  required: ['verdict', 'score', 'findings'],
}
const CODEX_RESULT = {
  type: 'object', additionalProperties: false,
  properties: {
    codexInvoked: { type: 'boolean' }, threadMode: { type: 'string', enum: ['start', 'resume'] },
    threadExists: { type: 'boolean' }, filesChanged: { type: 'array', items: { type: 'string' } },
    testsWritten: { type: 'integer' }, summary: { type: 'string' }, error: { type: 'string' },
  },
  required: ['codexInvoked', 'threadMode', 'threadExists', 'filesChanged', 'testsWritten', 'summary'],
}
const IMPL_RESULT = {
  type: 'object', additionalProperties: false,
  properties: {
    filesChanged: { type: 'array', items: { type: 'string' } },
    testsWritten: { type: 'boolean' }, summary: { type: 'string' },
    unverified: { type: 'array', items: { type: 'string' } },
    error: { type: ['string', 'null'] },
  },
  required: ['filesChanged', 'testsWritten', 'summary', 'unverified', 'error'],
}
const FORGE_CONFIG_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    roles: { type: 'object' },
    stages: { type: 'object' },
  },
  required: ['roles', 'stages'],
}
const CODEX_REVIEW_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    codexInvoked: { type: 'boolean' }, threadMode: { type: 'string', enum: ['start', 'resume'] },
    threadExists: { type: 'boolean' }, review: REVIEW_SCHEMA, error: { type: 'string' },
  },
  required: ['codexInvoked', 'threadMode', 'threadExists', 'review'],
}
const FIX_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    fixed: { type: 'array', items: { type: 'string' } },
    couldNotFix: { type: 'array', items: { type: 'string' } },
    touchedFiles: { type: 'array', items: { type: 'string' } },
    diff: { type: 'string' }, notes: { type: 'string' },
  },
  required: ['fixed', 'couldNotFix', 'touchedFiles', 'diff', 'notes'],
}
const CODEX_FIX_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    codexInvoked: { type: 'boolean' }, threadMode: { type: 'string', enum: ['start', 'resume'] },
    threadExists: { type: 'boolean' }, fix: FIX_SCHEMA, error: { type: 'string' },
  },
  required: ['codexInvoked', 'threadMode', 'threadExists', 'fix'],
}
const VERIFY_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    codexInvoked: { type: 'boolean' }, threadMode: { type: 'string', enum: ['resume'] },
    threadExists: { type: 'boolean' }, clean: { type: 'boolean' },
    results: {
      type: 'array', items: {
        type: 'object', additionalProperties: false,
        properties: {
          file: { type: 'string' }, line: { type: 'integer' },
          status: { type: 'string', enum: ['RESOLVED', 'STILL BROKEN', 'REBUTTAL ACCEPTED'] },
          reason: { type: 'string' },
        },
        required: ['file', 'line', 'status', 'reason'],
      },
    },
    unresolved: { type: 'array', items: FINDING }, error: { type: 'string' },
  },
  required: ['codexInvoked', 'threadMode', 'threadExists', 'clean', 'results', 'unresolved'],
}
const CONTEXT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    files: { type: 'array', items: { type: 'string' } }, commandSucceeded: { type: 'boolean' },
    diff: { type: 'string' }, planSummary: { type: 'string' },
    criteria: { type: 'array', items: { type: 'string' } },
    checklist: { type: 'string' }, standards: { type: 'string' },
    testPaths: { type: 'array', items: { type: 'string' } }, error: { type: 'string' },
    contract: { type: 'string' }, reviewerContract: { type: 'string' }, checkpointFindings: { type: 'string' },
  },
  required: ['files', 'commandSucceeded', 'diff', 'planSummary', 'criteria', 'checklist', 'standards', 'testPaths', 'reviewerContract', 'checkpointFindings'],
}
const GATE_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    passed: { type: 'boolean' },
    failures: {
      type: 'array', items: {
        type: 'object', additionalProperties: false,
        properties: { tool: { type: 'string' }, summary: { type: 'string' } },
        required: ['tool', 'summary'],
      },
    },
    commands: { type: 'array', items: { type: 'string' } },
    files: { type: 'array', items: { type: 'string' } }, diff: { type: 'string' },
    diffTruncated: { type: 'boolean' }, diffExcluded: { type: 'array', items: { type: 'string' } },
    diffPath: { type: 'string' }, diffBytes: { type: 'integer' },
    commit: {
      anyOf: [
        { type: 'null' },
        { type: 'object', additionalProperties: false, properties: { sha: { anyOf: [{ type: 'string' }, { type: 'null' }] }, pushed: { type: 'boolean' }, error: { type: 'string' } }, required: ['sha', 'pushed', 'error'] },
      ],
    },
  },
  required: ['passed', 'failures', 'commands'],
}
const PLAN_TEXT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { planText: { type: 'string' } }, required: ['planText'],
}
const SHIP_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    branch: { type: 'string' }, prUrl: { type: 'string' }, prNumber: { type: 'integer' }, repo: { type: 'string' },
    skipped: { type: 'boolean' }, reason: { type: 'string' },
  },
  required: ['branch', 'prUrl', 'prNumber', 'repo'],
}
const QA_DRAFT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    path: { type: 'string' }, items: { type: 'integer' }, opened: { type: 'boolean' }, error: { type: 'string' },
  },
  required: ['path', 'items', 'opened', 'error'],
}
const SANDBOX_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    skipped: { type: 'boolean' }, reason: { type: 'string' }, sandboxId: { type: 'string' },
    loginUrl: { type: 'string' }, previewUrl: { type: 'string' }, testsPassed: { type: 'boolean' }, summary: { type: 'string' },
    seedRecipe: { type: 'string' },
    mode: { type: 'string', enum: ['skip', 'git-fetch', 'hot-patch', 're-fork'] },
  },
  required: ['skipped', 'reason', 'sandboxId', 'loginUrl', 'previewUrl', 'testsPassed', 'summary', 'seedRecipe'],
}
const SIGN_IN_CRITERION = 'Signed-out check: in a fresh browser context with no stored session, open the preview URL and confirm the login page renders with no authenticated content. Fresh sign-in: open the login URL in that same context and confirm the authenticated landing page loads.'
const SMOKE_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    results: {
      type: 'array', items: {
        type: 'object', additionalProperties: false,
        properties: {
          criterion: { type: 'string' }, passed: { type: 'boolean' }, note: { type: 'string' }, screenshot: { type: 'string' },
        },
        required: ['criterion', 'passed', 'note', 'screenshot'],
      },
    },
  },
  required: ['results'],
}
const ACK_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { written: { type: 'boolean' } }, required: ['written'],
}
const HANDOFF_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { handoffPath: { type: 'string' } }, required: ['handoffPath'],
}

const LENSES = [
  { key: 'security', paths: /(auth|permission|identity|rbac|token|session)/i, prompt: 'Audit authentication, authorization, scoping, token/session handling, input trust, and privilege boundaries.' },
  { key: 'dx-audit', paths: /(views?|serializers?|urls?|routes?|clients?|api)\//i, skill: 'dx-audit' },
  { key: 'design-audit', paths: /\.tsx?$/i, skill: 'design-audit' },
]

function dryRunPlanText() {
  if (PARAMS.planText) return PARAMS.planText
  if (!PARAMS.checkpoints || !PARAMS.checkpoints.length) return '## Phase 0\n'
  const ranges = PARAMS.checkpoints.map(item => String(item.phases || '').match(/^(\d+)(?:-(\d+))?$/)).filter(Boolean)
  if (!ranges.length) return '## Phase 0\n'
  const first = Number(ranges[0][1])
  const last = Math.max(...ranges.map(match => Number(match[2] || match[1]))) + 1
  const phases = Array.from({ length: last - first + 1 }, (_, offset) => `## Phase ${first + offset}\n`)
  const checkpoints = PARAMS.checkpoints.map(item => `- Phases ${item.phases}: ${item.reason || ''}`)
  return `${phases.join('\n')}\n## Checkpoints\n${checkpoints.join('\n')}\n`
}

function dryFindings() {
  return Array.from({ length: PARAMS.dryRunFindings }, (_, index) => ({
    file: 'auth/api/client.py', line: index + 1, severity: 'HIGH',
    claim: `dry-run finding ${index + 1}`, fix_hint: 'fix the dry-run finding',
  }))
}

const STUBS = {
  implementer: () => ({ filesChanged: ['auth/api/client.py'], testsWritten: false, summary: 'dry-run Claude implementation', unverified: [], error: null }),
  reviewer: () => ({ verdict: PARAMS.dryRunFindings ? 'request_changes' : 'approve', score: PARAMS.dryRunFindings ? 2 : 5, findings: dryFindings(), disputes: [] }),
  spotReviewer: () => ({ verdict: 'approve', score: 5, findings: [], disputes: [] }),
  lens: () => ({ verdict: 'approve', score: 5, findings: [], disputes: [] }),
  qa: () => ({ passed: true, failures: [], commands: ['dry-run gate'], files: ['auth/api/client.py'], diff: 'dry-run checkpoint diff' }),
  gate: opts => PARAMS.dryRunFailGate === opts.label
    ? { passed: false, failures: [{ tool: 'tests', summary: 'dry-run forced failure' }], commands: ['dry-run gate'], files: ['auth/api/client.py'], diff: 'dry-run checkpoint diff', diffPath: `${PARAMS.runDir}/gate-dry-run.diff`, diffBytes: 23 }
    : { passed: true, failures: [], commands: ['dry-run gate'], files: ['auth/api/client.py'], diff: 'dry-run checkpoint diff', diffPath: `${PARAMS.runDir}/gate-dry-run.diff`, diffBytes: 23 },
  shipper: opts => opts.schema === ACK_SCHEMA
    ? { written: true }
    : { branch: `${PARAMS.ticket}-dry-run`, prUrl: 'https://example.invalid/pr/1', prNumber: 1, repo: PARAMS.repo || 'owner/repo' },
  qaDraft: () => ({ path: `${PARAMS.runDir}/qa-artifact.html`, items: 1, opened: false, error: '' }),
  sandboxQA: opts => opts.schema === ACK_SCHEMA
    ? { written: true }
    : { skipped: false, reason: '', sandboxId: 'dry-run-sandbox', loginUrl: 'https://example.invalid/login', previewUrl: 'https://example.invalid/preview', testsPassed: true, summary: 'dry-run sandbox passed', seedRecipe: '', mode: 'hot-patch' },
  smoke: opts => {
    const number = opts.label === 'smoke' ? 1 : Number(String(opts.label).split('-')[1] || 1)
    const criteria = smokeCriteria({ criteria: PARAMS.criteria }).slice((number - 1) * 6, number * 6)
    return { results: criteria.map(criterion => ({ criterion, passed: true, note: 'dry run', screenshot: `${PARAMS.runDir}/smoke/dry-run.png` })) }
  },
  changedFiles: opts => opts.schema === PLAN_TEXT_SCHEMA
    ? { planText: dryRunPlanText() }
    : opts.schema === FORGE_CONFIG_SCHEMA
    ? { roles: {}, stages: { sandbox: false, ff_review: false, qa_login: false } }
    : {
      files: ['auth/api/client.py'], commandSucceeded: true, diff: 'dry-run diff', planSummary: 'dry-run plan summary',
      criteria: PARAMS.criteria, checklist: 'dry-run checklist', standards: 'dry-run code standards', testPaths: ['tests/unit'], error: '',
      reviewerContract: 'dry-run reviewer contract', checkpointFindings: '',
    },
  readConfig: () => ({ roles: {}, stages: { sandbox: false, ff_review: false, qa_login: false } }),
  handoff: opts => opts.schema === ACK_SCHEMA ? { written: true } : { handoffPath: `${PARAMS.runDir}/handoff.md` },
  trim: () => ({ written: true }),
  codexWrap: opts => {
    if (opts.schema === CODEX_RESULT) return { codexInvoked: true, threadMode: 'start', threadExists: true, filesChanged: ['auth/api/client.py'], testsWritten: 0, summary: 'dry-run Codex', error: '' }
    if (opts.schema === CODEX_REVIEW_SCHEMA) return { codexInvoked: true, threadMode: 'start', threadExists: true, review: { verdict: PARAMS.dryRunFindings ? 'request_changes' : 'approve', score: PARAMS.dryRunFindings ? 2 : 5, findings: dryFindings(), disputes: [] }, error: '' }
    if (opts.schema === CODEX_FIX_SCHEMA) return { codexInvoked: true, threadMode: opts.label === 'fix-1' ? 'start' : 'resume', threadExists: true, fix: { fixed: [], couldNotFix: [], touchedFiles: PARAMS.dryRunFindings ? ['auth/api/client.py'] : [], diff: '', notes: 'dry-run fix' }, error: '' }
    if (opts.schema === VERIFY_SCHEMA) return { codexInvoked: true, threadMode: 'resume', threadExists: true, clean: !PARAMS.dryRunFindings, results: dryFindings().map(finding => ({ file: finding.file, line: finding.line, status: 'STILL BROKEN', reason: finding.claim })), unresolved: dryFindings(), error: '' }
    return { written: true }
  },
}

const decisions = []
const runtimeAgent = agent
let spawnCount = 0
let capBlocked = false

async function decide(text) {
  decisions.push(text)
}

function configRoleForTier(tierRole) {
  const mapped = ROLE_MAP[tierRole] || []
  if (tierRole === 'implementer') return PARAMS.lane === 'quick' ? 'quick-impl' : 'impl'
  return mapped[0] || null
}

function configuredRole(name) {
  return (FORGE_CONFIG && FORGE_CONFIG.roles && FORGE_CONFIG.roles[name]) || null
}

function configuredStage(name) {
  return Boolean(FORGE_CONFIG && FORGE_CONFIG.stages && FORGE_CONFIG.stages[name])
}

function tierProfile(tierRole) {
  const fallback = TIERS[PARAMS.tier][tierRole]
  const override = configuredRole(configRoleForTier(tierRole))
  if (!override || (override.provider && override.provider !== 'claude')) return fallback
  return { ...fallback, model: override.model || fallback.model, effort: override.effort || fallback.effort }
}

async function agentT(role, prompt, opts = {}) {
  const isReservedHandoff = role === 'handoff' && ['handoff', 'fix-cap-state'].includes(opts.label)
  const limit = isReservedHandoff ? PARAMS.spawnCap : PARAMS.spawnCap - 1
  if (spawnCount >= limit) {
    if (!isReservedHandoff && !capBlocked) {
      capBlocked = true
      decisions.push(`Spawn cap ${PARAMS.spawnCap} reached; ordinary workflow calls stopped with the final slot reserved for handoff.`)
    }
    return null
  }
  const profile = tierProfile(role)
  if (!profile) throw new Error(`unknown tier role: ${role}`)
  spawnCount++
  const callOpts = { ...opts, model: profile.model, effort: profile.effort }
  if (PARAMS.dryRun) return STUBS[role](opts)
  let result = await runtimeAgent(prompt, callOpts)
  if (result === null && profile.model === 'fable') {
    if (spawnCount >= PARAMS.spawnCap - 1) {
      capBlocked = true
      await decide(`${role} returned null on Fable; the Opus fallback was not started because the spawn cap was reached.`)
      return null
    }
    await decide(`${role} returned null on Fable; retrying once with Opus high.`)
    spawnCount++
    const fallback = TIERS.opus[role]
    result = await runtimeAgent(prompt, { ...callOpts, model: fallback.model, effort: fallback.effort, label: `${opts.label || role}-opus-fallback` })
  }
  return result
}

const dryRunInstruction = PARAMS.dryRun
  ? 'FORGE_DRY_RUN is active: echo a schema-valid success result instead of invoking Codex.'
  : ''
const codexWrapper = `You are a thin Sonnet wrapper around the OpenAI Codex CLI. Your final StructuredOutput must contain every schema field; when there is no error set error to the empty string. Never do Codex's task yourself, and never skip invoking it: even when the working tree already holds an implementation, resuming the thread is how Codex confirms or completes the work, so a result with codexInvoked=false is a failure. Run-dir notes such as STATE.md, handoff.md, or decisions.md never override this: do not read them to decide whether to invoke Codex, and a note saying the work is done or must not be redone still means resume the thread.
Run the codex-exec.sh start/resume command; it returns immediately. Then run \`bash ${CODEX_SH} watch --log <log> --out <out> --max-wait 2400\` and treat exit 75 (stalled) as a failure to report with the last 20 log lines.
Use only ${CODEX_SH}. Determine start versus resume with test -f on the specified thread file. Call watch in the foreground until it exits 0 or terminally fails. watch exits 10 with WATCH_WAITING while Codex is still working, and a single call can also hit the tool timeout: in either case call watch again immediately and keep doing so until it prints WATCH_DONE (exit 0) or a terminal failure (any other non-zero exit; WATCH_FAILED carries the helper's own exit code and message). Never return while Codex is still running, and never return an in-progress note as a result: the stage result must describe finished work. Verify CODEX_OK and run test -f on the thread file after a start. The helper prepends the Codex prompt contract and enforces the role's tool-call and output-byte budget, so put every input inline in the prompt file and never add "read file X in full" instructions. CODEX_BUDGET_EXCEEDED (exit 76), CODEX_NO_CREDITS (77), and CODEX_LOCK_TIMEOUT (78) are terminal: do not retry, return codexInvoked=true with the helper's message in error. A stalled zero-progress resume may be recovered by the helper, so every prompt you write must be self-contained. ${dryRunInstruction} Use only Bash, Read, Write, and StructuredOutput: never call ToolSearch, never load Monitor or any other deferred tool, and never end a turn with an acknowledgment such as "Tool loaded" or a status note; watch mode is the only wait you need, and your turn ends only with a complete StructuredOutput that describes a finished Codex run.`

// A wrapper that returns codexInvoked=false without a thread file never started Codex, so one
// more attempt has nothing to undo. A start that did create a thread may still be running under
// the helper's lock, and a null result means the spawn cap was hit; neither is retried.
async function codexAgent(prompt, opts) {
  const result = await agentT('codexWrap', prompt, opts)
  if (result === null || result.codexInvoked === true) return result
  if (result.threadMode === 'start' && result.threadExists === true) return result
  await decide(`${opts.label} wrapper returned without invoking Codex (${String(result.error || 'no error text').slice(0, 200)}); retrying once.`)
  return agentT('codexWrap', prompt, { ...opts, label: `${opts.label}-retry` })
}

function assertCodex(result, where) {
  if (capBlocked && !result) return false
  if (!result || result.codexInvoked !== true) {
    throw new Error(`Codex assertion failed at ${where}: ${(result && result.error) || 'wrapper returned null'}`)
  }
  if (result.threadMode === 'start' && result.threadExists !== true) {
    throw new Error(`Codex assertion failed at ${where}: expected thread file was not created`)
  }
  // A wrapper that gave up waiting reports codexInvoked=true with an explanatory error while
  // Codex is still running; downstream stages would then run against an unfinished tree.
  if (typeof result.error === 'string' && result.error.trim()) {
    throw new Error(`Codex assertion failed at ${where}: wrapper returned an error: ${result.error.slice(0, 300)}`)
  }
  return true
}

function assertImplementation(result, where) {
  const role = PARAMS.lane === 'quick' ? 'quick-impl' : 'impl'
  if ((configuredRole(role) || {}).provider !== 'claude') return assertCodex(result, where)
  if (!result || result.error) {
    throw new Error(`Claude implementation failed at ${where}: ${(result && result.error) || 'agent returned null'}`)
  }
  return true
}

function parseCheckpoints(planText, argsCheckpoints) {
  const phases = [...String(planText || '').matchAll(/^#{2,3}\s*Phase\s+(\d+)\b[^\n]*$/gmi)]
    .map(match => ({ number: Number(match[1]), index: match.index }))
  const fallback = () => [{
    from: phases.length ? phases[0].number : null,
    to: phases.length ? phases[phases.length - 1].number : null,
    reason: '', final: true,
  }]
  let entries
  if (Array.isArray(argsCheckpoints)) {
    if (!argsCheckpoints.length) return fallback()
    entries = argsCheckpoints.map(item => ({ phases: String(item && item.phases || ''), reason: String(item && item.reason || '') }))
  } else {
    const heading = /^#{2,}\s*Checkpoints\s*$/im.exec(String(planText || ''))
    if (!heading) return fallback()
    const afterHeading = String(planText).slice(heading.index + heading[0].length).replace(/^\r?\n/, '')
    const nextHeading = afterHeading.search(/^#{2,}\s+/m)
    const body = (nextHeading >= 0 ? afterHeading.slice(0, nextHeading) : afterHeading).trim()
    const lines = body.split(/\r?\n/).map(line => line.trim()).filter(Boolean)
    entries = lines.map(line => {
      const match = /^-\s*Phases?\s+(\d+(?:-\d+)?)\s*:\s*(.+)$/i.exec(line)
      return match && { phases: match[1], reason: match[2].trim() }
    })
  }
  const invalid = () => {
    decide('Checkpoint plan format invalid; falling back to a single implementation segment.')
    return fallback()
  }
  if (!phases.length || !entries.length || entries.some(entry => !entry)) return invalid()
  const numbers = phases.map(item => item.number)
  const found = new Set(numbers)
  if (found.size !== numbers.length || numbers.some((number, index) => index && number <= numbers[index - 1])) return invalid()
  const segments = []
  let expected = numbers[0]
  for (const entry of entries) {
    const range = /^(\d+)(?:-(\d+))?$/.exec(entry.phases.trim())
    if (!range || !entry.reason.trim()) return invalid()
    const from = Number(range[1])
    const to = Number(range[2] || range[1])
    if (from !== expected || to < from) return invalid()
    for (let number = from; number <= to; number++) if (!found.has(number)) return invalid()
    segments.push({ from, to, reason: entry.reason.trim(), final: false })
    expected = to + 1
  }
  const last = numbers[numbers.length - 1]
  if (expected <= last) {
    for (let number = expected; number <= last; number++) if (!found.has(number)) return invalid()
    segments.push({ from: expected, to: last, reason: '', final: true })
  } else if (expected === last + 1) {
    segments[segments.length - 1].final = true
  } else {
    return invalid()
  }
  return segments
}

function planPhases(planText, segment) {
  if (!segment || segment.from === null || segment.to === null) return String(planText || '')
  const headings = [...String(planText || '').matchAll(/^#{2,3}\s*Phase\s+(\d+)\b[^\n]*$/gmi)]
  const first = headings.findIndex(match => Number(match[1]) === segment.from)
  const after = headings.findIndex(match => Number(match[1]) > segment.to)
  if (first < 0) return ''
  return String(planText).slice(headings[first].index, after < 0 ? undefined : headings[after].index).trim()
}

function planCriteria(planText) {
  if (PARAMS.criteria.length) return JSON.stringify(PARAMS.criteria)
  const heading = /^#{2,}\s*Acceptance Criteria\s*$/im.exec(String(planText || ''))
  if (!heading) return '(none declared)'
  const rest = String(planText).slice(heading.index + heading[0].length).replace(/^\r?\n/, '')
  const nextHeading = rest.search(/^#{2,}\s+/m)
  return (nextHeading >= 0 ? rest.slice(0, nextHeading) : rest).trim()
}

function readPlan() {
  return agentT('changedFiles', `Read ${PLAN} completely with ranged sed reads only; keep each range under 200 lines and the total under 1500 lines. Do not read or change repository files. If the file is longer than 1500 lines, return what you read and append the line [TRUNCATED] at the end of planText. Return the plan's exact text unchanged as planText.`,
  { label: 'read-plan', phase: 'Implement', schema: PLAN_TEXT_SCHEMA })
}

async function loadForgeConfig() {
  if (FORGE_CONFIG) return
  const result = await agentT('readConfig', `Read ~/.claude/skills/forge/forge.config.json with a ranged sed read. Return only its roles and stages objects. If it is missing or invalid, return empty roles and all stages false. Do not read repository files.`,
    { label: 'read-config', phase: 'Implement', schema: FORGE_CONFIG_SCHEMA })
  FORGE_CONFIG = result || { roles: {}, stages: { sandbox: false, ff_review: false, qa_login: false } }
}

function segmentThread(index) {
  return index === 0 ? CODEX_IMPL_THREAD : `${PARAMS.runDir}/codex-impl-cp${index + 1}.thread`
}

function implement(segment, index, total, pendingCheckpointLines = [], previousResult = null) {
  const implementationRole = PARAMS.lane === 'quick' ? 'quick-impl' : 'impl'
  if ((configuredRole(implementationRole) || {}).provider === 'claude') {
    const findings = pendingCheckpointLines.length ? JSON.stringify(pendingCheckpointLines) : '[]'
    return agentT('implementer', `Implement this confirmed Forge plan segment in ${PARAMS.projectDir}. Never commit or ship. Run only the quick checks required by the plan. Write the implementation summary to ${PARAMS.runDir}/implementation-summary.md. Report live-dependent capabilities under unverified.\n\nPLAN SEGMENT\n${planPhases(PARAMS.planText, segment)}\n\nCHECKPOINT FINDINGS\n${findings}`,
      { label: index === 0 ? 'implement' : `implement-cp${index + 1}`, phase: 'Implement', schema: IMPL_RESULT, agentType: 'implementer' })
  }
  const indexedPaths = total > 1 || Boolean(segment.reason)
  const promptPath = indexedPaths ? `${PARAMS.runDir}/implement-prompt-${index}.md` : `${PARAMS.runDir}/implement-prompt.md`
  const logPath = indexedPaths ? `${PARAMS.runDir}/codex-implement-${index}.jsonl` : `${PARAMS.runDir}/codex-implement.jsonl`
  const outPath = indexedPaths ? `${PARAMS.runDir}/codex-implement-${index}-final.md` : `${PARAMS.runDir}/codex-implement-final.md`
  const scope = total > 1
    ? `\nAdd this block to the Codex prompt verbatim:\nPHASES IN SCOPE NOW: Phase ${segment.from} .. Phase ${segment.to} (segment ${index + 1} of ${total}). Implement only these phases. Do not start later phases. When done, report filesChanged for this segment only.`
    : ''
  const persistFindings = pendingCheckpointLines.length
    ? `Before invoking Codex, append each missing exact line from ${JSON.stringify(pendingCheckpointLines)} to ${PARAMS.runDir}/checkpoint-findings.md, creating it if needed and never truncating or duplicating existing lines.\n`
    : ''
  const threadFile = segmentThread(index)
  const previous = index > 0
    ? `Include only this previous segment summary verbatim in the Codex prompt: ${JSON.stringify((previousResult && previousResult.summary) || '')}. Name ${PARAMS.runDir}/gate-cp${index}.diff, ${PARAMS.runDir}/gate-cp${index}-retry.diff, and ${PARAMS.runDir}/gate-cp${index}-retry2.diff as optional paths Codex may inspect with ranged sed -n reads. Do not read or inline those diffs while building the prompt.\n`
    : ''
  const mode = index === 0 ? `test -f ${threadFile} && MODE=resume || MODE=start` : 'MODE=start'
  return codexAgent(`You orchestrate the IMPLEMENT stage. ${codexWrapper}
Read ~/.claude/skills/forge/references/implementer.md and ~/.claude/skills/forge/references/code-standards.md in full. Write ${promptPath} as a self-contained Codex prompt containing the implementer contract, then the code-standards contents verbatim, then the full text of ${PLAN} under a PLAN heading and of ${PARAMS.runDir}/context.md (if present) under a CONTEXT heading, and of ${PARAMS.runDir}/recon.md (if present) under a RECON heading.${scope} ${previous}Do not tell Codex to read those files, AGENTS.md, or CLAUDE.md; Codex loads AGENTS.md itself. Implement only the confirmed plan and its test strategy. Before returning, run ruff check, ruff format --check, makemigrations --check, and semgrep on the files touched, skipping Semgrep when missing; fix what they report. Do not run pytest or anything that needs Postgres or Redis, because the Codex sandbox has no network access, localhost included, so those runs are the gate's job. The gate remains the authority. Do not commit, and write ${PARAMS.runDir}/implementation-summary.md. If ${PLAN} declares a Phase 0 evidence harness, build it first and keep it runnable; report every live-dependent capability as implemented-unverified — a worker-run harness against a live target is what marks it verified.
${persistFindings}Run ${mode}, then invoke exactly: bash ${CODEX_SH} "$MODE" --thread-file ${threadFile} --prompt-file ${promptPath} --cd ${PARAMS.projectDir} --sandbox workspace-write --writable ${PARAMS.runDir} ${CODEX_IMPL_FLAGS} --log ${logPath} --out ${outPath}. Collect changed and untracked files. Return the structured result.`,
  { label: index === 0 ? 'implement' : `implement-cp${index + 1}`, phase: 'Implement', schema: CODEX_RESULT })
}

function localGate(label = 'gate', gatePhase = 'Gate', files = []) {
  const quote = value => `'${String(value).replace(/'/g, `'\\''`)}'`
  const filesArg = files.length ? ` --files ${files.map(quote).join(' ')}` : ''
  return agentT('gate', `Run exactly: \`bash ~/.claude/skills/forge/scripts/gate.sh --repo ${quote(PARAMS.projectDir)} --run-dir ${quote(PARAMS.runDir)} --label ${label}${filesArg}\`. Return its stdout JSON as your structured output without changes. If the script exits 2 or prints no JSON, return \`{ passed: false, failures: [{ tool: 'gate.sh', summary: <stderr tail> }], commands: [] }\`.`,
  { label, phase: gatePhase, schema: GATE_SCHEMA })
}

function gateFindings(gate) {
  return (gate.failures || []).map(failure => ({
    file: '', line: 0, severity: 'HIGH', claim: `${failure.tool}: ${failure.summary}`, fix_hint: 'Resolve this gate failure only.',
  }))
}

async function gateWithFixes(label, files, threadFile, context, phaseLabel) {
  let gate = await localGate(label, phaseLabel, files)
  const touchedFiles = []
  for (let round = 1; round <= 2 && (!gate || !gate.passed); round++) {
    const fixLabel = round === 1 ? `fix-${label}` : `fix-${label}-2`
    const retryLabel = round === 1 ? `${label}-retry` : `${label}-retry2`
    const fix = await fixAgent(
      gateFindings(gate || { failures: [{ tool: 'gate', summary: 'agent returned null' }] }),
      context,
      fixLabel,
      threadFile,
      phaseLabel,
    )
    if (!fix) return { gate, touchedFiles, blocked: true, capReached: false }
    touchedFiles.push(...(fix.touchedFiles || []))
    files = [...new Set([...files, ...(fix.touchedFiles || [])])]
    gate = await localGate(retryLabel, phaseLabel, files)
  }
  return { gate, touchedFiles, blocked: false, capReached: !gate || !gate.passed }
}

async function recordFixCap(gate, threadFile, branch, findings = []) {
  const gateFailures = (gate && gate.failures) || []
  const failures = [...new Set([
    ...gateFailures.map(item => `${item.tool}: ${String(item.summary).slice(0, 200)}`),
    ...findings.map(item => {
      const claim = String(item.claim).slice(0, 200)
      return item.file ? `${item.file}:${item.line || 0} ${claim}` : claim
    }),
  ])]
  const diffPath = (gate && gate.diffPath) || `${PARAMS.runDir}/gate-gate.diff`
  await decide(`Fix cap reached; failures: ${failures.join(' | ') || 'no failure detail'}; gate diff: ${diffPath}.`)
  if (PARAMS.auto) {
    await agentT('handoff', `Rewrite ${PARAMS.runDir}/STATE.md from ~/.claude/references/state-template.md. Add a "Fix cap reached" block with this failure list: ${JSON.stringify(failures)}; gate diffPath=${diffPath}; fix thread=${threadFile}; branch=${branch || '(unknown branch)'}. Preserve the template's other required state and pointer fields. Return written=true.`,
    { label: 'fix-cap-state', phase: 'Handoff', schema: ACK_SCHEMA })
    return 'READY_FOR_HUMAN'
  }
  return 'BLOCKED'
}

function stopped(state) {
  return state.status === 'BLOCKED' || state.status === 'READY_FOR_HUMAN'
}

function changedFiles(checkpointLines = []) {
  return agentT('changedFiles', `You collect the exact Forge review inputs. Do not review or edit code. Work in ${PARAMS.projectDir}.
1. Collect file paths and a complete textual diff, including staged and untracked files. For lane ${PARAMS.lane}, ${PARAMS.lane === 'review' ? 'review uncommitted changes against HEAD' : 'resolve the branch base and review the merge-base-to-HEAD branch diff plus any uncommitted changes'}.
2. Read ${PLAN} if present. Return its ## Summary section, or its first 4000 characters when absent.
3. Acceptance criteria are this args array when non-empty: ${JSON.stringify(PARAMS.criteria)}. Otherwise extract the plan's ## Acceptance Criteria section.
4. Read and return the complete contents of ~/.claude/skills/forge/references/review-checklist.md, ~/.claude/skills/forge/references/code-standards.md, and ~/.claude/skills/forge/references/claude-reviewer-contract.md. Return the last file as reviewerContract.
5. Extract plan-specified pytest paths; fall back to tests/unit.
6. Extract the plan's ## Public API contract section verbatim as field contract; return an empty string when absent.
7. Append each missing line from ${JSON.stringify(checkpointLines)} to ${PARAMS.runDir}/checkpoint-findings.md, creating it if needed. Do not duplicate an existing line. Return the file's complete text as checkpointFindings, or an empty string when it has no content.
Return per schema.`,
  { label: 'changed-files', phase: 'Review', schema: CONTEXT_SCHEMA })
}

function planSummary(context) {
  return (context.planSummary || '').slice(0, 4000)
}

function acceptanceCriteria(context) {
  return PARAMS.criteria.length ? PARAMS.criteria : (context.criteria || [])
}
function smokeCriteria(context) {
  return configuredStage('qa_login')
    ? [SIGN_IN_CRITERION, ...acceptanceCriteria(context)]
    : acceptanceCriteria(context)
}

function contextFailed(context) {
  return !context || context.commandSucceeded !== true
}

// Reviewers get the whole diff inline; a diff past this size is cut and the reviewer told so,
// since an unbounded prompt is what lets a session grow past its budget.
const DIFF_CAP = 160000

function boundedDiff(context) {
  const diff = String(context.diff || '')
  if (diff.length <= DIFF_CAP) return diff
  decide(`Review diff truncated from ${diff.length} to ${DIFF_CAP} characters; reviewers were told which part is missing.`)
  return `${diff.slice(0, DIFF_CAP)}\n[DIFF TRUNCATED at ${DIFF_CAP} of ${diff.length} characters; changed files: ${JSON.stringify(context.files || [])}. Read the rest only with ranged sed on the listed files.]`
}

function segmentDiffContext(context) {
  const diff = String(context.diff || '')
  if (diff) {
    const excluded = context.diffExcluded && context.diffExcluded.length
      ? JSON.stringify(context.diffExcluded)
      : 'none'
    const truncated = context.diffTruncated
      ? `\n[DIFF TRUNCATED: first ${diff.length} characters shown of ${context.diffBytes || 0} bytes; the rest is at ${context.diffPath}, read it with ranged sed]`
      : ''
    return `DIFF (working tree vs HEAD; files: ${JSON.stringify(context.files || [])}; excluded generated files: ${excluded})\n${diff}${truncated}`
  }
  return context.diffPath
    ? `The segment diff is at ${context.diffPath} (${context.diffBytes || 0} bytes); read it with ranged sed`
    : ''
}

function knownFindingsContext(context) {
  const findings = String(context.checkpointFindings || '').trim()
  return findings
    ? `Known from checkpoint reviews (verify fixed or still open; do not re-report as new)\n${findings}`
    : ''
}

function spotReview(segment, index, total, planText, gate) {
  const context = {
    files: gate.files || [], diff: gate.diff || '', diffTruncated: !!gate.diffTruncated,
    diffExcluded: gate.diffExcluded || [], diffPath: gate.diffPath || '', diffBytes: gate.diffBytes || 0,
    checkpointFindings: '',
  }
  return agentT('spotReviewer', `Review only checkpoint ${index + 1} of ${total}. You are read-only. Use ranged reads only to confirm a file:line, run no git commands, and use at most 30 tool calls. Do not inspect other review findings.

PROJECT DIR
${PARAMS.projectDir}
Every path in the diff and in your findings is relative to this directory. Confirm a file:line only with an absolute path under it (sed -n 'A,Bp' ${PARAMS.projectDir}/<path>); never resolve a path against your own working directory.

PHASES IN SCOPE
${planPhases(planText, segment)}

CHECKPOINT REASON
${segment.reason}

ACCEPTANCE CRITERIA
${planCriteria(planText)}

${segmentDiffContext(context)}

Check only:
1. Does the code match the plan's contract for these phases (names, shapes, endpoints, flags)?
2. Any test weakened, skipped, deleted, or asserting a mock? Any plan-required test missing?
3. Obvious correctness defects in the diff.

Nothing else: no style, no docs, and no speculative refactors. Return exactly the review schema.`,
  { label: `spot-review-cp${index + 1}`, phase: 'Review', schema: REVIEW_SCHEMA, agentType: 'spot-reviewer' })
}

function reviewerPrompt(identity, focus, context) {
  return `${identity === 'Codex general' ? '' : `${context.reviewerContract}\n\n`}You are the ${identity} reviewer. Review independently; do not inspect review transcripts or other reviewers' findings. ${focus} Ground findings in your own evidence: if ${PARAMS.runDir}/STATUS.json or harness output files (selfcheck*.json, parity.json, smoke/) exist, read them; never rely on the implementer's or fixer's summary. The diff below is complete unless marked truncated; read repository files only to confirm a specific file:line it touches, with ranged reads.
Use disputes only for a concrete concern at a file:line that you examined and explicitly reject, with the evidence in reason. Return exactly the review schema.

PROJECT DIR
${PARAMS.projectDir}
Every path in the diff and in your findings is relative to this directory. Confirm a file:line only with an absolute path under it (sed -n 'A,Bp' ${PARAMS.projectDir}/<path>); never resolve a path against your own working directory.

DIFF
${boundedDiff(context)}

PLAN SUMMARY
${planSummary(context)}

PUBLIC API CONTRACT (score the implementation against this; deviations are findings):
${context.contract || '(none declared)'}

ACCEPTANCE CRITERIA
${JSON.stringify(acceptanceCriteria(context))}

REVIEW CHECKLIST
${context.checklist}

FLAG VIOLATIONS OF THESE CODE STANDARDS
${context.standards}${knownFindingsContext(context) ? `\n\n${knownFindingsContext(context)}` : ''}`
}

async function codexReview(context) {
  const review = reviewerPrompt('Codex general', 'Assess every checklist item and acceptance criterion.', context)
  const result = await codexAgent(`You orchestrate the CODEX general review. ${codexWrapper}
Write ${PARAMS.runDir}/codex-review-prompt.md with the exact reviewer prompt below; add nothing (the helper prepends the prompt contract). Run test -f ${CODEX_REVIEW_THREAD} && MODE=resume || MODE=start, then invoke exactly: bash ${CODEX_SH} "$MODE" --thread-file ${CODEX_REVIEW_THREAD} --prompt-file ${PARAMS.runDir}/codex-review-prompt.md --cd ${PARAMS.projectDir} --sandbox read-only ${CODEX_REVIEW_FLAGS} --log ${PARAMS.runDir}/codex-review.jsonl --out ${PARAMS.runDir}/codex-review-final.md. Return invocation evidence plus Codex's REVIEW_SCHEMA result in the wrapper schema without adding findings.

${review}`,
  { label: 'review-codex', phase: 'Review', schema: CODEX_REVIEW_SCHEMA })
  // A Codex failure (out of credits, auth, stall) must surface as a named failure, not as
  // the placeholder verdict the wrapper returns alongside its `error` field.
  try {
    if (!assertCodex(result, 'review')) return null
  } catch (error) {
    await decide(`Codex review did not run: ${error.message}`)
    return null
  }
  if (result.error) {
    await decide(`Codex review did not run: ${result.error}`)
    return null
  }
  return result.review
}

const REVIEW_TIMEOUT_MS = 25 * 60 * 1000

function withTimeout(promise, ms, label) {
  if (typeof setTimeout !== 'function') return promise
  let timer
  const timeout = new Promise(resolve => {
    timer = setTimeout(() => {
      decide(`${label} produced nothing for ${Math.round(ms / 60000)} min; treated as FAIL so the run can continue.`)
      resolve(null)
    }, ms)
  })
  return Promise.race([promise.finally(() => clearTimeout(timer)), timeout])
}

function claudeReview(context) {
  return agentT('reviewer', reviewerPrompt('Claude general', 'Assess every checklist item and acceptance criterion.', context),
    { label: 'review-claude', phase: 'Review', schema: REVIEW_SCHEMA, agentType: 'reviewer' })
}

function lensReview(lens, context) {
  const skill = lens.skill
    ? `If ~/.claude/skills/${lens.skill}/SKILL.md exists, read it and every lenses/*.md beneath that skill and apply them. If absent, fall back to a generic ${lens.key} audit.`
    : lens.prompt
  return agentT('lens', reviewerPrompt(`${lens.key} lens`, `${skill} Report only ${lens.key} concerns.`, context),
    { label: `lens-${lens.key}`, phase: 'Review', schema: REVIEW_SCHEMA })
}

function detectContradictions(rows) {
  const contradictions = []
  for (const source of rows) {
    for (const finding of source.result.findings || []) {
      if (!['HIGH', 'CRITICAL'].includes(finding.severity)) continue
      for (const other of rows) {
        if (other.key === source.key) continue
        const dispute = (other.result.disputes || []).find(item => item.file === finding.file && item.line === finding.line)
        if (dispute) contradictions.push({ finding, raisedBy: source.key, dispute, disputedBy: other.key })
      }
    }
  }
  return contradictions
}

function uniqueFindings(rows) {
  const seen = new Set()
  const findings = []
  for (const row of rows) for (const finding of row.result.findings || []) {
    const key = JSON.stringify([finding.file, finding.line, finding.claim])
    if (!seen.has(key)) {
      seen.add(key)
      findings.push({ ...finding, reviewer: row.key })
    }
  }
  return findings
}

async function applyRulings(findings, contradictions) {
  const dropped = new Set()
  const unresolved = []
  for (const contradiction of contradictions) {
    const finding = contradiction.finding
    const ruling = (PARAMS.rulings || []).find(item => item.file === finding.file && item.line === finding.line)
    if (ruling) {
      if (ruling.decision === 'drop') dropped.add(JSON.stringify([finding.file, finding.line]))
    } else if (PARAMS.auto) {
      await decide(`Auto ruling applied ${finding.file}:${finding.line} conservatively: ${finding.claim}`)
    } else {
      unresolved.push(contradiction)
    }
  }
  return {
    unresolved,
    confirmed: findings.filter(finding => !dropped.has(JSON.stringify([finding.file, finding.line]))),
  }
}

async function reviewPanel(context) {
  const selected = LENSES.filter(lens => (context.files || []).some(file => lens.paths.test(file)))
  const reviewProvider = (configuredRole('review') || {}).provider || 'codex'
  const specs = []
  if (reviewProvider === 'codex') specs.push({ key: 'codex', lens: false, run: () => codexReview(context) })
  if (reviewProvider === 'claude' || PARAMS.lane === 'dev') specs.push({ key: 'claude', lens: false, run: () => claudeReview(context) })
  for (const lens of selected) specs.push({ key: lens.key, lens: true, run: () => lensReview(lens, context) })
  // A reviewer that never returns (a hung model call) must not hang the run: after
  // REVIEW_TIMEOUT_MS it is treated as FAIL and the panel proceeds without it.
  const raw = await parallel(specs.map(spec => () => withTimeout(spec.run(), REVIEW_TIMEOUT_MS, `review:${spec.key}`)))
  const present = raw.filter(Boolean)
  const rows = specs.map((spec, index) => raw[index] ? { key: spec.key, result: raw[index] } : null).filter(Boolean)
  const failures = specs.flatMap((spec, index) => raw[index] ? [] : [{ key: spec.key, status: 'FAIL', reason: 'agent returned null' }])
  const findings = uniqueFindings(rows)
  const disputes = detectContradictions(rows)
  const ruled = await applyRulings(findings, disputes)
  return { reviews: rows, findings, disputes, unresolvedDisputes: ruled.unresolved, confirmed: ruled.confirmed, failures, returned: present.length }
}

function unresolvedAfterVerification(items, verify) {
  const unresolved = []
  const malformed = !Array.isArray(verify.results) || verify.results.length === 0
  for (const finding of items) {
    if (malformed) { unresolved.push(finding); continue }
    const matches = verify.results.filter(result => result.file === finding.file && result.line === finding.line)
    if (matches.length === 0 || matches.some(match => match.status === 'STILL BROKEN')) unresolved.push(finding)
  }
  const seen = new Set(unresolved.map(finding => JSON.stringify([finding.file, finding.line, finding.claim])))
  for (const finding of verify.unresolved || []) {
    const key = JSON.stringify([finding.file, finding.line, finding.claim])
    if (!seen.has(key)) {
      seen.add(key)
      unresolved.push(finding)
    }
  }
  return unresolved
}

async function fixAgent(items, context, label, threadFile, fixPhase = 'Fix') {
  const round = label === 'fix-2' ? 2 : 1
  const reviewDiffPath = (context && context.diffPath) || `${PARAMS.runDir}/gate-gate.diff`
  const implementationRole = PARAMS.lane === 'quick' ? 'quick-impl' : 'impl'
  if ((configuredRole(implementationRole) || {}).provider === 'claude') {
    const result = await agentT('implementer', `Fix only these confirmed findings in ${PARAMS.projectDir}: ${JSON.stringify(items)}. Verify each against current code first. Do not commit or ship. Run only quick checks that need no services.`,
      { label, phase: fixPhase, schema: IMPL_RESULT, agentType: 'implementer' })
    if (!result || result.error) return null
    return { fixed: items.map(item => item.claim), couldNotFix: [], touchedFiles: result.filesChanged, diff: '', notes: result.summary }
  }
  const mode = threadFile === CODEX_FIX_THREAD && label === 'fix-1'
    ? 'MODE=start'
    : `test -f ${threadFile} && MODE=resume || MODE=start`
  const result = await codexAgent(`You orchestrate FIX ROUND ${round} (${label}). ${codexWrapper}
Read ~/.claude/skills/forge/references/code-standards.md in full. Write ${PARAMS.runDir}/${label}-prompt.md as a self-contained Codex prompt containing those standards verbatim, this confirmed file:line finding list as JSON, and the instruction to verify each claim against current code and fix only findings that are real: ${JSON.stringify(items)}. With ranged reads, include ${PARAMS.runDir}/implementation-summary.md when present and the review diff at ${reviewDiffPath} when present. Do not refactor adjacent code or commit. Before returning, run ruff check, ruff format --check, makemigrations --check, and semgrep on the files touched, skipping Semgrep when missing; fix what they report. Do not run pytest or anything that needs Postgres or Redis, because the Codex sandbox has no network access, localhost included, so those runs are the gate's job. The gate remains the authority. A failure caused by an unreachable service (Redis, Postgres, Docker, network, a missing binary) is environmental: list it under couldNotFix with the evidence and never change tests, fixtures, caches, or settings to route around it. Work in ${PARAMS.projectDir}.
Run ${mode}, then invoke exactly: bash ${CODEX_SH} "$MODE" --thread-file ${threadFile} --prompt-file ${PARAMS.runDir}/${label}-prompt.md --cd ${PARAMS.projectDir} --sandbox workspace-write --writable ${PARAMS.runDir} ${CODEX_IMPL_FLAGS} --log ${PARAMS.runDir}/codex-${label}.jsonl --out ${PARAMS.runDir}/codex-${label}-final.md. Return invocation evidence plus touched files and git diff limited to 12000 characters in the wrapper schema.`,
  { label, phase: fixPhase, schema: CODEX_FIX_SCHEMA })
  if (!assertCodex(result, label)) return null
  return result.fix
}

function verifyFixes(items, fixResult, round) {
  const diff = String(fixResult.diff || '').slice(0, 12000)
  if ((configuredRole('review') || {}).provider === 'claude') {
    return agentT('reviewer', `Verify only these findings after the fix: ${JSON.stringify(items)}. Inspect the current code and mark each result RESOLVED, STILL BROKEN, or REBUTTAL ACCEPTED. Raise no new findings.`,
      { label: `verify-${round}`, phase: 'Fix', schema: VERIFY_SCHEMA, agentType: 'reviewer' })
  }
  return codexAgent(`You orchestrate FIX VERIFICATION ROUND ${round}. ${codexWrapper}
Write ${PARAMS.runDir}/verify-${round}-prompt.md as a self-contained Codex prompt with the confirmed findings below and the fix diff. Ask the reviewer to mark every finding, including findings raised by the Fable reviewer, RESOLVED, STILL BROKEN, or REBUTTAL ACCEPTED. Verify only these findings; test execution belongs to the gate. Do not raise new findings. Verify against the code and any harness evidence in ${PARAMS.runDir} (STATUS.json, selfcheck*.json); a finding is RESOLVED only if you can point at the changed code, not because the fixer said so.
FINDINGS: ${JSON.stringify(items)}
FIX DIFF (capped at 12000 characters): ${diff}
Run test -f ${CODEX_REVIEW_THREAD} && MODE=resume || MODE=start. This stage must resume the review thread, so if MODE is start, return an invocation error instead of running. Otherwise invoke exactly: bash ${CODEX_SH} "$MODE" --thread-file ${CODEX_REVIEW_THREAD} --prompt-file ${PARAMS.runDir}/verify-${round}-prompt.md --cd ${PARAMS.projectDir} --sandbox read-only ${CODEX_REVIEW_FLAGS} --log ${PARAMS.runDir}/codex-verify-${round}.jsonl --out ${PARAMS.runDir}/codex-verify-${round}-final.md. Translate without changing the verdicts.`,
  { label: `verify-${round}`, phase: 'Fix', schema: VERIFY_SCHEMA })
}

function assertVerification(result, where) {
  if ((configuredRole('review') || {}).provider === 'claude') {
    if (!result || result.error) throw new Error(`Claude verification failed at ${where}`)
    return true
  }
  return assertCodex(result, where)
}

async function converge(panel, context) {
  let unresolved = panel.confirmed || []
  let fixesApplied = false
  const rounds = []
  const touched = []
  if (!unresolved.length) {
    await decide('Fix stage skipped because the review panel returned no confirmed findings.')
    return { unresolved, fixesApplied, rounds, touchedFiles: touched, blocked: false, capReached: false, gatePassed: true, gate: null, gateRan: false }
  }
  const fix = await fixAgent(unresolved, context, 'fix-1', CODEX_FIX_THREAD)
  if (!fix) return { unresolved, fixesApplied, rounds, touchedFiles: touched, blocked: true, capReached: false, gatePassed: false, gate: null, gateRan: false }
  fixesApplied = (fix.touchedFiles || []).length > 0
  touched.push(...(fix.touchedFiles || []))
  const gate = await localGate('gate-fix-1', 'Fix')
  const verify = await verifyFixes(unresolved, fix, 1)
  if (!assertVerification(verify, 'verify-1')) return { unresolved, fixesApplied, rounds, touchedFiles: touched, blocked: true, capReached: false, gatePassed: Boolean(gate && gate.passed), gate, gateRan: Boolean(gate) }
  unresolved = unresolvedAfterVerification(unresolved, verify)
  if (!gate || !gate.passed) unresolved = [...unresolved, ...gateFindings(gate || { failures: [{ tool: 'gate', summary: 'agent returned null' }] })]
  rounds.push({ round: 1, fix, gate, verify })
  await writeStatus({
    rounds: { fix: 1 },
    open_findings: unresolved.map(finding => ({ file: finding.file, line: finding.line, severity: finding.severity, summary: finding.claim })),
  }, 'Fix')
  if (!unresolved.length) return { unresolved, fixesApplied, rounds, touchedFiles: touched, blocked: false, capReached: false, gatePassed: Boolean(gate && gate.passed), gate, gateRan: Boolean(gate) }

  const fix2 = await fixAgent(unresolved, context, 'fix-2', CODEX_FIX_THREAD)
  if (!fix2) return { unresolved, fixesApplied, rounds, touchedFiles: touched, blocked: true, capReached: false, gatePassed: Boolean(gate && gate.passed), gate, gateRan: Boolean(gate) }
  fixesApplied = fixesApplied || (fix2.touchedFiles || []).length > 0
  touched.push(...(fix2.touchedFiles || []))
  const gate2 = await localGate('gate-fix-2', 'Fix')
  const verify2 = await verifyFixes(unresolved, fix2, 2)
  if (!assertVerification(verify2, 'verify-2')) return { unresolved, fixesApplied, rounds, touchedFiles: touched, blocked: true, capReached: false, gatePassed: Boolean(gate2 && gate2.passed), gate: gate2, gateRan: Boolean(gate2) }
  unresolved = unresolvedAfterVerification(unresolved, verify2)
  if (!gate2 || !gate2.passed) unresolved = [...unresolved, ...gateFindings(gate2 || { failures: [{ tool: 'gate', summary: 'agent returned null' }] })]
  rounds.push({ round: 2, fix: fix2, gate: gate2, verify: verify2 })
  await writeStatus({
    rounds: { fix: 2 },
    open_findings: unresolved.map(finding => ({ file: finding.file, line: finding.line, severity: finding.severity, summary: finding.claim })),
  }, 'Fix')
  if (!unresolved.length) return { unresolved, fixesApplied, rounds, touchedFiles: touched, blocked: false, capReached: false, gatePassed: Boolean(gate2 && gate2.passed), gate: gate2, gateRan: Boolean(gate2) }
  return { unresolved, fixesApplied, rounds, touchedFiles: touched, blocked: true, capReached: true, gatePassed: Boolean(gate2 && gate2.passed), gate: gate2, gateRan: Boolean(gate2) }
}

// The working tree can carry unrelated local work, including tracked secret-bearing env
// files; the shipper stages only the run's own files, never "whatever git status shows".
function stagingRules(files) {
  const list = files.length ? `Stage EXACTLY these paths, with 'git add -- <path> ...' and nothing else: ${JSON.stringify(files)}. A listed path that does not exist is skipped and reported.` : 'Stage only the files this run changed.'
  return `${list} Never run 'git add -A', 'git add -u', or 'git add .'. Never stage any path under '.envs/', any '*.env*' file, or any file outside that list even if 'git status' shows it modified or untracked.`
}

function ship(existing = null, files = []) {
  const dependency = PARAMS.dependsOnGate
    ? `Before creating a branch or pushing, poll ${PARAMS.dependsOnGate} every 60 seconds for up to 30 minutes. Continue only after it exists and its JSON field passed is true. Otherwise return {branch:"",prUrl:"",prNumber:0,repo:${JSON.stringify(PARAMS.repo)},skipped:true,reason:"waited on ${PARAMS.dependsOnGate}; API gate never passed"} without creating a branch, committing, pushing, or editing a PR. `
    : ''
  const prompt = existing
    ? `${dependency}You sync verified Forge fixes to the existing pull request. Follow ~/.claude/skills/ship-pr/SKILL.md and ~/.claude/skills/ship-pr/references/lessons.md. In ${PARAMS.projectDir}, stay on branch ${existing.branch}, commit current verified fixes, push them, and return the same non-draft PR metadata: ${JSON.stringify(existing)}. Update the PR body after the push. Include supplied ticket keys without inventing links: ${JSON.stringify(PARAMS.tickets)}. ${stagingRules(files)}`
    : `${dependency}You run the SHIP stage. Follow ~/.claude/skills/ship-pr/SKILL.md and ~/.claude/skills/ship-pr/references/lessons.md. In ${PARAMS.projectDir}, resolve the repository base branch, create a descriptive branch, commit the implementation, push it, open a NON-draft PR, and return {branch, prUrl, prNumber, repo}. Include supplied ticket keys without inventing links: ${JSON.stringify(PARAMS.tickets)}. ${stagingRules(files)}`
  return agentT('shipper', prompt, { label: existing ? 'ship-sync' : 'ship', phase: existing ? 'Fix' : 'Ship', agentType: 'shipper', schema: SHIP_SCHEMA })
}

function qaArtifactDraft(shipResult, context) {
  const criteria = acceptanceCriteria(context)
  return agentT('qaDraft', `You draft and open the QA artifact immediately after the pull request is pushed. Never fail the run: on any error return the attempted path, items=0, opened=false, and the error text.
1. Read lines 1-70 of ~/.claude/skills/forge/references/qa-artifact.html for its complete data and placeholder contract. Read ${PARAMS.runDir}/sandbox.json with ranged reads if it exists.
2. Write ${PARAMS.runDir}/qa-data.json. Set ticket=${JSON.stringify(PARAMS.ticket)}; derive shortTitle as 2-4 words from this plan summary: ${JSON.stringify(planSummary(context))}; set date to today; tier=${JSON.stringify(PARAMS.tierSandbox)}; branch=${JSON.stringify(shipResult.branch)}. Set sandboxId, previewUrl, rootLoginEmail, rootLoginPassword, and adminCreds from sandbox.json when present, otherwise "" so handoff can fill them. Set jiraTickets to one row per key in ${JSON.stringify(PARAMS.tickets)}, each with key, url="", title="", and role="". Set links=[{label:"Pull request",url:${JSON.stringify(shipResult.prUrl)}}]. Set contextItems to 2-4 concise lines from the plan summary.
Build qaItems with at least one item per affected code area by grouping these files by top-level app directory: ${JSON.stringify(context.files || [])}. Add one item per acceptance criterion not already covered: ${JSON.stringify(criteria)}. Every item has title, ticketKey, ticketUrl, before, whatChanged, why, steps with 2-6 concrete entries, expected, evidence="", pr=${JSON.stringify(String(shipResult.prNumber))}, a screenGroup guessed from its file area, and clickPass={status:"PENDING",note:"steward click pass pending",screenshot:""}. Wrap endpoint paths and commands in single backticks. Build users from sandbox.json testUsers and team entries as objects containing role and email only; never copy a password or token into users. Set every handoff key named by the template contract to "".
3. Write a small Python renderer to ${PARAMS.runDir}/qa-render.py that loads qa-data.json and substitutes every {{KEY}} placeholder according to the template header contract. Run it to render ${PARAMS.runDir}/qa-artifact.html, then run open ${PARAMS.runDir}/qa-artifact.html on macOS. If the Artifact tool is available, publish the rendered file titled "${PARAMS.ticket} <shortTitle> QA".
4. Return path=${PARAMS.runDir}/qa-artifact.html, the qaItems count as items, whether open succeeded as opened, and error="". On any error return that path, items=0, opened=false, and the error text.`,
  { label: 'qa-draft', phase: 'Ship', agentType: 'worker', schema: QA_DRAFT_SCHEMA })
}

function qaDraftSummary(draft) {
  return {
    path: (draft && draft.path) || '',
    items: draft && Number.isInteger(draft.items) ? draft.items : 0,
    opened: Boolean(draft && draft.opened),
  }
}

const sandboxToolFallback = `If the sandbox MCP tools are missing or fail with a connection error, follow the overlay's references/stages/sandbox.md fallback. Only when both configured methods fail return skipped=true and name both errors.`

function sandboxQA(shipResult, context) {
  const isUi = /frontend$/.test(PARAMS.repo)
  const branchField = isUi ? 'ui_branch' : 'api_branch'
  const check = isUi
    ? 'cd /app/frontend && yarn tsc --noEmit'
    : `cd /app/backend && uv run pytest ${(context.testPaths || ['tests/unit']).join(' ')} -x -q`
  if (PARAMS.existingSandbox) {
    return agentT('sandboxQA', `You run SANDBOX QA for Forge against an existing sandbox. ${syncInstructions(PARAMS.existingSandbox, shipResult, context.files || [], isUi, false, check, sandboxToolFallback)}`,
    { label: 'sandbox-qa', phase: 'Sandbox', schema: SANDBOX_SCHEMA })
  }
  return agentT('sandboxQA', `You run SANDBOX QA for Forge. Read and follow references/stages/sandbox.md supplied by the overlay. ${sandboxToolFallback}
Create one sandbox with ${branchField}=${shipResult.branch}, tier=${PARAMS.tierSandbox}, and ide=True. Write its metadata to ${PARAMS.runDir}/sandbox.json. Record ide_url and ide_password only in that file; treat them as credentials and never return them in a message, summary, or structured output. Then run with timeout 900: ${check}. Return sandbox id, login URL, preview URL, test result, summary, and seedRecipe="". On any skip, return skipped=true, the reason, empty strings for sandboxId/loginUrl/previewUrl/summary/seedRecipe, and testsPassed=false.`,
  { label: 'sandbox-qa', phase: 'Sandbox', schema: SANDBOX_SCHEMA })
}

function syncInstructions(sandbox, shipResult, files, isUi, allowSkip, check, toolFallback) {
  const repo = isUi ? 'frontend' : 'backend'
  const root = `/app/${repo}`
  const branchField = isUi ? 'ui_branch' : 'api_branch'
  const branch = shipResult.branch
  const fileHint = files.length ? `${files.length} files changed: ${JSON.stringify(files)}` : '0 files supplied; the changed set is unknown'
  const migrate = 'cd /app/backend && uv run python manage.py migrate --no-input'
  const skipAction = allowSkip
    ? 'Set mode="skip", skipped=false, testsPassed=false, and summary="fork already at <sha>; sync skipped" with the sync seconds. Return the same sandbox metadata immediately and DO NOT run the check command. The workflow may carry forward a prior passing result for this same fork.'
    : 'Set mode="skip" and summary="fork already at <sha>; sync skipped", but continue to the check command. This QA stage has no prior result to carry forward, so only the upload is skipped.'
  return `Existing sandbox metadata: ${JSON.stringify(sandbox)}. The branch is ${branch}; the file-count hint is ${fileHint}. Use the sandbox tools named by the overlay stage reference. ${toolFallback}
Perform these steps IN ORDER and measure elapsed seconds for the whole sync step:
1. Skip check. Locally in ${PARAMS.projectDir}, run git fetch origin ${branch} --quiet && git rev-parse origin/${branch} to get TIP. In sandbox ${sandbox.sandboxId}, use exec_command for cd ${root} && git rev-parse HEAD to get FORK_HEAD, then cd ${root} && git status --porcelain | wc -l to get DIRTY. If TIP equals FORK_HEAD and DIRTY is 0: ${skipAction} Otherwise continue.
2. Determine the changed set locally in ${PARAMS.projectDir} with git diff --name-only <FORK_HEAD> origin/${branch}, substituting the FORK_HEAD sha from step 1. Treat ${JSON.stringify(files)} only as a cross-check hint. If the derived set and hint disagree, report that in summary and use the derived set. If FORK_HEAD is not present locally or git diff errors, fall back to the hint when it is non-empty; otherwise use re-fork. Measure total bytes with wc -c against the corresponding files under ${PARAMS.projectDir}; deleted files count as zero bytes. The measured set and byte count control the choice.
3. Git-fetch first. In sandbox ${sandbox.sandboxId}, run: cd ${root} && GIT_TERMINAL_PROMPT=0 git fetch origin ${branch} && git checkout -B ${branch} FETCH_HEAD. On success set mode="git-fetch". If the changed set contains a migrations/ path, run with timeout 600: ${migrate}; a non-zero migration is a blocker with the last 20 output lines in summary. Then ${isUi ? 'let vite reload itself' : 'restart the API process with the fork start script'}. Skip steps 4 and 5 and continue to step 6. If fetch or checkout fails, say so in summary and continue to the hot-patch fallback.
4. Hot-patch after a failed git-fetch only when the known changed set has at most 3 entries and totals at most 40000 bytes. Set mode="hot-patch". For each repo-relative path, use upload_file to upload inline text from ${PARAMS.projectDir}/<path> to ${root}/<path> in sandbox ${sandbox.sandboxId}; remove a deleted file with exec_command rm at ${root}/<path>. ${isUi ? 'The vite dev server hot-reloads.' : `If any path is under a migrations/ directory, first use exec_command with timeout 600 for: ${migrate}. A non-zero exit is a blocker: return skipped=true, put the last 20 output lines in summary, preserve the current sandbox metadata, and set testsPassed=false. Then restart the API process with the fork start script.`} Skip step 5 and continue to step 6.
5. Re-fork after a failed git-fetch when hot-patch is not allowed. Set mode="re-fork". Read ${PARAMS.runDir}/sandbox.json when present and retain its cohort and team values. Call create_sandbox with ${branchField}=${branch}, tier=${PARAMS.tierSandbox}, login_email="" for token injection, and ide=True; leave other arguments at their defaults. Treat ide_url and ide_password as credentials: write them only to ${PARAMS.runDir}/sandbox.json and never return them in a message, summary, or structured output. Wait until the tool reports the new sandbox healthy. If the changed set touches a migrations/ path, run in the NEW sandbox with timeout 600: ${migrate}. If migration exits non-zero, call teardown_sandbox on the NEW sandbox id without force and never retry with force; keep and return the OLD sandbox metadata, set skipped=true and testsPassed=false, and name the torn-down new id plus the migration's last 20 output lines in summary. Only after the new sandbox is healthy${isUi ? '' : ' and any migration succeeds'}, copy ${PARAMS.runDir}/sandbox.json when present to ${PARAMS.runDir}/sandbox.${sandbox.sandboxId}.json, then call teardown_sandbox on OLD sandbox ${sandbox.sandboxId}, without force. If teardown of the OLD sandbox fails, including a 403 because another developer owns it, report the failure in summary and continue on the NEW fork; never retry with force. Write ${PARAMS.runDir}/sandbox.json with the NEW sandbox metadata, the retained cohort and team when present, seedRecipe="${PARAMS.runDir}/sandbox.${sandbox.sandboxId}.json", and seedsReplayed=false. From this point, use and return the NEW sandboxId, loginUrl, previewUrl, and seedRecipe. The summary must say "seeds not replayed; recipe at ${PARAMS.runDir}/sandbox.${sandbox.sandboxId}.json".
6. Unless the allowed clean-fork skip returned early, run in the current sandbox with timeout 900: ${check}. Set testsPassed from its exit result and skipped=false.
Return sandboxId, loginUrl, previewUrl, mode, testsPassed, skipped, reason, summary, and seedRecipe ("" when none). Summary must report mode, measured file count, total bytes, seconds spent on the sync step, and the test result. On any tool-unavailable or blocker skip, return skipped=true, its reason, the current sandbox metadata, seedRecipe from that metadata or "", and testsPassed=false.`
}

function postSandboxMarker(shipResult, sandbox) {
  return agentT('shipper', `Append the pull-request marker to the PR body exactly once on ${shipResult.prUrl}. Read the current body with \`gh pr view ${shipResult.prNumber} --repo ${shipResult.repo} --json body -q .body\`. ` +
  `If the body contains exactly \`<!-- forge-sandbox: ${sandbox.sandboxId} -->\`, do nothing. If it has a forge-sandbox marker with a different id, replace that entire marker line with exactly \`<!-- forge-sandbox: ${sandbox.sandboxId} -->\` and ensure exactly one marker remains. If it has no marker, append a blank line and that exact marker at the end. Save any changed whole body with gh pr edit --body-file. Never post a comment. Return {written: true} as before.`,
  { label: 'sandbox-marker', phase: 'Sandbox', agentType: 'shipper', schema: ACK_SCHEMA })
}

function writeStatus(patch, phaseLabel) {
  return agentT('trim', `Merge this JSON patch into ${PARAMS.runDir}/STATUS.json. If the file does not exist, create it as {"criteria":[],"rounds":{},"open_findings":[]} first. Rules: never delete existing keys; "criteria" entries match by "text" (fall back to matching by array index when texts differ); for a matched criterion overwrite status/evidence/round only when the patch provides them; "rounds" merges key-by-key (patch wins); "open_findings" is REPLACED by the patch's array when provided; set "updated" to the current ISO timestamp. Write the merged JSON back with 2-space indentation and return written=true. Patch: ${JSON.stringify(patch)}`,
  { label: `status-${phaseLabel}`, phase: phaseLabel, schema: ACK_SCHEMA })
}

async function smoke(sandbox, context) {
  const criteria = smokeCriteria(context)
  const results = []
  for (let offset = 0; offset < criteria.length; offset += 6) {
    const chunk = criteria.slice(offset, offset + 6)
    const number = offset / 6 + 1
    const label = number === 1 ? 'smoke' : `smoke-${number}`
    const specStep = number === 1
      ? `If ${PARAMS.projectDir}/e2e/ contains Playwright specs, first read ${PARAMS.projectDir}/e2e/README.md for the base-URL and login env vars, run the suite against ${sandbox.previewUrl} with the line reporter and \`--grep\` on any criterion tag the plan names, and save the output to ${PARAMS.runDir}/smoke/e2e.log. A criterion covered by a passing spec is PASS with evidence = that log path. Only criteria with no matching spec are attempted with Playwright MCP tools.`
      : 'Do not run the Playwright spec suite in this chunk. Attempt each criterion below with Playwright MCP tools.'
    const smokeResult = await agentT('smoke', `${specStep} You run the acceptance-criterion SMOKE stage, never exploratory testing. Read ${PARAMS.runDir}/sandbox.json (ranged read; keys rootLogin or testUsers[0].email, and testPassword). ` +
    `If testPassword is present, open ${sandbox.previewUrl} and sign in with that email and password in a fresh context; only if it is absent open ${sandbox.loginUrl}. Then attempt each criterion with no matching spec in order: ${JSON.stringify(chunk)}. Save one relevant screenshot per MCP-attempted criterion under ${PARAMS.runDir}/smoke/. Use the application preview ${sandbox.previewUrl}. Before returning, run ls on every screenshot and log path you intend to report. A path that does not exist becomes an empty string and its note says the evidence is missing. Return criterion, pass/fail, note, and screenshot path; only paths that exist, never image data.`,
    { label, phase: 'Sandbox', schema: SMOKE_SCHEMA })
    if (!smokeResult) return null
    results.push(...(smokeResult.results || []))
  }
  return { results }
}

function sandboxRefresh(sandbox, shipResult, context) {
  const isUi = /frontend$/.test(PARAMS.repo)
  const check = isUi ? 'cd /app/frontend && yarn tsc --noEmit' : `cd /app/backend && uv run pytest ${(context.testPaths || ['tests/unit']).join(' ')} -x -q`
  return agentT('sandboxQA', `You run SANDBOX POST-FIX RE-RUN. ${syncInstructions(sandbox, shipResult, context.files || [], isUi, true, check, sandboxToolFallback)}`,
  { label: 'sandbox-refresh', phase: 'Fix', schema: SANDBOX_SCHEMA })
}

async function handoff(state, context) {
  const preserveFixCap = state.status === 'READY_FOR_HUMAN'
    ? `Read the existing ${PARAMS.runDir}/STATE.md first and preserve its "Fix cap reached" block verbatim in the rewritten file.`
    : ''
  const handoffState = {
    ...state,
    qaDraft: qaDraftSummary(state.qaDraft),
    context: context && {
      files: context.files || [], planSummary: planSummary(context),
      criteria: acceptanceCriteria(context), testPaths: context.testPaths || [],
    },
  }
  await writeStatus({ rounds: { handoff: 1 }, status: state.status }, 'Handoff')
  return agentT('handoff', `You write the Forge HANDOFF at ${PARAMS.runDir}/handoff.md. First APPEND to ${PARAMS.runDir}/decisions.md (create it if missing; never truncate or rewrite existing content) a section headed \`## Workflow <current UTC timestamp in ISO 8601, which you generate because the script cannot>\` followed by one line per entry of this decisions array: ${JSON.stringify(decisions)}. Use only the run data below, ${PARAMS.runDir}/STATUS.json, and ${PARAMS.runDir}/decisions.md. Do not read the diff or repository files; file names come from the run data.
Write these sections exactly: What changed and why; Gate results; Sandbox + smoke results (include login URL, preview URL, sandbox id, and any post-fix re-run, with no expiry caveats); Review scores and findings; Manual QA checklist (one item per acceptance criterion); Judgment calls; Status. Status must be ${state.status}. Judgment calls must include every entry from ${JSON.stringify(decisions)}.
Read ${PARAMS.runDir}/STATUS.json and render the Manual QA checklist from its criteria (status + evidence per item) when it exists.
Acceptance criteria: ${JSON.stringify(acceptanceCriteria(context))}
Run data: ${JSON.stringify(handoffState)}
Then rewrite ${PARAMS.runDir}/STATE.md whole (never append) from ~/.claude/references/state-template.md with the run's current state, next steps, blockers, pointers (plan, decisions, STATUS.json, PR, branch, sandbox), and do-not-redo facts. ${preserveFixCap}
Return the handoff path.`,
  { label: 'handoff', phase: 'Handoff', schema: HANDOFF_SCHEMA })
}

function mergeImplementResults(results) {
  const first = results[0]
  return {
    codexInvoked: results.every(result => result.codexInvoked === true),
    threadMode: first.threadMode,
    threadExists: results.every(result => result.threadExists === true),
    filesChanged: [...new Set(results.flatMap(result => result.filesChanged || []))],
    testsWritten: results.reduce((total, result) => total + (result.testsWritten || 0), 0),
    summary: results.map(result => result.summary).filter(Boolean).join('\n'),
    error: results.map(result => result.error).filter(Boolean).join('; '),
  }
}

async function runCheckpointSegments(state, firstResult, segments) {
  const results = [firstResult]
  for (let index = 0; index < segments.length; index++) {
    const segment = segments[index]
    const result = results[index]
    const implementLabel = index === 0 ? 'implement' : `implement-cp${index + 1}`
    try {
      if (!assertImplementation(result, implementLabel)) throw new Error('implementation agent returned null')
    } catch (error) {
      state.status = 'BLOCKED'
      await decide(`Checkpoint ${index + 1} implementation failed; later segments were stopped: ${error.message}`)
      if (!segment.final) await decide(`[cp${index + 1}] gate fail, spot review skipped (0 findings, 0 fixed)`)
      break
    }
    if (segment.final) continue

    const checkpoint = index + 1
    const segmentFiles = [...new Set(result.filesChanged || [])]
    phase('Gate')
    let gateRun = null
    try {
      gateRun = await gateWithFixes(`gate-cp${checkpoint}`, segmentFiles, segmentThread(index), { standards: '' }, 'Gate')
    } catch (error) {
      await decide(`Checkpoint ${checkpoint} gate fix failed: ${error.message}`)
    }
    let gate = gateRun && gateRun.gate
    if (gateRun) result.filesChanged = [...new Set([...(result.filesChanged || []), ...(gateRun.touchedFiles || [])])]
    if (!gate || !gate.passed) {
      state.status = gateRun && gateRun.capReached
        ? await recordFixCap(gate, segmentThread(index), '', gateFindings(gate || { failures: [] }))
        : 'BLOCKED'
      await decide(`[cp${checkpoint}] gate fail, spot review skipped (0 findings, 0 fixed)`)
      await decide(`Checkpoint ${checkpoint} local gate did not pass; later segments were stopped.`)
      break
    }

    phase('Review')
    const review = await spotReview(segment, index, segments.length, PARAMS.planText, gate)
    if (!review) {
      await decide(`Checkpoint ${checkpoint} spot review returned null; continuing without blocking.`)
      await decide(`[cp${checkpoint}] gate pass, spot review null (0 findings, 0 fixed)`)
    } else {
      const findings = review.findings || []
      const blocking = findings.filter(finding => ['CRITICAL', 'HIGH'].includes(finding.severity))
      const deferred = findings.filter(finding => ['MEDIUM', 'LOW'].includes(finding.severity))
      const deferredLines = deferred.map(finding => `[cp${checkpoint}] ${finding.severity} ${finding.file}:${finding.line} ${finding.claim}`)
      state.checkpointFindings.push(...deferredLines)
      let fixed = 0
      if (blocking.length) {
        let fix = null
        try {
          fix = await fixAgent(blocking, { standards: '' }, `fix-spot-cp${checkpoint}`, segmentThread(index), 'Review')
        } catch (error) {
          await decide(`Checkpoint ${checkpoint} spot-review fix failed: ${error.message}`)
        }
        if (!fix) {
          state.status = 'BLOCKED'
          await decide(`Checkpoint ${checkpoint} spot-review fix returned null; later segments were stopped before re-gating.`)
          await decide(`[cp${checkpoint}] gate fail, spot review ${review.verdict} (${findings.length} findings, 0 fixed)`)
          break
        }
        fixed = (fix.fixed || []).length
        result.filesChanged = [...new Set([...(result.filesChanged || []), ...(fix.touchedFiles || [])])]
        if ((fix.touchedFiles || []).length === 0) {
          await decide(`Checkpoint ${checkpoint} spot-review fix touched no files (findings stale or rebutted); re-gate skipped.`)
        } else {
          phase('Gate')
          gate = await localGate(`gate-cp${checkpoint}-fix`, 'Gate', result.filesChanged)
          if (!gate || !gate.passed) {
            state.status = 'BLOCKED'
            await decide(`Checkpoint ${checkpoint} re-gate failed after the spot-review fix; later segments were stopped.`)
          }
        }
      }
      await decide(`[cp${checkpoint}] gate ${state.status === 'BLOCKED' ? 'fail' : 'pass'}, spot review ${review.verdict} (${findings.length} findings, ${fixed} fixed)`)
      if (state.status === 'BLOCKED') break
    }

    phase('Implement')
    const pendingLines = state.checkpointFindings.filter(line => line.startsWith(`[cp${checkpoint}] `))
    const next = await implement(segments[index + 1], index + 1, segments.length, pendingLines, result)
    results.push(next)
  }
  state.implement = results.some(Boolean) ? mergeImplementResults(results.filter(Boolean)) : null
  if (!state.implement) state.status = 'BLOCKED'
  if (capBlocked && state.status !== 'READY_FOR_HUMAN') state.status = 'BLOCKED'
  return state
}

async function fullLane() {
  phase('Implement')
  if (PARAMS.lane === 'dev' && PARAMS.planText === null) {
    const plan = await readPlan()
    PARAMS.planText = plan ? plan.planText : ''
  } else {
    PARAMS.planText = PARAMS.planText || ''
  }
  const checkpointArgs = PARAMS.lane === 'dev' ? PARAMS.checkpoints : []
  const segments = parseCheckpoints(PARAMS.planText, checkpointArgs)
  const initial = { status: 'DONE', implement: null, gate: null, ship: null, qaDraft: null, sandbox: null, smoke: null, review: null, convergence: null, sandboxRefresh: null, checkpointFindings: [] }
  const rows = await pipeline(
    [initial],
    async state => {
      phase('Implement')
      const first = await implement(segments[0], 0, segments.length)
      if (segments.length > 1 || (segments[0] && segments[0].reason)) return runCheckpointSegments(state, first, segments)
      state.implement = first
      if (!assertImplementation(first, 'implement')) state.status = 'BLOCKED'
      if (capBlocked && state.status !== 'READY_FOR_HUMAN') state.status = 'BLOCKED'
      return state
    },
    async state => {
      phase('Gate')
      if (stopped(state)) return state
      const gateRun = await gateWithFixes('gate', (state.implement && state.implement.filesChanged) || [], segmentThread(segments.length - 1), { standards: '' }, 'Gate')
      state.gate = gateRun.gate
      if (state.implement) state.implement.filesChanged = [...new Set([...(state.implement.filesChanged || []), ...(gateRun.touchedFiles || [])])]
      if (!state.gate || !state.gate.passed) {
        state.status = gateRun.capReached
          ? await recordFixCap(state.gate, segmentThread(segments.length - 1), '', gateFindings(state.gate || { failures: [] }))
          : 'BLOCKED'
        await decide('Pre-ship local gate did not pass; later stages were stopped.')
      }
      return state
    },
    async state => {
      phase('Ship')
      if (stopped(state)) return state
      if (PARAMS.noShip) {
        await decide('Ship, sandbox, and smoke stages skipped because args.noShip is true.')
        return state
      }
      state.ship = await ship(null, (state.implement && state.implement.filesChanged) || [])
      if (!state.ship || state.ship.skipped) {
        state.status = 'BLOCKED'
        if (state.ship && state.ship.reason) await decide(state.ship.reason)
      }
      return state
    },
    async state => {
      phase('Sandbox')
      if (stopped(state) || !state.ship) return state
      state.context = await changedFiles(state.checkpointFindings)
      if (contextFailed(state.context)) {
        state.qaDraft = await qaArtifactDraft(state.ship, state.context || { files: [], criteria: PARAMS.criteria })
        if (!state.qaDraft) state.qaDraft = { path: `${PARAMS.runDir}/qa-artifact.html`, items: 0, opened: false, error: 'agent returned null' }
        state.status = 'BLOCKED'
        await decide(`Changed-file collection failed; review inputs are unavailable: ${(state.context && state.context.error) || 'agent returned null'}`)
        return state
      }
      if (!configuredStage('sandbox')) {
        state.qaDraft = await qaArtifactDraft(state.ship, state.context)
        if (!state.qaDraft) state.qaDraft = { path: `${PARAMS.runDir}/qa-artifact.html`, items: 0, opened: false, error: 'agent returned null' }
        await decide('Sandbox and smoke skipped because stages.sandbox is off.')
        return state
      }
      ;[state.qaDraft, state.sandbox] = await Promise.all([
        qaArtifactDraft(state.ship, state.context),
        sandboxQA(state.ship, state.context),
      ])
      if (!state.qaDraft) state.qaDraft = { path: `${PARAMS.runDir}/qa-artifact.html`, items: 0, opened: false, error: 'agent returned null' }
      if (!state.sandbox) state.sandbox = { key: 'sandbox-qa', status: 'FAIL', reason: 'agent returned null' }
      if (state.sandbox.skipped) await decide(`Sandbox QA skipped: ${state.sandbox.reason}`)
      if (state.sandbox.sandboxId) await postSandboxMarker(state.ship, state.sandbox)
      if (state.sandbox.previewUrl) {
        state.smoke = await smoke(state.sandbox, state.context)
        if (!state.smoke) state.smoke = { key: 'smoke', status: 'FAIL', reason: 'agent returned null' }
        if (Array.isArray(state.smoke.results)) {
          await writeStatus({
            criteria: state.smoke.results.map(result => ({ text: result.criterion, status: result.passed ? 'pass' : 'fail', evidence: result.screenshot || result.note || null, round: 0 })),
            rounds: { smoke: 1 },
          }, 'Sandbox')
        }
      } else {
        await decide('Smoke skipped because sandbox QA returned no preview URL.')
      }
      return state
    },
    async state => {
      phase('Review')
      if (stopped(state)) return state
      state.context = state.context || await changedFiles(state.checkpointFindings)
      if (PARAMS.lane === 'quick') await decide('Quick lane omits the Claude general reviewer by lane design.')
      state.review = await reviewPanel(state.context)
      if ((configuredRole('review') || {}).provider !== 'claude' && state.review.failures.some(failure => failure.key === 'codex')) {
        // Cross-model review is the contract; never continue Claude-only.
        state.status = 'BLOCKED'
        await decide('CROSS-MODEL ASSERT FAILED: the Codex review did not run, so the run is BLOCKED instead of continuing with Claude-only findings. The PR and sandbox are preserved; resume once Codex is available.')
        return state
      }
      if (state.review.unresolvedDisputes.length) state.needsJudge = true
      return state
    },
    async state => {
      if (state.needsJudge || stopped(state)) return state
      phase('Fix')
      state.convergence = await converge(state.review, state.context)
      if (state.convergence.capReached) {
        state.status = await recordFixCap(state.convergence.gate, CODEX_FIX_THREAD, (state.ship && state.ship.branch) || '', state.convergence.unresolved)
      } else if (state.convergence.blocked) {
        state.status = 'BLOCKED'
      }
      if (!state.convergence.capReached && state.convergence.gateRan && !state.convergence.gatePassed) {
        state.status = 'BLOCKED'
        const firstFailure = state.convergence.gate && (state.convergence.gate.failures || [])[0]
        const fallback = state.convergence.gate ? 'no failure detail' : 'agent returned null'
        const summary = String((firstFailure && firstFailure.summary) || fallback).slice(0, 200)
        const branch = (state.ship && state.ship.branch) || '(unknown branch)'
        await decide(`Fix-round gate failed (${summary}); fixes left uncommitted on ${branch}; ship-sync and sandbox-refresh skipped.`)
      }
      if (state.convergence.blocked && state.convergence.gatePassed) {
        const branch = (state.ship && state.ship.branch) || '(unknown branch)'
        await decide(`Fixes stayed unpushed on ${branch} because ${state.convergence.unresolved.length} finding(s) remained unresolved after verification.`)
      }
      if (!state.convergence.blocked && state.convergence.fixesApplied && state.convergence.gatePassed && state.ship) {
        const synced = await ship(state.ship, [
          ...((state.implement && state.implement.filesChanged) || []),
          ...((state.convergence && state.convergence.touchedFiles) || []),
        ])
        if (!synced || synced.skipped) {
          state.status = 'BLOCKED'
          await decide((synced && synced.reason) || 'Verified fixes could not be pushed to the existing pull request.')
        } else {
          state.ship = synced
        }
        if (configuredStage('sandbox') && state.sandbox && state.sandbox.sandboxId && synced && !synced.skipped) {
          const refreshFiles = [...new Set([
            ...((state.context && state.context.files) || []),
            ...((state.implement && state.implement.filesChanged) || []),
            ...((state.convergence && state.convergence.touchedFiles) || []),
          ])]
          state.sandboxRefresh = await sandboxRefresh(state.sandbox, state.ship, { ...state.context, files: refreshFiles })
          if (!state.sandboxRefresh) state.sandboxRefresh = { key: 'sandbox-refresh', status: 'FAIL', reason: 'agent returned null' }
          if (state.sandboxRefresh.mode === 'skip' && state.sandbox.testsPassed === true && state.sandbox.sandboxId === state.sandboxRefresh.sandboxId) {
            state.sandboxRefresh.testsPassed = true
            const carried = 'previous passing result carried forward for the same fork'
            state.sandboxRefresh.summary = `${state.sandboxRefresh.summary}; ${carried}`
            state.sandboxRefresh.reason = state.sandboxRefresh.reason ? `${state.sandboxRefresh.reason}; ${carried}` : carried
          }
          if (state.sandboxRefresh.sandboxId && state.sandboxRefresh.sandboxId !== state.sandbox.sandboxId) {
            state.sandbox = {
              ...state.sandbox,
              sandboxId: state.sandboxRefresh.sandboxId,
              loginUrl: state.sandboxRefresh.loginUrl,
              previewUrl: state.sandboxRefresh.previewUrl,
              testsPassed: state.sandboxRefresh.testsPassed,
              seedRecipe: state.sandboxRefresh.seedRecipe,
            }
            await postSandboxMarker(state.ship, state.sandbox)
          }
          if (state.sandboxRefresh.mode === 'git-fetch' || state.sandboxRefresh.mode === 'hot-patch' || state.sandboxRefresh.mode === 're-fork') {
            state.sandbox.testsPassed = state.sandboxRefresh.testsPassed
          }
        }
      }
      return state
    },
  )
  const finalState = rows.filter(Boolean)[0]
  if (!finalState) throw new Error('dev lane produced no final state (a stage threw before the pipeline returned)')
  return finalState
}

async function reviewLane() {
  await decide('Review lane skipped Implement, standalone Gate, Ship, Sandbox, and Smoke stages.')
  phase('Review')
  const context = await changedFiles()
  if (contextFailed(context)) {
    await decide(`Changed-file collection failed; review inputs are unavailable: ${(context && context.error) || 'agent returned null'}`)
    return { status: 'BLOCKED', context: context || { criteria: PARAMS.criteria }, review: null, convergence: null, ship: null, sandbox: null, smoke: null, sandboxRefresh: null, gate: null, implement: null }
  }
  const review = await reviewPanel(context)
  if ((configuredRole('review') || {}).provider !== 'claude' && review.failures.some(failure => failure.key === 'codex')) {
    await decide('CROSS-MODEL ASSERT FAILED: the Codex review did not run, so the review lane is BLOCKED instead of continuing Claude-only.')
    return { status: 'BLOCKED', context, review, convergence: null, ship: null, sandbox: null, smoke: null, sandboxRefresh: null, gate: null, implement: null }
  }
  if (review.unresolvedDisputes.length) return { needsJudge: true, context, review }
  phase('Fix')
  const convergence = await converge(review, context)
  const status = convergence.capReached
    ? await recordFixCap(convergence.gate, CODEX_FIX_THREAD, '', convergence.unresolved)
    : convergence.blocked || capBlocked ? 'BLOCKED' : 'DONE'
  return { status, context, review, convergence, ship: null, sandbox: null, smoke: null, sandboxRefresh: null, gate: null, implement: null }
}

await loadForgeConfig()
let state = PARAMS.lane === 'review' ? await reviewLane() : await fullLane()
if (state.needsJudge) {
  return { status: 'needsJudge', findings: state.review.findings, disputes: state.review.unresolvedDisputes, runDir: PARAMS.runDir }
}
if (capBlocked && state.status !== 'READY_FOR_HUMAN') state.status = 'BLOCKED'
phase('Handoff')
const ho = await handoff(state, state.context || { criteria: PARAMS.criteria })
if (!ho) {
  if (state.status !== 'READY_FOR_HUMAN') state.status = 'BLOCKED'
  await decide('Handoff agent returned null; no handoff path was produced.')
}
if (capBlocked && state.status !== 'READY_FOR_HUMAN') state.status = 'BLOCKED'
return {
  status: state.status,
  runDir: PARAMS.runDir,
  handoffPath: (ho && ho.handoffPath) || '',
  prUrl: (state.ship && state.ship.prUrl) || '',
  qaDraft: qaDraftSummary(state.qaDraft),
  sandboxId: (state.sandbox && state.sandbox.sandboxId) || '',
  decisions,
}
