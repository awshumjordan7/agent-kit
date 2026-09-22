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
    triage: { model: 'fable', effort: 'high' },
    judge: { model: 'fable', effort: 'high' },
    codexWrap: { model: 'sonnet', effort: 'low' },
    gate: { model: 'haiku', effort: 'low' },
    sandboxQA: { model: 'sonnet', effort: 'medium' },
    qaDraft: { model: 'sonnet', effort: 'low' },
    smoke: { model: 'sonnet', effort: 'medium' },
    trim: { model: 'haiku', effort: 'low' },
    lens: { model: 'sonnet', effort: 'high' },
    shipper: { model: 'sonnet', effort: 'low' },
    handoff: { model: 'sonnet', effort: 'low' },
    changedFiles: { model: 'haiku', effort: 'low' },
    readConfig: { model: 'haiku', effort: 'low' },
  },
  opus: {
    implementer: { model: 'opus', effort: 'high' },
    reviewer: { model: 'opus', effort: 'high' },
    triage: { model: 'opus', effort: 'high' },
    judge: { model: 'opus', effort: 'high' },
    codexWrap: { model: 'sonnet', effort: 'low' },
    gate: { model: 'haiku', effort: 'low' },
    sandboxQA: { model: 'sonnet', effort: 'medium' },
    qaDraft: { model: 'sonnet', effort: 'low' },
    smoke: { model: 'sonnet', effort: 'medium' },
    trim: { model: 'haiku', effort: 'low' },
    lens: { model: 'sonnet', effort: 'high' },
    shipper: { model: 'sonnet', effort: 'low' },
    handoff: { model: 'sonnet', effort: 'low' },
    changedFiles: { model: 'haiku', effort: 'low' },
    readConfig: { model: 'haiku', effort: 'low' },
  },
}

const ROLE_MAP = {
  implementer: ['impl', 'quick-impl'],
  reviewer: ['review'],
}

const requestedLane = args.lane || 'build'
const canonicalLane = ['quick', 'dev'].includes(requestedLane) ? 'build' : requestedLane
const PARAMS = {
  lane: canonicalLane,
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
  planText: typeof args.planText === 'string' ? args.planText : null,
  planPath: typeof args.planPath === 'string' && args.planPath ? args.planPath : `${args.runDir}/plan.md`,
  dryRun: args.dryRun === true,
  dryRunFailGate: typeof args.dryRunFailGate === 'string' ? args.dryRunFailGate : null,
  dryRunStubborn: args.dryRunStubborn === true,
  dryRunFindings: Number.isInteger(args.dryRunFindings) && args.dryRunFindings > 0 ? args.dryRunFindings : 0,
  ghEnvUnset: Array.isArray(args.ghEnvUnset) ? args.ghEnvUnset : null,
  forgeConfig: args.forgeConfig && typeof args.forgeConfig === 'object' ? args.forgeConfig : null,
  fullySpecified: args.fullySpecified === true,
  stageAlso: Array.isArray(args.stageAlso) ? args.stageAlso.map(String) : [],
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
function codexImplFlags() {
  return codexFlags(pickImplRole(PARAMS.lane, PARAMS.fullySpecified, PARAMS.planText, quickReviewThreshold()), args.codexModelImpl || args.codexModel, args.codexEffortImpl)
}
const CODEX_REVIEW_FLAGS = codexFlags('review', args.codexModelReview || args.codexModel, args.codexEffortReview)
const CODEX_SH = '~/.claude/skills/forge/scripts/codex-exec.sh'
const PLAN = PARAMS.planPath

// Persistent Codex thread files:
// CODEX_PLAN_THREAD / codex-plan.thread is reserved for Phase 3 plan review outside this script.
// CODEX_REVIEW_THREAD / codex-review.thread owns review and all fix verification.
const CODEX_PLAN_THREAD = `${PARAMS.runDir}/codex-plan.thread`
const CODEX_IMPL_THREAD = `${PARAMS.runDir}/codex-impl.thread`
const CODEX_REVIEW_THREAD = `${PARAMS.runDir}/codex-review.thread`

if (!PARAMS.runDir || !PARAMS.projectDir) {
  throw new Error('forge-core requires args.runDir and args.projectDir')
}
if (!PARAMS.planText) {
  throw new Error('planText is required; pass the plan text in args')
}
if (!['build', 'review'].includes(PARAMS.lane)) {
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
    testsWritten: { type: 'integer' }, summary: { type: 'string' }, error: { type: ['string', 'null'] },
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
    thresholds: { type: 'object' },
    lenses: { type: 'object' },
    ticketUrl: { type: 'string' },
    repos: { type: 'object' },
    ghEnvUnset: { type: 'object' },
  },
  required: ['roles', 'stages', 'thresholds', 'lenses', 'ticketUrl', 'repos'],
}
const CODEX_REVIEW_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    codexInvoked: { type: 'boolean' }, threadMode: { type: 'string', enum: ['start', 'resume'] },
    threadExists: { type: 'boolean' }, review: REVIEW_SCHEMA, error: { type: ['string', 'null'] },
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
    threadExists: { type: 'boolean' }, fix: FIX_SCHEMA, error: { type: ['string', 'null'] },
  },
  required: ['codexInvoked', 'threadMode', 'threadExists', 'fix'],
}
const VERIFY_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    codexInvoked: { type: 'boolean' }, threadMode: { type: 'string', enum: ['start'] },
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
    unresolved: { type: 'array', items: FINDING },
    contractViolations: {
      type: 'array', items: {
        type: 'object', additionalProperties: false,
        properties: { file: { type: 'string' }, line: { type: 'integer' }, claim: { type: 'string' } },
        required: ['file', 'line', 'claim'],
      },
    },
    error: { type: ['string', 'null'] },
  },
  required: ['codexInvoked', 'threadMode', 'threadExists', 'clean', 'results', 'unresolved', 'contractViolations'],
}
const TRIAGE_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    verdicts: {
      type: 'array', items: {
        type: 'object', additionalProperties: false,
        properties: {
          file: { type: 'string' }, line: { type: 'integer' },
          real: { type: 'string', enum: ['yes', 'no', 'uncertain'] },
          worthIt: { type: 'boolean' }, why: { type: 'string' },
        },
        required: ['file', 'line', 'real', 'worthIt', 'why'],
      },
    },
  },
  required: ['verdicts'],
}
const JUDGE_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    decisions: {
      type: 'array', items: {
        type: 'object', additionalProperties: false,
        properties: {
          id: { type: 'string' }, verdict: { type: 'string', enum: ['dismiss', 'respec', 'fixed'] },
          instruction: { type: 'string' }, reason: { type: 'string' },
        },
        required: ['id', 'verdict', 'instruction', 'reason'],
      },
    },
    cannotDecide: { type: 'boolean' },
  },
  required: ['decisions', 'cannotDecide'],
}
const CONTEXT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    files: { type: 'array', items: { type: 'string' } },
    droppedPaths: { type: 'array', items: { type: 'string' } },
    preexisting: { type: 'array', items: { type: 'string' } }, commandSucceeded: { type: 'boolean' },
    diffPath: { type: 'string' }, diffBytes: { type: 'integer' }, diffLines: { type: 'integer' },
    diffValid: { type: 'boolean' }, planSummary: { type: 'string' },
    criteria: { type: 'array', items: { type: 'string' } },
    checklist: { type: 'string' }, standards: { type: 'string' },
    testPaths: { type: 'array', items: { type: 'string' } }, error: { type: 'string' },
    contract: { type: 'string' }, reviewerContract: { type: 'string' },
  },
  required: ['files', 'preexisting', 'commandSucceeded', 'diffPath', 'diffBytes', 'diffLines', 'diffValid', 'planSummary', 'criteria', 'checklist', 'standards', 'testPaths', 'error', 'contract', 'reviewerContract'],
}
const GATE_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    passed: { type: 'boolean' },
    failures: {
      type: 'array', items: {
        type: 'object', additionalProperties: false,
        properties: { tool: { type: 'string' }, summary: { type: 'string' }, file: { type: ['string', 'null'] }, line: { type: ['integer', 'null'] } },
        required: ['tool', 'summary', 'file', 'line'],
      },
    },
    warnings: {
      type: 'array', items: {
        type: 'object', additionalProperties: false,
        properties: { tool: { type: 'string' }, summary: { type: 'string' } },
        required: ['tool', 'summary'],
      },
    },
    skipped: { type: 'array', items: { type: 'string' } },
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

const DEFAULT_LENSES = {
  security: '(auth|permission|identity|rbac|token|session)',
  design: '\\.tsx?$',
}
const LENSES = [
  { key: 'security', configKey: 'security', prompt: 'Audit authentication, authorization, scoping, token/session handling, input trust, and privilege boundaries.' },
  { key: 'dx-audit', paths: /(views?|serializers?|urls?|routes?|clients?|api)\//i, skill: 'dx-audit' },
  { key: 'design-audit', configKey: 'design', skill: 'design-audit' },
]

function quickReviewThreshold() {
  const value = FORGE_CONFIG && FORGE_CONFIG.thresholds && FORGE_CONFIG.thresholds.quickReviewThreshold
  return Number.isInteger(value) && value >= 1 ? value : 8
}

function plannedSourceFiles(planText) {
  const phases = /^(#{2,})\s*Phases\s*$/im.exec(String(planText || ''))
  if (!phases) return 0
  const after = String(planText).slice(phases.index + phases[0].length)
  const next = after.search(new RegExp(`^#{2,${phases[1].length}}\\s+(?!Phase\\b)`, 'mi'))
  const body = next >= 0 ? after.slice(0, next) : after
  const knownSourceExtension = /\.(?:bash|c|cc|cpp|cs|css|cxx|go|h|hpp|html|java|js|jsx|kt|kts|less|mjs|php|py|rb|rs|scala|scss|sh|sql|svelte|swift|toml|ts|tsx|vue|yaml|yml|zsh)$/i
  const paths = [...body.matchAll(/`([^`\n]+\.[A-Za-z0-9]+)`/g)]
    .map(match => match[1])
    .filter(path => /[\\/]/.test(path) || knownSourceExtension.test(path))
  return new Set(paths.filter(isSourcePath)).size
}

function isSourcePath(path) {
  const normalized = String(path).replace(/\\/g, '/').toLowerCase()
  const name = normalized.split('/').pop() || ''
  return !normalized.startsWith('tests/') && !normalized.includes('/tests/') &&
    !name.startsWith('test_') && !name.endsWith('_test.py') &&
    !name.endsWith('.md') && !name.endsWith('.json') && /\.[a-z0-9]+$/.test(name)
}

function pickImplRole(lane, fullySpecified, planText, threshold = 8) {
  return fullySpecified && plannedSourceFiles(planText) <= threshold
    ? 'quick-impl'
    : 'impl'
}

function sandboxAllowed(stageOn, repo, repos) {
  if (!stageOn) return false
  const basename = String(repo || '').replace(/\\/g, '/').split('/').filter(Boolean).pop() || ''
  return [repos && repos.frontend, repos && repos.backend].filter(Boolean).includes(basename)
}

function sandboxRoots() {
  const repos = (FORGE_CONFIG && FORGE_CONFIG.repos) || {}
  return {
    frontend: `/app/${repos.frontend || 'frontend'}`,
    backend: `/app/${repos.backend || 'backend'}`,
  }
}

function backendPrefix(root) {
  return `cd ${root} && { [ -f /app/env.sh ] && . /app/env.sh || true; }`
}

function sandboxCheck(isUi, testPaths = ['tests/unit']) {
  const roots = sandboxRoots()
  return isUi
    ? `cd ${roots.frontend} && yarn tsc --noEmit`
    : `${backendPrefix(roots.backend)} && uv run pytest ${testPaths.join(' ')} -x -q`
}

function configuredLenses() {
  const configured = (FORGE_CONFIG && FORGE_CONFIG.lenses) || DEFAULT_LENSES
  return LENSES.map(lens => lens.paths
    ? lens
    : { ...lens, paths: configuredLensPattern(configured[lens.configKey], DEFAULT_LENSES[lens.configKey]) })
}

function configuredLensPattern(value, fallback) {
  const pattern = typeof value === 'string' && value.length <= 500 ? value : fallback
  // Lens expressions come from local Forge configuration and are length-bounded before compilation.
  return new RegExp(pattern, 'i') // nosemgrep: javascript.lang.security.audit.detect-non-literal-regexp.detect-non-literal-regexp
}

function ticketLinks() {
  const template = (FORGE_CONFIG && FORGE_CONFIG.ticketUrl) || ''
  return PARAMS.tickets.map(key => ({ key, url: template ? template.replace('<KEY>', key) : '' }))
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
  triage: () => ({ verdicts: dryFindings().map(finding => ({ file: finding.file, line: finding.line, real: 'yes', worthIt: true, why: 'dry-run confirmed' })) }),
  judge: () => ({ decisions: dryFindings().map(finding => ({ id: findingKey(finding), verdict: 'respec', instruction: finding.fix_hint, reason: 'dry-run respec' })), cannotDecide: false }),
  lens: () => ({ verdict: 'approve', score: 5, findings: [], disputes: [] }),
  gate: opts => {
    const forcedFailure = PARAMS.dryRunFailGate === opts.label
      || (PARAMS.dryRunFailGate && dryRunJournal.some(entry => entry.role === 'gate' && entry.label === PARAMS.dryRunFailGate))
    return forcedFailure
      ? { passed: false, failures: [{ tool: 'tests', summary: 'dry-run forced failure', file: null, line: null }], commands: ['dry-run gate'], files: ['auth/api/client.py'], diff: 'dry-run diff', diffPath: `${PARAMS.runDir}/gate-dry-run.diff`, diffBytes: 23 }
      : { passed: true, failures: [], commands: ['dry-run gate'], files: ['auth/api/client.py'], diff: 'dry-run diff', diffPath: `${PARAMS.runDir}/gate-dry-run.diff`, diffBytes: 23 }
  },
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
  changedFiles: opts => opts.schema === ACK_SCHEMA
    ? { written: true }
    : opts.schema === FORGE_CONFIG_SCHEMA
    ? { roles: {}, stages: { sandbox: false, ff_review: false, qa_login: false }, thresholds: { quickReviewThreshold: 8 }, lenses: DEFAULT_LENSES, ticketUrl: '', repos: { frontend: '', backend: '' } }
    : {
      files: ['auth/api/client.py'], preexisting: [], commandSucceeded: true, diffPath: `${PARAMS.runDir}/review-dry-run.diff`, diffBytes: 12, diffLines: 1, diffValid: true, planSummary: 'dry-run plan summary',
      criteria: PARAMS.criteria, checklist: 'dry-run checklist', standards: 'dry-run code standards', testPaths: ['tests/unit'], error: '',
      contract: 'dry-run public contract', reviewerContract: 'dry-run reviewer contract',
    },
  readConfig: () => ({ roles: {}, stages: { sandbox: false, ff_review: false, qa_login: false }, thresholds: { quickReviewThreshold: 8 }, lenses: DEFAULT_LENSES, ticketUrl: '', repos: { frontend: '', backend: '' } }),
  handoff: opts => opts.schema === ACK_SCHEMA ? { written: true } : { handoffPath: `${PARAMS.runDir}/handoff.md` },
  trim: () => ({ written: true }),
  codexWrap: opts => {
    if (opts.schema === CODEX_RESULT) return { codexInvoked: true, threadMode: 'start', threadExists: true, filesChanged: ['auth/api/client.py'], testsWritten: 0, summary: 'dry-run Codex', error: '' }
    if (opts.schema === CODEX_REVIEW_SCHEMA) return { codexInvoked: true, threadMode: 'start', threadExists: true, review: { verdict: PARAMS.dryRunFindings ? 'request_changes' : 'approve', score: PARAMS.dryRunFindings ? 2 : 5, findings: dryFindings(), disputes: [] }, error: '' }
    if (opts.schema === CODEX_FIX_SCHEMA) return { codexInvoked: true, threadMode: opts.label === 'fix-1' ? 'start' : 'resume', threadExists: true, fix: { fixed: [], couldNotFix: [], touchedFiles: opts.label === 'fix-1' && PARAMS.dryRunFindings ? ['auth/api/client.py'] : [], diff: '', notes: 'dry-run fix' }, error: '' }
    if (opts.schema === VERIFY_SCHEMA) return { codexInvoked: true, threadMode: 'start', threadExists: true, clean: !PARAMS.dryRunStubborn, results: dryFindings().map(finding => ({ file: finding.file, line: finding.line, status: PARAMS.dryRunStubborn ? 'STILL BROKEN' : 'RESOLVED', reason: finding.claim })), unresolved: PARAMS.dryRunStubborn ? dryFindings() : [], contractViolations: [], error: '' }
    return { written: true }
  },
}

const decisions = []
if (canonicalLane !== requestedLane) decisions.push(`Lane alias ${requestedLane} canonicalized to build`)
const dryRunJournal = []
const __test = {
  plannedSourceFiles,
  partitionTriage,
  pickImplRole,
  sandboxAllowed,
  sandboxCheck,
  dryRunJournal,
  codexAgent,
}
const runtimeAgent = agent
let spawnCount = 0
let capBlocked = false

async function decide(text) {
  decisions.push(text)
}

function configRoleForTier(tierRole) {
  const mapped = ROLE_MAP[tierRole] || []
  if (tierRole === 'implementer') return pickImplRole(PARAMS.lane, PARAMS.fullySpecified, PARAMS.planText, quickReviewThreshold())
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
  const isHandoff = role === 'handoff' && opts.label === 'handoff'
  const limit = isHandoff ? PARAMS.spawnCap : PARAMS.spawnCap - 1
  if (spawnCount >= limit) {
    if (!isHandoff && !capBlocked) {
      capBlocked = true
      decisions.push(`Spawn cap ${PARAMS.spawnCap} reached; ordinary workflow calls stopped with the final slot reserved for handoff.`)
    }
    return null
  }
  const profile = tierProfile(role)
  if (!profile) throw new Error(`unknown tier role: ${role}`)
  spawnCount++
  const callOpts = { ...opts, model: profile.model, effort: profile.effort }
  if (PARAMS.dryRun) {
    dryRunJournal.push({ role, label: opts.label || role, prompt })
    return STUBS[role](opts)
  }
  let result = await runtimeAgent(prompt, callOpts)
  if (result === null && profile.model === 'fable') {
    if (spawnCount >= PARAMS.spawnCap - 2) {
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
const codexWrapper = `Read ~/.claude/skills/forge/references/codex-wrapper.md and follow it exactly. ${dryRunInstruction}`

// Normalize wrapper errors and retry a real error once before assertCodex throws. A Codex process
// still holding the helper lock surfaces as CODEX_LOCK_TIMEOUT and throws after that retry.
// A null result means the spawn cap was hit and is not retried.
async function codexAgent(prompt, opts) {
  let result = await agentT('codexWrap', prompt, opts)
  if (result) result.error = normalizedCodexError(result.error)
  if (result && result.codexInvoked === true && result.error) {
    const terminalError = /^(?:CODEX_DIFF_INVALID|CODEX_BUDGET_EXCEEDED|CODEX_NO_CREDITS)\b/.test(result.error)
    if (terminalError) return result
    await decide(`${opts.label} wrapper returned an error (${result.error.slice(0, 200)}); retrying once.`)
    result = await agentT('codexWrap', `${prompt}\nattempt=${Date.now()}`, { ...opts, label: `${opts.label}-error-retry` })
    if (result) result.error = normalizedCodexError(result.error)
    return result
  }
  if (result === null || result.codexInvoked === true) return result
  if (result.threadMode === 'start' && result.threadExists === true) return result
  await decide(`${opts.label} wrapper returned without invoking Codex (${String(result.error || 'no error text').slice(0, 200)}); retrying once.`)
  result = await agentT('codexWrap', `${prompt}\nattempt=${Date.now()}`, { ...opts, label: `${opts.label}-retry` })
  if (result) result.error = normalizedCodexError(result.error)
  return result
}

function normalizedCodexError(error) {
  if (error === null || error === undefined) return ''
  const normalized = String(error).trim()
  return normalized === '""' || normalized === "''" ? '' : normalized
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
  const error = normalizedCodexError(result.error)
  if (error) {
    throw new Error(`Codex assertion failed at ${where}: wrapper returned an error: ${error.slice(0, 300)}`)
  }
  return true
}

function assertImplementation(result, where) {
  const role = pickImplRole(PARAMS.lane, PARAMS.fullySpecified, PARAMS.planText, quickReviewThreshold())
  if ((configuredRole(role) || {}).provider !== 'claude') return assertCodex(result, where)
  if (!result || result.error) {
    throw new Error(`Claude implementation failed at ${where}: ${(result && result.error) || 'agent returned null'}`)
  }
  return true
}

async function loadForgeConfig() {
  const result = FORGE_CONFIG || await agentT('readConfig', `Read ~/.claude/skills/forge/forge.config.json with a ranged sed read. Return its roles, stages, thresholds, lenses, ticketUrl, repos, and ghEnvUnset. If it is missing or invalid, use the documented defaults. Do not read repository files.`,
    { label: 'read-config', phase: 'Implement', schema: FORGE_CONFIG_SCHEMA })
  const defaults = {
    roles: {}, stages: { sandbox: false, ff_review: false, qa_login: false },
    thresholds: { quickReviewThreshold: 8 }, lenses: DEFAULT_LENSES,
    ticketUrl: '', repos: { frontend: '', backend: '' }, ghEnvUnset: {},
  }
  FORGE_CONFIG = {
    ...defaults, ...(result || {}),
    thresholds: { ...defaults.thresholds, ...((result && result.thresholds) || {}) },
    lenses: { ...defaults.lenses, ...((result && result.lenses) || {}) },
    repos: { ...defaults.repos, ...((result && result.repos) || {}) },
  }
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`
}

function baselineContext() {
  return agentT('changedFiles', `Execute exactly one command and return its stdout JSON unchanged: python3 ~/.claude/skills/forge/scripts/run_context.py baseline --run-dir ${shellQuote(PARAMS.runDir)} --repo ${shellQuote(PARAMS.projectDir)}`,
    { label: 'baseline', phase: 'Implement', schema: ACK_SCHEMA })
}

function fullTestPromptInstruction() {
  return `With ranged reads, read ~/.claude/skills/forge/forge.config.json, resolve the gate entry for ${PARAMS.projectDir}, and name its exact tests command in the Codex prompt under FULL TEST COMMAND. Tell Codex to run that full test command before returning; the gate re-runs it, and Codex's run is the first line of defense. Codex must include the test summary line in summary and never report tests as intentionally skipped.`
}

function runBeforeReturningInstruction() {
  return 'Before returning, run service-free tests relevant to the touched files, ruff check, ruff format --check, makemigrations --check --dry-run in Django repositories, and Semgrep when installed. Fix what they report; the gate remains authoritative.'
}

function implement() {
  const implementationRole = pickImplRole(PARAMS.lane, PARAMS.fullySpecified, PARAMS.planText, quickReviewThreshold())
  if ((configuredRole(implementationRole) || {}).provider === 'claude') {
    return agentT('implementer', `Implement this confirmed Forge plan in ${PARAMS.projectDir}. Never commit or ship. With ranged reads, read ~/.claude/skills/forge/forge.config.json, resolve the gate entry for this repository, and run its exact tests command before returning. The gate re-runs it; include the test summary line in summary and never report tests as intentionally skipped. Write the implementation summary to ${PARAMS.runDir}/implementation-summary.md. Report live-dependent capabilities under unverified.\n\nPLAN\n${PARAMS.planText}`,
      { label: 'implement', phase: 'Implement', schema: IMPL_RESULT, agentType: 'claude-implementer' })
  }
  const promptPath = `${PARAMS.runDir}/implement-prompt.md`
  const logPath = `${PARAMS.runDir}/codex-implement.jsonl`
  const outPath = `${PARAMS.runDir}/codex-implement-final.md`
  return codexAgent(`You orchestrate the IMPLEMENT stage. ${codexWrapper}
Read ~/.claude/skills/forge/references/implementer.md and ~/.claude/skills/forge/references/code-standards.md in full. ${fullTestPromptInstruction()} Write ${promptPath} as a self-contained Codex prompt containing the implementer contract, then the code-standards contents verbatim, then the full text of ${PLAN} under a PLAN heading and of ${PARAMS.runDir}/context.md (if present) under a CONTEXT heading, and of ${PARAMS.runDir}/recon.md (if present) under a RECON heading. Do not tell Codex to read those files, AGENTS.md, or CLAUDE.md; Codex loads AGENTS.md itself. Implement only the confirmed plan and its test strategy. ${runBeforeReturningInstruction()} Do not commit, and write ${PARAMS.runDir}/implementation-summary.md. If ${PLAN} declares a Phase 0 evidence harness, build it first and keep it runnable; report every live-dependent capability as implemented-unverified — a worker-run harness against a live target is what marks it verified.
Run test -f ${CODEX_IMPL_THREAD} && MODE=resume || MODE=start, then invoke exactly: bash ${CODEX_SH} "$MODE" --thread-file ${CODEX_IMPL_THREAD} --prompt-file ${promptPath} --cd ${PARAMS.projectDir} --sandbox workspace-write --writable ${PARAMS.runDir} ${codexImplFlags()} --log ${logPath} --out ${outPath}. Collect changed and untracked files. Return the structured result.`,
  { label: 'implement', phase: 'Implement', schema: CODEX_RESULT })
}

function localGate(label = 'gate', gatePhase = 'Gate', files = [], only = []) {
  const quote = value => `'${String(value).replace(/'/g, `'\\''`)}'`
  const filesArg = files.length ? ` --files ${files.map(quote).join(' ')}` : ''
  const onlyArg = only.length ? ` --only ${only.join(',')}` : ''
  return agentT('gate', `Run exactly: \`bash ~/.claude/skills/forge/scripts/gate.sh --repo ${quote(PARAMS.projectDir)} --run-dir ${quote(PARAMS.runDir)} --label ${label}${onlyArg}${filesArg}\`. Return its stdout JSON as your structured output without changes. If the script exits 2 or prints no JSON, return \`{ passed: false, failures: [{ tool: 'gate.sh', summary: "gate.sh could not run (exit 2: config or usage error): <stderr tail>", file: null, line: null }], commands: [] }\`.`,
  { label, phase: gatePhase, schema: GATE_SCHEMA })
}

function gateFindings(gate) {
  return (gate.failures || []).map(failure => {
    const locations = [...String(failure.summary || '').matchAll(/(\S+?):(\d+)\b/g)]
      .filter(match => !match[1].includes('://'))
    const location = locations[locations.length - 1]
    return {
      file: failure.file || (location ? location[1] : ''),
      line: failure.line || (location ? Number(location[2]) : 0),
      severity: 'HIGH',
      claim: `${failure.tool}: ${failure.summary}`,
      fix_hint: 'Resolve this gate failure only.',
      source: 'gate',
      tool: failure.tool,
    }
  })
}

async function gateWithFixes(label, files, threadFile, context, phaseLabel) {
  let gate = await localGate(label, phaseLabel, files)
  const touchedFiles = []
  if (!gate || !gate.passed) {
    const findings = gateFindings(gate || { failures: [{ tool: 'gate', summary: 'agent returned null', file: null, line: null }] })
    const fix = await fixAgent(findings, context, `fix-${label}`, threadFile, phaseLabel)
    if (!fix) return { gate, touchedFiles, blocked: true, needsJudge: false }
    touchedFiles.push(...(fix.touchedFiles || []))
    files = [...new Set([...files, ...touchedFiles])]
    gate = await localGate(`${label}-retry`, phaseLabel, files)
  }
  if (!gate || !gate.passed) {
    const findings = gateFindings(gate || { failures: [{ tool: 'gate', summary: 'agent returned null', file: null, line: null }] })
    const judge = await agentT('judge', `Judge this repeated gate failure. Dismiss only a false finding, respec with exact fix instructions, or mark fixed if the code already contains the fix. Set cannotDecide=true if current evidence is insufficient. Findings: ${JSON.stringify(findings.map(item => ({ id: findingKey(item), finding: item })))}\n\nPUBLIC API CONTRACT\n${context.contract || '(none declared)'}`,
      { label: `judge-${label}`, phase: phaseLabel, schema: JUDGE_SCHEMA, agentType: 'judge' })
    if (!judge || judge.cannotDecide) return { gate, touchedFiles, blocked: true, needsJudge: true }
    const respecified = findings.flatMap(finding => {
      const decision = (judge.decisions || []).find(item => item.id === findingKey(finding))
      if (!decision || decision.verdict !== 'respec') return []
      return [{ ...finding, fix_hint: decision.instruction || finding.fix_hint }]
    })
    if (respecified.length) {
      const fix = await fixAgent(respecified, context, `fix-${label}-2`, `${threadFile}-2`, phaseLabel)
      if (!fix) return { gate, touchedFiles, blocked: true, needsJudge: false }
      touchedFiles.push(...(fix.touchedFiles || []))
      files = [...new Set([...files, ...touchedFiles])]
    }
    gate = await localGate(`${label}-retry2`, phaseLabel, files)
  }
  return { gate, touchedFiles, blocked: !gate || !gate.passed, needsJudge: false }
}

function stopped(state) {
  return state.needsJudge || state.status === 'BLOCKED' || state.status === 'READY_FOR_HUMAN'
}

function changedFiles(allDirty = false) {
  const mode = allDirty ? ' --all-dirty' : ''
  const base = PARAMS.lane === 'review' ? ` --base ${shellQuote(args.base || 'main')}` : ''
  return agentT('changedFiles', `Execute exactly one command and return its stdout JSON unchanged: python3 ~/.claude/skills/forge/scripts/run_context.py context --run-dir ${shellQuote(PARAMS.runDir)} --repo ${shellQuote(PARAMS.projectDir)} --plan-file ${shellQuote(PLAN)} --label gate${mode}${base}`,
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

function diffSection(context, codex = false) {
  return codex
    ? `DIFF: inlined by codex-exec.sh --inline-diff ${context.diffPath}`
    : `Diff file: ${context.diffPath} (${context.diffLines} lines). Read it with the Read tool in ranges of at most 2000 lines; never paste it.`
}

function reviewerPrompt(identity, focus, context, codex = false) {
  return `${identity === 'Codex general' ? '' : `${context.reviewerContract}\n\n`}You are the ${identity} reviewer. Review independently; do not inspect review transcripts or other reviewers' findings. ${focus} Ground findings in your own evidence: if ${PARAMS.runDir}/STATUS.json or harness output files (selfcheck*.json, parity.json, smoke/) exist, read them; never rely on the implementer's or fixer's summary. The named diff file is the review source; read repository files only to confirm a specific file:line it touches, with ranged reads.
Use disputes only for a concrete concern at a file:line that you examined and explicitly reject, with the evidence in reason. Return exactly the review schema.

PROJECT DIR
${PARAMS.projectDir}
Every path in the diff and in your findings is relative to this directory. Confirm a file:line only with an absolute path under it (sed -n 'A,Bp' ${PARAMS.projectDir}/<path>); never resolve a path against your own working directory.

${diffSection(context, codex)}

PLAN SUMMARY
${planSummary(context)}

PUBLIC API CONTRACT (score the implementation against this; deviations are findings):
${context.contract || '(none declared)'}

ACCEPTANCE CRITERIA
${JSON.stringify(acceptanceCriteria(context))}

REVIEW CHECKLIST
${context.checklist}

FLAG VIOLATIONS OF THESE CODE STANDARDS
${context.standards}`
}

async function codexReview(context) {
  const review = reviewerPrompt('Codex general', 'Assess every checklist item and acceptance criterion.', context, true)
  const result = await codexAgent(`You orchestrate the CODEX general review. ${codexWrapper}
Write ${PARAMS.runDir}/codex-review-prompt.md with the exact reviewer prompt below; add nothing (the helper prepends the prompt contract). Run test -f ${CODEX_REVIEW_THREAD} && MODE=resume || MODE=start, then invoke exactly: bash ${CODEX_SH} "$MODE" --thread-file ${CODEX_REVIEW_THREAD} --prompt-file ${PARAMS.runDir}/codex-review-prompt.md --inline-diff ${context.diffPath} --cd ${PARAMS.projectDir} --sandbox read-only ${CODEX_REVIEW_FLAGS} --log ${PARAMS.runDir}/codex-review.jsonl --out ${PARAMS.runDir}/codex-review-final.md. Return invocation evidence plus Codex's REVIEW_SCHEMA result in the wrapper schema without adding findings.

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
    const key = findingKey(finding)
    if (!seen.has(key)) {
      seen.add(key)
      findings.push({ ...finding, reviewer: row.key })
    }
  }
  return findings
}

function findingKey(finding) {
  return JSON.stringify([finding.file || '', finding.line || 0, String(finding.claim || '').slice(0, 200)])
}

function partitionTriage(findings, verdicts, auto = false) {
  const fix = []
  const disputes = []
  const dropped = []
  for (const finding of findings) {
    const verdict = (verdicts || []).find(item => item.file === finding.file && item.line === finding.line)
    if (!verdict || verdict.real === 'uncertain') {
      if (auto) fix.push(finding)
      else disputes.push({ finding, reason: verdict ? verdict.why : 'triage returned no verdict' })
    } else if (verdict.real === 'yes' && verdict.worthIt) {
      fix.push(finding)
    } else {
      dropped.push({ finding, reason: verdict.why })
    }
  }
  return { fix, disputes, dropped }
}

function triageFindings(findings, context, label = 'triage') {
  if (!findings.length) return Promise.resolve({ verdicts: [] })
  return agentT('triage', `Triage every review finding against the current file:line before any fixer runs. Use ranged reads only, remain read-only, and decide whether the claim is real and worthwhile to fix. Return one verdict per finding. Findings: ${JSON.stringify(findings)}\n\n${diffSection(context)}`,
    { label, phase: 'Review', schema: TRIAGE_SCHEMA, agentType: 'triage' })
}

async function applyRulings(findings, contradictions) {
  const dropped = new Set()
  const applied = new Set()
  const unresolved = []
  for (const contradiction of contradictions) {
    const finding = contradiction.finding
    const ruling = (PARAMS.rulings || []).find(item => item.file === finding.file && item.line === finding.line)
    if (ruling) {
      const key = JSON.stringify([finding.file, finding.line])
      if (ruling.decision === 'drop') dropped.add(key)
      else applied.add(key)
    } else if (PARAMS.auto) {
      await decide(`Auto ruling applied ${finding.file}:${finding.line} conservatively: ${finding.claim}`)
    } else {
      unresolved.push(contradiction)
    }
  }
  for (const finding of findings) {
    const ruling = (PARAMS.rulings || []).find(item => item.file === finding.file && item.line === finding.line)
    if (ruling) {
      const key = JSON.stringify([finding.file, finding.line])
      if (ruling.decision === 'drop') dropped.add(key)
      else applied.add(key)
    }
  }
  return {
    unresolved,
    applied: findings.filter(finding => applied.has(JSON.stringify([finding.file, finding.line]))),
    confirmed: findings.filter(finding => {
      const key = JSON.stringify([finding.file, finding.line])
      return !dropped.has(key) && !applied.has(key)
    }),
  }
}

async function reviewPanel(context) {
  if (!context.diffValid) return { status: 'BLOCKED', reason: 'review diff invalid' }
  const selected = configuredLenses().filter(lens => (context.files || []).some(file => lens.paths.test(file)))
  const reviewProvider = (configuredRole('review') || {}).provider || 'codex'
  const specs = []
  if (reviewProvider === 'codex') specs.push({ key: 'codex', lens: false, run: () => codexReview(context) })
  specs.push({ key: 'claude', lens: false, run: () => claudeReview(context) })
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
  const triage = await triageFindings(ruled.confirmed, context)
  let partitioned
  if (triage) {
    partitioned = partitionTriage(ruled.confirmed, triage.verdicts, PARAMS.auto)
  } else {
    await decide('Triage agent returned no result; retaining the pre-triage confirmed findings.')
    partitioned = { fix: ruled.confirmed, disputes: [], dropped: [] }
  }
  for (const item of partitioned.dropped) {
    await decide(`Triage dropped ${item.finding.file}:${item.finding.line}: ${item.reason}`)
  }
  const unresolvedDisputes = [...ruled.unresolved, ...partitioned.disputes]
  return { reviews: rows, findings, disputes, unresolvedDisputes, confirmed: [...ruled.applied, ...partitioned.fix], failures, returned: present.length }
}

function unresolvedAfterVerification(items, verify) {
  const unresolved = []
  const malformed = !Array.isArray(verify.results) || verify.results.length === 0
  for (const finding of items) {
    if (malformed) { unresolved.push(finding); continue }
    const matches = verify.results.filter(result => result.file === finding.file && result.line === finding.line)
    if (matches.length === 0 || matches.some(match => match.status === 'STILL BROKEN')) unresolved.push(finding)
  }
  const seen = new Set(unresolved.map(findingKey))
  for (const finding of verify.unresolved || []) {
    const key = findingKey(finding)
    if (!seen.has(key)) {
      seen.add(key)
      const original = items.find(item => findingKey(item) === key)
      unresolved.push(original && original.source ? { ...finding, source: original.source } : finding)
    }
  }
  for (const violation of verify.contractViolations || []) {
    const finding = { ...violation, severity: 'HIGH', fix_hint: 'Match the public API contract.' }
    const key = findingKey(finding)
    if (!seen.has(key)) {
      seen.add(key)
      unresolved.push(finding)
    }
  }
  return unresolved
}

async function fixAgent(items, context, label, threadFile, fixPhase = 'Fix') {
  const round = Number(label.match(/(\d+)$/)?.[1] || 1)
  const reviewDiffPath = (context && context.diffPath) || `${PARAMS.runDir}/gate-gate.diff`
  const findingFileCount = new Set(items.map(item => item.file).filter(isSourcePath)).size
  const implementationRole = findingFileCount <= quickReviewThreshold() ? 'quick-impl' : 'impl'
  if ((configuredRole(implementationRole) || {}).provider === 'claude') {
    const result = await agentT('implementer', `Fix only these confirmed findings in ${PARAMS.projectDir}: ${JSON.stringify(items)}. Verify each against current code first. Do not commit or ship. ${runBeforeReturningInstruction()} Include the test summary line in summary and never report tests as intentionally skipped.`,
      { label, phase: fixPhase, schema: IMPL_RESULT, agentType: 'claude-implementer' })
    if (!result || result.error) return null
    return { fixed: items.map(item => item.claim), couldNotFix: [], touchedFiles: result.filesChanged, diff: '', notes: result.summary }
  }
  const result = await codexAgent(`You orchestrate FIX ROUND ${round} (${label}). ${codexWrapper}
Read ~/.claude/skills/forge/references/code-standards.md in full. Write ${PARAMS.runDir}/${label}-prompt.md as a self-contained Codex prompt containing those standards verbatim, this confirmed file:line finding list as JSON, and the instruction to verify each claim against current code and fix only findings that are real: ${JSON.stringify(items)}. With ranged reads, include ${PARAMS.runDir}/implementation-summary.md when present and the review diff at ${reviewDiffPath} when present. Do not refactor adjacent code or commit. ${runBeforeReturningInstruction()} A failure caused by an unreachable service (Redis, Postgres, Docker, network, a missing binary) is environmental: list it under couldNotFix with the evidence and never change tests, fixtures, caches, or settings to route around it. Work in ${PARAMS.projectDir}.
Run MODE=start, then invoke exactly: bash ${CODEX_SH} "$MODE" --fresh --thread-file ${threadFile} --prompt-file ${PARAMS.runDir}/${label}-prompt.md --cd ${PARAMS.projectDir} --sandbox workspace-write --writable ${PARAMS.runDir} ${codexFlags(implementationRole, args.codexModelImpl || args.codexModel, args.codexEffortImpl)} --log ${PARAMS.runDir}/codex-${label}.jsonl --out ${PARAMS.runDir}/codex-${label}-final.md. Return invocation evidence plus touched files and git diff limited to 12000 characters in the wrapper schema.`,
  { label, phase: fixPhase, schema: CODEX_FIX_SCHEMA })
  if (!assertCodex(result, label)) return null
  return result.fix
}

function verifyFixes(items, fixResult, round, context = {}) {
  const diff = String(fixResult.diff || '').slice(0, 12000)
  if ((configuredRole('review') || {}).provider === 'claude') {
    return agentT('reviewer', `Verify only these findings after the fix: ${JSON.stringify(items)}. Inspect the current code and mark each result RESOLVED, STILL BROKEN, or REBUTTAL ACCEPTED. Check every fix against this public API contract and return deviations in contractViolations: ${(context && context.contract) || '(none declared)'}. Raise no other new findings.`,
      { label: `verify-${round}`, phase: 'Fix', schema: VERIFY_SCHEMA, agentType: 'reviewer' })
  }
  return codexAgent(`You orchestrate FIX VERIFICATION ROUND ${round}. ${codexWrapper}
Write ${PARAMS.runDir}/verify-${round}-prompt.md as a self-contained Codex prompt with the confirmed findings below, the public API contract, and the fix diff. Ask the reviewer to mark every finding, including findings raised by the Fable reviewer, RESOLVED, STILL BROKEN, or REBUTTAL ACCEPTED. Verify only these findings plus contract compliance; test execution belongs to the gate. Return contract deviations only in contractViolations and raise no other new findings. Verify against the code and any harness evidence in ${PARAMS.runDir} (STATUS.json, selfcheck*.json); a finding is RESOLVED only if you can point at the changed code, not because the fixer said so.
FINDINGS: ${JSON.stringify(items)}
PUBLIC API CONTRACT:
${(context && context.contract) || '(none declared)'}
FIX DIFF (capped at 12000 characters): ${diff}
Run MODE=start, then invoke exactly: bash ${CODEX_SH} "$MODE" --fresh --thread-file ${PARAMS.runDir}/codex-verify-${round}.thread --prompt-file ${PARAMS.runDir}/verify-${round}-prompt.md --cd ${PARAMS.projectDir} --sandbox read-only ${CODEX_REVIEW_FLAGS} --log ${PARAMS.runDir}/codex-verify-${round}.jsonl --out ${PARAMS.runDir}/codex-verify-${round}-final.md. Translate without changing the verdicts.`,
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
    return { unresolved, fixesApplied, rounds, touchedFiles: touched, blocked: false, gatePassed: true, gate: null, gateRan: false }
  }
  let gate = null
  let verificationFailed = false
  let judgedWithoutProgress = 0
  let needsJudge = false
  for (let round = 1; unresolved.length && round <= 8; round++) {
    const beforeCount = unresolved.length
    const priorGatePassed = gate ? Boolean(gate.passed) : true
    const findingsToVerify = unresolved
    const fix = await fixAgent(unresolved, context, `fix-${round}`, `${PARAMS.runDir}/codex-fix-${round}.thread`)
    if (!fix) {
      verificationFailed = true
      break
    }
    const roundTouched = fix.touchedFiles || []
    touched.push(...roundTouched)
    fixesApplied = fixesApplied || roundTouched.length > 0
    const verify = await verifyFixes(findingsToVerify, fix, round, context)
    if (!assertVerification(verify, `verify-${round}`)) {
      verificationFailed = true
      break
    }
    unresolved = unresolvedAfterVerification(findingsToVerify, verify)
    gate = await localGate(`gate-fix-${round}`, 'Fix', [...new Set(touched)], ['tests'])
    if (gate && gate.passed) {
      unresolved = unresolved.filter(finding => finding.source !== 'gate' || finding.tool !== 'tests')
    } else {
      unresolved = [...unresolved, ...gateFindings(gate || { failures: [{ tool: 'gate', summary: 'agent returned null', file: null, line: null }] })]
    }
    const deduped = new Map(unresolved.map(finding => [findingKey(finding), finding]))
    unresolved = [...deduped.values()]
    rounds.push({ round, fix, gate, verify })
    await writeStatus({
      rounds: { fix: round },
      open_findings: unresolved.map(finding => ({ file: finding.file, line: finding.line, severity: finding.severity, summary: finding.claim })),
    }, 'Fix')
    const progressed = unresolved.length < beforeCount || (!priorGatePassed && Boolean(gate && gate.passed))
    if (progressed || !unresolved.length) {
      judgedWithoutProgress = 0
      continue
    }
    const judge = await agentT('judge', `Judge these unresolved findings after a fix, verification, and tests-only gate made no progress. Read current file:line evidence with ranged reads. For each finding id, dismiss it, respec it with exact instructions for one more implementation round, or mark it fixed so it goes directly through verification. Do not widen scope. If evidence cannot decide, set cannotDecide=true.\n\nFINDINGS\n${JSON.stringify(unresolved.map(item => ({ id: findingKey(item), finding: item })))}\n\nPUBLIC API CONTRACT\n${context.contract || '(none declared)'}`,
      { label: `judge-${round}`, phase: 'Fix', schema: JUDGE_SCHEMA, agentType: 'judge' })
    if (!judge || judge.cannotDecide) {
      needsJudge = true
      break
    }
    judgedWithoutProgress += 1
    const decisionsById = new Map((judge.decisions || []).map(item => [item.id, item]))
    const fixed = []
    unresolved = unresolved.flatMap(finding => {
      const decision = decisionsById.get(findingKey(finding))
      if (!decision) return [finding]
      if (decision.verdict === 'dismiss') return []
      if (decision.verdict === 'fixed') {
        fixed.push(finding)
        return []
      }
      return [{ ...finding, fix_hint: decision.instruction || finding.fix_hint }]
    })
    if (fixed.length) {
      const judgedVerify = await verifyFixes(fixed, { diff: '', touchedFiles: [] }, `${round}-judge`, context)
      if (!assertVerification(judgedVerify, `verify-${round}-judge`)) {
        verificationFailed = true
        break
      }
      unresolved.push(...unresolvedAfterVerification(fixed, judgedVerify))
    }
    if (judgedWithoutProgress >= 2 && unresolved.length) break
  }
  gate = await localGate('gate-final', 'Fix', [...new Set(touched)])
  if (gate && gate.passed) {
    unresolved = unresolved.filter(finding => finding.source !== 'gate')
  } else {
    unresolved = [...unresolved, ...gateFindings(gate || { failures: [{ tool: 'gate', summary: 'agent returned null', file: null, line: null }] })]
  }
  const blocked = verificationFailed || unresolved.length > 0 || !gate || !gate.passed
  return {
    unresolved, fixesApplied, rounds, touchedFiles: [...new Set(touched)], blocked, needsJudge,
    gatePassed: Boolean(gate && gate.passed), gate, gateRan: Boolean(gate),
  }
}

// The working tree can carry unrelated local work, including tracked secret-bearing env
// files; the shipper stages only the run's own files, never "whatever git status shows".
function stagingRules(files, context = {}) {
  const staged = [...new Set(context.files || [])]
    .filter(path => !String(path).split('/').includes('.envs') && !/(^|\/)\.env(?:\.|$)|\.env$/i.test(String(path)))
  const list = staged.length ? `Stage EXACTLY these paths, with 'git add -- <path> ...' and nothing else: ${JSON.stringify(staged)}. Run 'git add -- <path>' for every listed path even when it is absent from the working tree because an absent tracked path is a deletion; skip and report a path only when it is both absent and untracked ('git ls-files --error-unmatch <path>' fails).` : 'No run-owned files are eligible for staging.'
  return `${list} Never run 'git add -A', 'git add -u', or 'git add .'. Never stage any path under '.envs/', any '.env', '.env.*', or '*.env' file, or any file outside that list even if 'git status' shows it modified or untracked.`
}

function ghEnvironmentInstruction() {
  const basename = String(PARAMS.projectDir).replace(/\\/g, '/').split('/').filter(Boolean).pop() || ''
  const configured = (FORGE_CONFIG && FORGE_CONFIG.ghEnvUnset && FORGE_CONFIG.ghEnvUnset[basename]) || []
  const names = (PARAMS.ghEnvUnset || configured).map(String).filter(name => /^[A-Za-z_][A-Za-z0-9_]*$/.test(name))
  if (!names.length) return ''
  const prefix = names.map(name => `-u ${name}`).join(' ')
  return `Prefix every gh command with \`env ${prefix} gh ...\`. Git push over SSH needs no gh. `
}

function ship(existing = null, files = [], context = {}) {
  const prompt = existing
    ? `${ghEnvironmentInstruction()}You sync verified Forge fixes to the existing pull request. Follow ~/.claude/skills/ship-pr/SKILL.md and ~/.claude/skills/ship-pr/references/lessons.md. In ${PARAMS.projectDir}, stay on branch ${existing.branch}, commit current verified fixes, push them, and return the same non-draft PR metadata: ${JSON.stringify(existing)}. Update the PR body after the push. The body contains a summary, change list, and links; omit a testing-results section. Include only these configured ticket links: ${JSON.stringify(ticketLinks())}. ${stagingRules(files, context)}`
    : `${ghEnvironmentInstruction()}You run the SHIP stage. Follow ~/.claude/skills/ship-pr/SKILL.md and ~/.claude/skills/ship-pr/references/lessons.md. In ${PARAMS.projectDir}, resolve the repository base branch, create a descriptive branch, commit the implementation, push it, open a NON-draft PR, and return {branch, prUrl, prNumber, repo}. The PR body contains a summary, change list, and links; omit a testing-results section. Include only these configured ticket links: ${JSON.stringify(ticketLinks())}. ${stagingRules(files, context)}`
  return agentT('shipper', prompt, { label: existing ? 'ship-sync' : 'ship', phase: existing ? 'Fix' : 'Ship', agentType: 'shipper', schema: SHIP_SCHEMA })
}

function qaArtifactDraft(shipResult, context) {
  const criteria = acceptanceCriteria(context)
  return agentT('qaDraft', `You draft and open the QA artifact immediately after the pull request is pushed. Never fail the run: on any error return the attempted path, items=0, opened=false, and the error text.
1. Read lines 1-70 of ~/.claude/skills/forge/references/qa-artifact.html for its complete data and placeholder contract. Read ${PARAMS.runDir}/sandbox.json with ranged reads if it exists.
2. Write ${PARAMS.runDir}/qa-data.json. Set ticket=${JSON.stringify(PARAMS.ticket)}; derive shortTitle as 2-4 words from this plan summary: ${JSON.stringify(planSummary(context))}; set date to today; tier=${JSON.stringify(PARAMS.tierSandbox)}; branch=${JSON.stringify(shipResult.branch)}. Set sandboxId, previewUrl, rootLoginEmail, rootLoginPassword, and adminCreds from sandbox.json when present, otherwise "" so handoff can fill them. Set links=[{label:"Pull request",url:${JSON.stringify(shipResult.prUrl)}}]. Set contextItems to 2-4 concise lines from the plan summary.
Build qaItems with at least one item per affected code area by grouping these files by top-level app directory: ${JSON.stringify(context.files || [])}. Set jiraTickets from this exact configured list: ${JSON.stringify(ticketLinks())}, adding title="" and role="" to each row. Add one item per acceptance criterion not already covered: ${JSON.stringify(criteria)}. Every item has title, ticketKey, ticketUrl, before, whatChanged, why, steps with 2-6 concrete entries, expected, evidence="", pr=${JSON.stringify(String(shipResult.prNumber))}, a screenGroup guessed from its file area, and clickPass={status:"PENDING",note:"steward click pass pending",screenshot:""}. Wrap endpoint paths and commands in single backticks. Build users from sandbox.json testUsers and team entries as objects containing role and email only; never copy a password or token into users. Set every handoff key named by the template contract to "".
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
  const repoBase = String(PARAMS.repo).split('/').filter(Boolean).pop() || ''
  const isUi = repoBase === FORGE_CONFIG.repos.frontend
  const branchField = isUi ? 'ui_branch' : 'api_branch'
  const check = sandboxCheck(isUi, context.testPaths || ['tests/unit'])
  if (PARAMS.existingSandbox) {
    return agentT('sandboxQA', `You run SANDBOX QA for Forge against an existing sandbox. ${syncInstructions(PARAMS.existingSandbox, shipResult, context.files || [], isUi, false, check, sandboxToolFallback)}`,
    { label: 'sandbox-qa', phase: 'Sandbox', schema: SANDBOX_SCHEMA })
  }
  return agentT('sandboxQA', `You run SANDBOX QA for Forge. Read and follow references/stages/sandbox.md supplied by the overlay. ${sandboxToolFallback}
Create one sandbox with ${branchField}=${shipResult.branch}, tier=${PARAMS.tierSandbox}, and ide=True. Write its metadata to ${PARAMS.runDir}/sandbox.json. Record ide_url and ide_password only in that file; treat them as credentials and never return them in a message, summary, or structured output. Then run with timeout 900: ${check}. Return sandbox id, login URL, preview URL, test result, summary, and seedRecipe="". On any skip, return skipped=true, the reason, empty strings for sandboxId/loginUrl/previewUrl/summary/seedRecipe, and testsPassed=false.`,
  { label: 'sandbox-qa', phase: 'Sandbox', schema: SANDBOX_SCHEMA })
}

function syncInstructions(sandbox, shipResult, files, isUi, allowSkip, check, toolFallback) {
  const roots = sandboxRoots()
  const root = isUi ? roots.frontend : roots.backend
  const commandPrefix = isUi ? `cd ${root}` : backendPrefix(root)
  const branchField = isUi ? 'ui_branch' : 'api_branch'
  const branch = shipResult.branch
  const fileHint = files.length ? `${files.length} files changed: ${JSON.stringify(files)}` : '0 files supplied; the changed set is unknown'
  const migrate = `${backendPrefix(roots.backend)} && uv run python manage.py migrate --no-input`
  const skipAction = allowSkip
    ? 'Set mode="skip", skipped=false, testsPassed=false, and summary="fork already at <sha>; sync skipped" with the sync seconds. Return the same sandbox metadata immediately and DO NOT run the check command. The workflow may carry forward a prior passing result for this same fork.'
    : 'Set mode="skip" and summary="fork already at <sha>; sync skipped", but continue to the check command. This QA stage has no prior result to carry forward, so only the upload is skipped.'
  return `Existing sandbox metadata: ${JSON.stringify(sandbox)}. The branch is ${branch}; the file-count hint is ${fileHint}. Use the sandbox tools named by the overlay stage reference. ${toolFallback}
Perform these steps IN ORDER and measure elapsed seconds for the whole sync step:
1. Skip check. Locally in ${PARAMS.projectDir}, run git fetch origin ${branch} --quiet && git rev-parse origin/${branch} to get TIP. In sandbox ${sandbox.sandboxId}, use exec_command for ${commandPrefix} && git rev-parse HEAD to get FORK_HEAD, then ${commandPrefix} && git status --porcelain | wc -l to get DIRTY. If TIP equals FORK_HEAD and DIRTY is 0: ${skipAction} Otherwise continue.
2. Determine the changed set locally in ${PARAMS.projectDir} with git diff --name-only <FORK_HEAD> origin/${branch}, substituting the FORK_HEAD sha from step 1. Treat ${JSON.stringify(files)} only as a cross-check hint. If the derived set and hint disagree, report that in summary and use the derived set. If FORK_HEAD is not present locally or git diff errors, fall back to the hint when it is non-empty; otherwise use re-fork. Measure total bytes with wc -c against the corresponding files under ${PARAMS.projectDir}; deleted files count as zero bytes. The measured set and byte count control the choice.
3. Git-fetch first. In sandbox ${sandbox.sandboxId}, run: ${commandPrefix} && GIT_TERMINAL_PROMPT=0 git fetch origin ${branch} && git checkout -B ${branch} FETCH_HEAD. On success set mode="git-fetch". If the changed set contains a migrations/ path, run with timeout 600: ${migrate}; a non-zero migration is a blocker with the last 20 output lines in summary. Then ${isUi ? 'let vite reload itself' : 'restart the API process with the fork start script'}. Skip steps 4 and 5 and continue to step 6. If fetch or checkout fails, say so in summary and continue to the hot-patch fallback.
4. Hot-patch after a failed git-fetch only when the known changed set has at most 3 entries and totals at most 40000 bytes. Set mode="hot-patch". For each repo-relative path, use upload_file to upload inline text from ${PARAMS.projectDir}/<path> to ${root}/<path> in sandbox ${sandbox.sandboxId}; remove a deleted file with exec_command rm at ${root}/<path>. ${isUi ? 'The vite dev server hot-reloads.' : `If any path is under a migrations/ directory, first use exec_command with timeout 600 for: ${migrate}. A non-zero exit is a blocker: return skipped=true, put the last 20 output lines in summary, preserve the current sandbox metadata, and set testsPassed=false. Then restart the API process with the fork start script.`} Skip step 5 and continue to step 6.
5. Re-fork after a failed git-fetch when hot-patch is not allowed. Set mode="re-fork". Read ${PARAMS.runDir}/sandbox.json when present and retain its cohort and team values. Call create_sandbox with ${branchField}=${branch}, tier=${PARAMS.tierSandbox}, login_email="" for token injection, and ide=True; leave other arguments at their defaults. Treat ide_url and ide_password as credentials: write them only to ${PARAMS.runDir}/sandbox.json and never return them in a message, summary, or structured output. Wait until the tool reports the new sandbox healthy. If the changed set touches a migrations/ path, run in the NEW sandbox with timeout 600: ${migrate}. If migration exits non-zero, call teardown_sandbox on the NEW sandbox id without force and never retry with force; keep and return the OLD sandbox metadata, set skipped=true and testsPassed=false, and name the torn-down new id plus the migration's last 20 output lines in summary. Only after the new sandbox is healthy${isUi ? '' : ' and any migration succeeds'}, copy ${PARAMS.runDir}/sandbox.json when present to ${PARAMS.runDir}/sandbox.${sandbox.sandboxId}.json, then call teardown_sandbox on OLD sandbox ${sandbox.sandboxId}, without force. If teardown of the OLD sandbox fails, including a 403 because another developer owns it, report the failure in summary and continue on the NEW fork; never retry with force. Write ${PARAMS.runDir}/sandbox.json with the NEW sandbox metadata, the retained cohort and team when present, seedRecipe="${PARAMS.runDir}/sandbox.${sandbox.sandboxId}.json", and seedsReplayed=false. From this point, use and return the NEW sandboxId, loginUrl, previewUrl, and seedRecipe. The summary must say "seeds not replayed; recipe at ${PARAMS.runDir}/sandbox.${sandbox.sandboxId}.json".
6. Unless the allowed clean-fork skip returned early, run in the current sandbox with timeout 900: ${check}. Set testsPassed from its exit result and skipped=false.
Return sandboxId, loginUrl, previewUrl, mode, testsPassed, skipped, reason, summary, and seedRecipe ("" when none). Summary must report mode, measured file count, total bytes, seconds spent on the sync step, and the test result. On any tool-unavailable or blocker skip, return skipped=true, its reason, the current sandbox metadata, seedRecipe from that metadata or "", and testsPassed=false.`
}

function postSandboxMarker(shipResult, sandbox) {
  return agentT('shipper', `${ghEnvironmentInstruction()}Append the pull-request marker to the PR body exactly once on ${shipResult.prUrl}. Read the current body with \`gh pr view ${shipResult.prNumber} --repo ${shipResult.repo} --json body -q .body\`. ` +
  `If the body contains exactly \`<!-- forge-sandbox: ${sandbox.sandboxId} -->\`, do nothing. If it has a forge-sandbox marker with a different id, replace that entire marker line with exactly \`<!-- forge-sandbox: ${sandbox.sandboxId} -->\` and ensure exactly one marker remains. If it has no marker, append a blank line and that exact marker at the end. Save any changed whole body with gh pr edit --body-file. Never post a comment. Return {written: true} as before.`,
  { label: 'sandbox-marker', phase: 'Sandbox', agentType: 'shipper', schema: ACK_SCHEMA })
}

function writeStatus(patch, phaseLabel) {
  return agentT('trim', `Execute exactly one command and return its stdout JSON unchanged: python3 ~/.claude/skills/forge/scripts/status_merge.py --status ${shellQuote(`${PARAMS.runDir}/STATUS.json`)} --patch-json ${shellQuote(JSON.stringify(patch))}`,
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
  const repoBase = String(PARAMS.repo).split('/').filter(Boolean).pop() || ''
  const isUi = repoBase === FORGE_CONFIG.repos.frontend
  const check = sandboxCheck(isUi, context.testPaths || ['tests/unit'])
  return agentT('sandboxQA', `You run SANDBOX POST-FIX RE-RUN. ${syncInstructions(sandbox, shipResult, context.files || [], isUi, true, check, sandboxToolFallback)}`,
  { label: 'sandbox-refresh', phase: 'Fix', schema: SANDBOX_SCHEMA })
}

async function handoff(state, context) {
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
Then rewrite ${PARAMS.runDir}/STATE.md whole (never append) from ~/.claude/references/state-template.md with the run's current state, next steps, blockers, pointers (plan, decisions, STATUS.json, PR, branch, sandbox), and do-not-redo facts.
Return the handoff path.`,
  { label: 'handoff', phase: 'Handoff', schema: HANDOFF_SCHEMA })
}

async function fullLane() {
  phase('Implement')
  const implementationRole = pickImplRole(PARAMS.lane, PARAMS.fullySpecified, PARAMS.planText, quickReviewThreshold())
  await decide(`Implementation role selected: ${implementationRole} (${plannedSourceFiles(PARAMS.planText)} planned source files; threshold ${quickReviewThreshold()}).`)
  const initial = { status: 'DONE', implement: null, gate: null, ship: null, qaDraft: null, sandbox: null, smoke: null, review: null, convergence: null, sandboxRefresh: null }
  const rows = await pipeline(
    [initial],
    async state => {
      phase('Implement')
      state.implement = await implement()
      if (!assertImplementation(state.implement, 'implement')) state.status = 'BLOCKED'
      if (capBlocked && state.status !== 'READY_FOR_HUMAN') state.status = 'BLOCKED'
      return state
    },
    async state => {
      phase('Gate')
      if (stopped(state)) return state
      const gateRun = await gateWithFixes('gate', (state.implement && state.implement.filesChanged) || [], `${PARAMS.runDir}/codex-fix-gate.thread`, { standards: '', contract: PARAMS.planText }, 'Gate')
      state.gate = gateRun.gate
      if (state.implement) state.implement.filesChanged = [...new Set([...(state.implement.filesChanged || []), ...(gateRun.touchedFiles || [])])]
      if (!state.gate || !state.gate.passed) {
        state.status = 'BLOCKED'
        if (gateRun.needsJudge) state.needsJudge = true
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
      state.context = state.context || await changedFiles()
      if (contextFailed(state.context)) {
        state.status = 'BLOCKED'
        await decide(`Changed-file collection failed before ship: ${(state.context && state.context.error) || 'agent returned null'}`)
        return state
      }
      state.ship = await ship(null, (state.implement && state.implement.filesChanged) || [], state.context)
      if (!state.ship || state.ship.skipped) {
        state.status = 'BLOCKED'
        if (state.ship && state.ship.reason) await decide(state.ship.reason)
      }
      return state
    },
    async state => {
      phase('Sandbox')
      if (stopped(state) || !state.ship) return state
      state.context = await changedFiles()
      if (contextFailed(state.context)) {
        state.qaDraft = await qaArtifactDraft(state.ship, state.context || { files: [], criteria: PARAMS.criteria })
        if (!state.qaDraft) state.qaDraft = { path: `${PARAMS.runDir}/qa-artifact.html`, items: 0, opened: false, error: 'agent returned null' }
        state.status = 'BLOCKED'
        await decide(`Changed-file collection failed; review inputs are unavailable: ${(state.context && state.context.error) || 'agent returned null'}`)
        return state
      }
      if (!sandboxAllowed(configuredStage('sandbox'), PARAMS.repo, FORGE_CONFIG.repos)) {
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
      state.context = state.context || await changedFiles()
      state.review = await reviewPanel(state.context)
      if (state.review.status === 'BLOCKED') {
        state.status = 'BLOCKED'
        await decide(state.review.reason)
        return state
      }
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
      if (state.convergence.needsJudge) state.needsJudge = true
      if (state.convergence.blocked) {
        state.status = 'BLOCKED'
      }
      if (state.convergence.gateRan && !state.convergence.gatePassed) {
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
        state.context = await changedFiles()
        if (contextFailed(state.context) || !state.context.diffValid) {
          state.status = 'BLOCKED'
          await decide(`Changed-file collection failed before ship sync: ${(state.context && state.context.error) || 'review diff invalid'}`)
          return state
        }
        const synced = await ship(state.ship, [
          ...((state.implement && state.implement.filesChanged) || []),
          ...((state.convergence && state.convergence.touchedFiles) || []),
        ], state.context)
        if (!synced || synced.skipped) {
          state.status = 'BLOCKED'
          await decide((synced && synced.reason) || 'Verified fixes could not be pushed to the existing pull request.')
        } else {
          state.ship = synced
        }
        if (sandboxAllowed(configuredStage('sandbox'), PARAMS.repo, FORGE_CONFIG.repos) && state.sandbox && state.sandbox.sandboxId && synced && !synced.skipped) {
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
  if (!finalState) throw new Error('build lane produced no final state (a stage threw before the pipeline returned)')
  return finalState
}

async function reviewLane() {
  await decide('Review lane skipped Implement, standalone Gate, Ship, Sandbox, and Smoke stages.')
  phase('Review')
  const context = await changedFiles(true)
  if (contextFailed(context)) {
    await decide(`Changed-file collection failed; review inputs are unavailable: ${(context && context.error) || 'agent returned null'}`)
    return { status: 'BLOCKED', context: context || { criteria: PARAMS.criteria }, review: null, convergence: null, ship: null, sandbox: null, smoke: null, sandboxRefresh: null, gate: null, implement: null }
  }
  const review = await reviewPanel(context)
  if (review.status === 'BLOCKED') return { status: 'BLOCKED', context, review, convergence: null, ship: null, sandbox: null, smoke: null, sandboxRefresh: null, gate: null, implement: null }
  if ((configuredRole('review') || {}).provider !== 'claude' && review.failures.some(failure => failure.key === 'codex')) {
    await decide('CROSS-MODEL ASSERT FAILED: the Codex review did not run, so the review lane is BLOCKED instead of continuing Claude-only.')
    return { status: 'BLOCKED', context, review, convergence: null, ship: null, sandbox: null, smoke: null, sandboxRefresh: null, gate: null, implement: null }
  }
  if (review.unresolvedDisputes.length) return { needsJudge: true, context, review }
  phase('Fix')
  const convergence = await converge(review, context)
  if (convergence.needsJudge) return { needsJudge: true, context, review, convergence }
  const status = convergence.blocked || capBlocked ? 'BLOCKED' : 'DONE'
  return { status, context, review, convergence, ship: null, sandbox: null, smoke: null, sandboxRefresh: null, gate: null, implement: null }
}

await loadForgeConfig()
await baselineContext()
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
  dryRunJournal: PARAMS.dryRun ? dryRunJournal.map(entry => entry.label) : undefined,
}
