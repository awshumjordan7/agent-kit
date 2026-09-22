// forge-core.js runs inside the Workflow sandbox; filesystem work belongs to agents.

export const meta = {
  name: 'forge-core',
  description: 'Forge orchestration: implement, gate, ship, sandbox, independent review, bounded fixes, and handoff',
  phases: [
    { title: 'Implement', detail: 'Implementation by the configured provider' },
    { title: 'Gate', detail: 'Repository-native tests, lint, Semgrep, and migration checks' },
    { title: 'Checkpoint', detail: 'Fresh pre-ship recommendation and decision' },
    { title: 'Ship', detail: 'Branch, commit, push, and non-draft pull request' },
    { title: 'Sandbox', detail: 'Platform sandbox tests, signed-out and sign-in check, and criterion-driven smoke checks' },
    { title: 'Review', detail: 'Independent Codex, optional Claude, and path-selected lenses' },
    { title: 'Fix', detail: 'Capped decide-then-apply fix loop with re-gate and scoped verification' },
    { title: 'Handoff', detail: 'Run status, evidence, decisions, and manual QA' },
  ],
}

const TIERS = {
  fable: {
    implementer: { model: 'opus', effort: 'high' },
    reviewer: { model: 'fable', effort: 'high' },
    triage: { model: 'fable', effort: 'high' },
    decider: { model: 'opus', effort: 'high' },
    applier: { model: 'opus', effort: 'medium' },
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
    reviewer: { model: 'opus', effort: 'xhigh' },
    triage: { model: 'opus', effort: 'high' },
    decider: { model: 'opus', effort: 'high' },
    applier: { model: 'opus', effort: 'medium' },
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
  applier: ['quick-impl'],
  reviewer: ['review'],
  checkpoint: ['review'],
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
  tier: TIERS[args.tier] ? args.tier : 'opus',
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
  checkpointDecision: typeof args.checkpointDecision === 'string' ? args.checkpointDecision : null,
  smokeCommand: typeof args.smokeCommand === 'string' ? args.smokeCommand : '',
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
if (PARAMS.checkpointDecision && !['ship', 'smoke', 'qa'].includes(PARAMS.checkpointDecision)) {
  throw new Error(`unsupported checkpointDecision: ${PARAMS.checkpointDecision}; allowed values are ship, smoke, qa`)
}

const PHASES = PARAMS.lane === 'build' ? planPhases(PARAMS.planText) : []
const PHASED = PHASES.length >= 2
// Spawns one phase adds: implement, a possible Codex wrapper retry, commit, phases.json write, gate.
const PHASE_SPAWNS = 5
// Spawns a phased run adds once: phases.json read, branch switch, resume file scan, final phases.json write.
const PHASED_RUN_SPAWNS = 4
if (PHASED) PARAMS.spawnCap += PHASE_SPAWNS * PHASES.length + PHASED_RUN_SPAWNS
const GATE_CHECKOUT = `${PARAMS.runDir}/gate-checkout`
const EMPTY_PHASES_FILE = { branch: '', phases: [], lastCommittedPhase: null, headSha: null, pendingGates: [] }

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
    handoffs: { type: 'integer', minimum: 0, default: 0 },
    handoffDetails: { type: 'array', items: { type: 'object', additionalProperties: false, properties: { contextTokens: { type: 'integer' }, toolCalls: { type: 'integer' } }, required: ['contextTokens', 'toolCalls'] } },
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
    status: { type: 'string', enum: ['DONE', 'PARTIAL'] },
    progressFile: { type: ['string', 'null'] },
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
    gate: { type: 'object' },
  },
  required: ['roles', 'stages', 'thresholds', 'lenses', 'ticketUrl', 'repos'],
}
const CODEX_REVIEW_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    codexInvoked: { type: 'boolean' }, threadMode: { type: 'string', enum: ['start', 'resume'] },
    threadExists: { type: 'boolean' }, review: REVIEW_SCHEMA, error: { type: ['string', 'null'] },
    handoffs: { type: 'integer', minimum: 0, default: 0 },
    handoffDetails: { type: 'array', items: { type: 'object', additionalProperties: false, properties: { contextTokens: { type: 'integer' }, toolCalls: { type: 'integer' } }, required: ['contextTokens', 'toolCalls'] } },
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
    results: {
      type: 'array', items: {
        type: 'object', additionalProperties: false,
        properties: { id: { type: 'string' }, reason: { type: 'string' } },
        required: ['id', 'reason'],
      },
    },
  },
  required: ['fixed', 'couldNotFix', 'touchedFiles', 'diff', 'notes', 'results'],
}
const CODEX_FIX_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    codexInvoked: { type: 'boolean' }, threadMode: { type: 'string', enum: ['start', 'resume'] },
    threadExists: { type: 'boolean' }, fix: FIX_SCHEMA, error: { type: ['string', 'null'] },
    handoffs: { type: 'integer', minimum: 0, default: 0 },
    handoffDetails: { type: 'array', items: { type: 'object', additionalProperties: false, properties: { contextTokens: { type: 'integer' }, toolCalls: { type: 'integer' } }, required: ['contextTokens', 'toolCalls'] } },
  },
  required: ['codexInvoked', 'threadMode', 'threadExists', 'fix'],
}
const SCOPED_VERIFY_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    results: {
      type: 'array', items: {
        type: 'object', additionalProperties: false,
        properties: {
          id: { type: 'string' },
          status: { type: 'string', enum: ['RESOLVED', 'UNRESOLVED'] },
          reason: { type: 'string' },
        },
        required: ['id', 'status', 'reason'],
      },
    },
  },
  required: ['results'],
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
const FIX_SPEC_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    items: {
      type: 'array', items: {
        type: 'object', additionalProperties: false,
        properties: {
          id: { type: 'string' }, source: { type: 'string', enum: ['gate', 'review'] },
          action: { type: 'string', enum: ['fix', 'reject', 'defer'] }, reason: { type: 'string' },
          files: { type: 'array', items: { type: 'string' } }, change: { type: 'string' }, check: { type: 'string' },
        },
        required: ['id', 'source', 'action', 'reason', 'files', 'change', 'check'],
      },
    },
    cannotDecide: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' }, diffStat: { type: 'string' },
    applied: { type: 'boolean' },
    apply: { anyOf: [{ type: 'null' }, FIX_SCHEMA] },
  },
  required: ['items', 'cannotDecide', 'notes', 'diffStat', 'applied', 'apply'],
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
const CHECKPOINT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    recommendation: { type: 'string', enum: ['ship', 'smoke', 'qa'] },
    command: { type: 'string' }, reason: { type: 'string' }, summary: { type: 'string' },
  },
  required: ['recommendation', 'command', 'reason', 'summary'],
}
const PHASE_ROW_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    id: { type: 'string' }, title: { type: 'string' },
    sha: { type: ['string', 'null'] }, gate: { type: ['string', 'null'] },
  },
  required: ['id', 'title', 'sha', 'gate'],
}
const PHASES_FILE_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    branch: { type: 'string' },
    phases: { type: 'array', items: PHASE_ROW_SCHEMA },
    lastCommittedPhase: { type: ['string', 'null'] },
    headSha: { type: ['string', 'null'] },
    pendingGates: {
      type: 'array', items: {
        type: 'object', additionalProperties: false,
        properties: { id: { type: 'string' }, sha: { type: 'string' }, label: { type: 'string' } },
        required: ['id', 'sha', 'label'],
      },
    },
  },
  required: ['branch', 'phases', 'lastCommittedPhase', 'pendingGates'],
}
const BRANCH_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { branch: { type: 'string' } }, required: ['branch'],
}
const CHECKPOINT_FILE_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    recommendation: { type: 'string', enum: ['ship', 'smoke', 'qa'] },
    command: { type: 'string' }, reason: { type: 'string' }, summary: { type: 'string' },
    decidedBy: { type: 'string', enum: ['pending', 'auto', 'user'] },
    implementFilesChanged: { type: 'array', items: { type: 'string' } },
    context: CONTEXT_SCHEMA,
    branch: { type: 'string' },
    phases: { type: 'array', items: PHASE_ROW_SCHEMA },
  },
  required: ['recommendation', 'command', 'reason', 'summary', 'decidedBy', 'implementFilesChanged', 'context'],
}
const SMOKE_RUN_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    passed: { type: 'boolean' },
    exitCode: { type: 'integer' }, timedOut: { type: 'boolean' },
    command: { type: 'string' }, logPath: { type: 'string' }, summary: { type: 'string' },
  },
  required: ['passed', 'exitCode', 'timedOut', 'command', 'logPath', 'summary'],
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
const THREAD_CHECK_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { threadExists: { type: 'boolean' } }, required: ['threadExists'],
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

function planPhases(planText) {
  const heading = /^###\s+Phase\s+([A-Za-z]*[0-9]+):\s*(\S.*?)\s*$/
  const lines = String(planText || '').split(/\r?\n/)
  const start = lines.findIndex(line => /^##\s+Phases\s*$/i.test(line))
  if (start < 0) return []
  const phases = []
  let fenced = false
  for (const line of lines.slice(start + 1)) {
    if (/^\s*(?:```|~~~)/.test(line)) {
      fenced = !fenced
    } else if (!fenced && /^#{1,2}\s/.test(line)) {
      break
    } else if (!fenced && /^###\s/.test(line)) {
      const match = heading.exec(line)
      if (!match) throw new Error(`Plan heading under ## Phases must read "### Phase <id>: <title>" with an id such as 1 or A1: ${line.trim()}`)
      if (phases.some(item => item.id === match[1])) throw new Error(`Plan phase id ${match[1]} appears twice under ## Phases`)
      phases.push({ id: match[1], title: match[2], lines: [] })
      continue
    }
    if (phases.length) phases[phases.length - 1].lines.push(line)
  }
  return phases.map(({ id, title, lines: body }) => ({ id, title, text: body.join('\n').trim() }))
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

function dryRunSha(label) {
  let hash = 0
  for (const character of String(label)) hash = (hash * 31 + character.charCodeAt(0)) >>> 0
  return hash.toString(16).padStart(8, '0').repeat(5)
}

function dryFindings() {
  return Array.from({ length: PARAMS.dryRunFindings }, (_, index) => ({
    file: 'auth/api/client.py', line: index + 1, severity: 'HIGH',
    claim: `dry-run finding ${index + 1}`, fix_hint: 'fix the dry-run finding',
  }))
}

const STUBS = {
  implementer: opts => opts.schema === FIX_SCHEMA
    ? { fixed: [], couldNotFix: [], touchedFiles: PARAMS.dryRunFindings ? ['auth/api/client.py'] : [], diff: 'dry-run fix diff', notes: 'dry-run fix', results: dryFindings().map(finding => ({ id: findingKey(finding), reason: 'dry-run fix explanation' })) }
    : { filesChanged: ['auth/api/client.py'], testsWritten: false, summary: 'dry-run Claude implementation', unverified: [], error: null },
  reviewer: opts => opts.schema === SCOPED_VERIFY_SCHEMA
    ? { results: dryFindings().map(finding => ({ id: findingKey(finding), status: PARAMS.dryRunStubborn ? 'UNRESOLVED' : 'RESOLVED', reason: finding.claim })) }
    : { verdict: PARAMS.dryRunFindings ? 'request_changes' : 'approve', score: PARAMS.dryRunFindings ? 2 : 5, findings: dryFindings(), disputes: [] },
  checkpoint: () => PARAMS.dryRunFindings
    ? { recommendation: 'smoke', command: 'true', reason: 'A focused smoke command would verify the dry-run change.', summary: '- Changed the dry-run fixture\n- Gate evidence was recorded\n- A focused smoke remains' }
    : { recommendation: 'ship', command: '', reason: 'The passing gate already covers the change.', summary: '- Implemented the planned change\n- Gate verification passed\n- No further pre-ship check is needed' },
  triage: () => ({ verdicts: dryFindings().map(finding => ({ file: finding.file, line: finding.line, real: 'yes', worthIt: true, why: 'dry-run confirmed' })) }),
  decider: opts => {
    const gateItems = gateFindings({ failures: [{ tool: 'tests', summary: 'dry-run forced failure', file: null, line: null }] })
    const items = String(opts.label).startsWith('decide-fix-gate') ? gateItems : dryFindings().map(finding => ({ ...finding, source: 'review' }))
    return { items: items.map(item => ({ id: findingKey(item), source: item.source, action: 'fix', reason: 'dry-run decision', files: [item.file].filter(Boolean), change: item.fix_hint, check: 'dry-run check' })), cannotDecide: [], notes: 'dry-run spec', diffStat: ' 1 file changed', applied: false, apply: null }
  },
  applier: opts => STUBS.implementer(opts),
  lens: () => ({ verdict: 'approve', score: 5, findings: [], disputes: [] }),
  gate: opts => {
    if (String(opts.label).startsWith('commit-')) {
      return { passed: true, failures: [], commands: [], skipped: ['lint', 'typecheck', 'migrations', 'tests', 'semgrep', 'parity'], commit: { sha: dryRunSha(opts.label), pushed: false, error: '' } }
    }
    const forcedFailure = PARAMS.dryRunFailGate === opts.label
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
    : opts.schema === SMOKE_RUN_SCHEMA
    ? { passed: true, exitCode: 0, timedOut: false, command: 'true', logPath: `${PARAMS.runDir}/smoke.log`, summary: 'smoke command passed' }
    : opts.schema === CHECKPOINT_FILE_SCHEMA
    ? { recommendation: PARAMS.dryRunFindings ? 'smoke' : 'ship', command: PARAMS.dryRunFindings ? 'true' : '', reason: PARAMS.dryRunFindings ? 'One command proves the change.' : 'The passing gate already covers the change.', summary: '- Implemented the planned change\n- Gate verification passed\n- No further pre-ship check is needed', decidedBy: 'pending', implementFilesChanged: ['auth/api/client.py'], context: { files: ['auth/api/client.py'], preexisting: [], commandSucceeded: true, diffPath: `${PARAMS.runDir}/review-dry-run.diff`, diffBytes: 12, diffLines: 1, diffValid: true, planSummary: 'dry-run plan summary', criteria: PARAMS.criteria, checklist: 'dry-run checklist', standards: 'dry-run code standards', testPaths: ['tests/unit'], error: '', contract: 'dry-run public contract', reviewerContract: 'dry-run reviewer contract' } }
    : opts.schema === FORGE_CONFIG_SCHEMA
    ? { roles: {}, stages: { sandbox: false, ff_review: false, qa_login: false }, thresholds: { quickReviewThreshold: 8 }, lenses: DEFAULT_LENSES, ticketUrl: '', repos: { frontend: '', backend: '' }, gate: {} }
    : opts.schema === PHASES_FILE_SCHEMA
    ? { ...EMPTY_PHASES_FILE }
    : opts.schema === BRANCH_SCHEMA
    ? { branch: `${PARAMS.ticket}-dry-run` }
    : opts.schema === THREAD_CHECK_SCHEMA
    ? { threadExists: true }
    : {
      files: ['auth/api/client.py'], preexisting: [], commandSucceeded: true, diffPath: `${PARAMS.runDir}/review-dry-run.diff`, diffBytes: 12, diffLines: 1, diffValid: true, planSummary: 'dry-run plan summary',
      criteria: PARAMS.criteria, checklist: 'dry-run checklist', standards: 'dry-run code standards', testPaths: ['tests/unit'], error: '',
      contract: 'dry-run public contract', reviewerContract: 'dry-run reviewer contract',
    },
  readConfig: () => ({ roles: {}, stages: { sandbox: false, ff_review: false, qa_login: false }, thresholds: { quickReviewThreshold: 8 }, lenses: DEFAULT_LENSES, ticketUrl: '', repos: { frontend: '', backend: '' }, gate: {} }),
  handoff: opts => opts.schema === ACK_SCHEMA ? { written: true } : { handoffPath: `${PARAMS.runDir}/handoff.md` },
  trim: () => ({ written: true }),
  codexWrap: opts => {
    if (opts.schema === CODEX_RESULT) return { codexInvoked: true, threadMode: 'start', threadExists: true, filesChanged: ['auth/api/client.py'], testsWritten: 0, summary: 'dry-run Codex', error: '', handoffs: 0 }
    if (opts.schema === CODEX_REVIEW_SCHEMA) return { codexInvoked: true, threadMode: 'start', threadExists: true, review: { verdict: PARAMS.dryRunFindings ? 'request_changes' : 'approve', score: PARAMS.dryRunFindings ? 2 : 5, findings: dryFindings(), disputes: [] }, error: '', handoffs: 0 }
    if (opts.schema === CODEX_FIX_SCHEMA) return { codexInvoked: true, threadMode: 'start', threadExists: true, fix: { fixed: [], couldNotFix: [], touchedFiles: PARAMS.dryRunFindings ? ['auth/api/client.py'] : [], diff: 'dry-run fix diff', notes: 'dry-run fix', results: dryFindings().map(finding => ({ id: findingKey(finding), reason: 'dry-run fix explanation' })) }, error: '', handoffs: 0 }
    return { written: true }
  },
}

const decisions = []
if (canonicalLane !== requestedLane) decisions.push(`Lane alias ${requestedLane} canonicalized to build`)
const dryRunJournal = []
const __test = {
  plannedSourceFiles,
  planPhases,
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

function journal(label) {
  if (PARAMS.dryRun) dryRunJournal.push({ role: 'event', label, prompt: '' })
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
  const profileRole = tierRole === 'checkpoint' ? 'reviewer' : tierRole
  const fallback = TIERS[PARAMS.tier][profileRole]
  const override = configuredRole(configRoleForTier(tierRole))
  if (!override || (override.provider && override.provider !== 'claude')) return fallback
  return { ...fallback, model: override.model || fallback.model, effort: override.effort || fallback.effort }
}

async function agentT(role, prompt, opts = {}) {
  // The gate-checkout removal runs only on exits that skip the handoff, so it may take the handoff's slot.
  const isHandoff = (role === 'handoff' && opts.label === 'handoff') || opts.label === 'remove-gate-checkout'
  const limit = isHandoff ? PARAMS.spawnCap : PARAMS.spawnCap - 1
  if (spawnCount >= limit) {
    if (!isHandoff && !capBlocked) {
      capBlocked = true
      decisions.push(`Spawn cap ${PARAMS.spawnCap} reached; ordinary workflow calls stopped with the final slot reserved for handoff.`)
    }
    return null
  }
  const forceTier = opts.forceTier === true
  const profile = forceTier ? TIERS[PARAMS.tier][role] : tierProfile(role)
  if (!profile) throw new Error(`unknown tier role: ${role}`)
  spawnCount++
  const { forceTier: _forceTier, ...agentOpts } = opts
  const callOpts = { ...agentOpts, model: profile.model, effort: profile.effort }
  if (PARAMS.dryRun) {
    dryRunJournal.push({ role, label: opts.label || role, prompt })
    return STUBS[role](opts)
  }
  let result = await runtimeAgent(prompt, callOpts)
  if (result === null && profile.model === 'fable' && !forceTier) {
    if (spawnCount >= PARAMS.spawnCap - 2) {
      capBlocked = true
      await decide(`${role} returned null on Fable; the Opus fallback was not started because the spawn cap was reached.`)
      return null
    }
    await decide(`${role} returned null on Fable; retrying once with Opus high.`)
    spawnCount++
    const fallback = TIERS.opus[role === 'checkpoint' ? 'reviewer' : role]
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
async function codexAttempts(prompt, opts) {
  let result = await agentT('codexWrap', prompt, opts)
  if (result) result.error = normalizedCodexError(result.error)
  await recordCodexHandoffs(result, opts.label)
  if (result && result.codexInvoked === true && result.error) {
    const terminalError = /^(?:CODEX_DIFF_INVALID|CODEX_BUDGET_EXCEEDED|CODEX_NO_CREDITS|CODEX_HANDOFF_EXHAUSTED|CODEX_CONTEXT_HANDOFF)\b/.test(result.error)
    if (terminalError) return result
    await decide(`${opts.label} wrapper returned an error (${result.error.slice(0, 200)}); retrying once.`)
    result = await agentT('codexWrap', `${prompt}\nattempt=error-retry`, { ...opts, label: `${opts.label}-error-retry` })
    if (result) result.error = normalizedCodexError(result.error)
    await recordCodexHandoffs(result, opts.label)
    return result
  }
  if (result === null || result.codexInvoked === true) return result
  if (result.threadMode === 'start' && result.threadExists === true) return result
  await decide(`${opts.label} wrapper returned without invoking Codex (${String(result.error || 'no error text').slice(0, 200)}); retrying once.`)
  result = await agentT('codexWrap', `${prompt}\nattempt=retry`, { ...opts, label: `${opts.label}-retry` })
  if (result) result.error = normalizedCodexError(result.error)
  await recordCodexHandoffs(result, opts.label)
  return result
}

// evidence names the stage's --thread-file and --log paths so a start the wrapper reports as
// threadless can be checked against the thread file and the helper's status line.
async function codexAgent(prompt, opts, evidence = null) {
  const result = await codexAttempts(prompt, opts)
  if (!evidence || !result || result.codexInvoked !== true || result.threadMode !== 'start' || result.threadExists === true || normalizedCodexError(result.error)) return result
  const script = [
    'import json, pathlib, sys',
    'thread, log = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])',
    'thread_id = thread.read_text(encoding="utf-8").strip() if thread.is_file() else ""',
    'stem = log.name.split(".")[0]',
    'statuses = [pathlib.Path(str(log) + ".status"), *log.parent.glob(stem + "*-h*.status")]',
    'lines = [path.read_text(encoding="utf-8").strip() for path in statuses if path.is_file()]',
    'print(json.dumps({"threadExists": bool(thread_id) and any(line.startswith("CODEX_OK ") and "thread=" + thread_id in line.split() for line in lines)}))',
  ].join('; ')
  const check = await agentT('changedFiles', `Execute exactly one command and return its stdout JSON unchanged: python3 -c ${shellQuote(script)} ${shellQuote(evidence.threadFile)} ${shellQuote(evidence.log)}`,
    { label: `${opts.label}-thread-check`, phase: opts.phase, schema: THREAD_CHECK_SCHEMA })
  if (check && check.threadExists === true) {
    result.threadExists = true
    await decide(`${opts.label} wrapper reported threadExists=false; ${evidence.threadFile} and a CODEX_OK status line for that thread were found, so the result was kept.`)
  }
  return result
}

async function recordCodexHandoffs(result, label) {
  const count = Math.max(0, Number((result && result.handoffs) || 0))
  const details = (result && Array.isArray(result.handoffDetails)) ? result.handoffDetails : []
  for (let index = 0; index < count; index++) {
    const detail = details[index] || { contextTokens: 0, toolCalls: 0 }
    await decide(`${label} handoff ${index + 1}: context=${detail.contextTokens} calls=${detail.toolCalls}`)
  }
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
  if (capBlocked && !result) return false
  // claudeImplement resolves every PARTIAL through continuations or throws, so one here skipped that path.
  if (result && result.status === 'PARTIAL') {
    throw new Error(`Claude implementation returned PARTIAL outside the continuation path at ${where}`)
  }
  if (!result || result.error) {
    throw new Error(`Claude implementation failed at ${where}: ${(result && result.error) || 'agent returned null'}`)
  }
  return true
}

async function loadForgeConfig() {
  const result = FORGE_CONFIG || await agentT('readConfig', `Read ~/.claude/skills/forge/forge.config.json with a ranged sed read. Return its roles, stages, thresholds, lenses, ticketUrl, repos, ghEnvUnset, and gate. If it is missing or invalid, use the documented defaults. Do not read repository files.`,
    { label: 'read-config', phase: 'Implement', schema: FORGE_CONFIG_SCHEMA })
  const defaults = {
    roles: {}, stages: { sandbox: false, ff_review: false, qa_login: false },
    thresholds: { quickReviewThreshold: 8 }, lenses: DEFAULT_LENSES,
    ticketUrl: '', repos: { frontend: '', backend: '' }, ghEnvUnset: {}, gate: {},
  }
  FORGE_CONFIG = {
    ...defaults, ...(result || {}),
    thresholds: { ...defaults.thresholds, ...((result && result.thresholds) || {}) },
    lenses: { ...defaults.lenses, ...((result && result.lenses) || {}) },
    repos: { ...defaults.repos, ...((result && result.repos) || {}) },
    gate: { ...defaults.gate, ...((result && result.gate) || {}) },
  }
}

function configuredGateEntry() {
  const entries = (FORGE_CONFIG && FORGE_CONFIG.gate) || {}
  const project = String(PARAMS.projectDir).replace(/\/$/, '')
  for (const [path, entry] of Object.entries(entries)) {
    const configured = String(path).replace(/\/$/, '')
    if (project === configured || (configured.startsWith('~/') && project.endsWith(configured.slice(1)))) return entry || {}
  }
  const projectName = project.split('/').pop() || ''
  for (const [path, entry] of Object.entries(entries)) {
    const configuredName = String(path).replace(/\/$/, '').split('/').pop() || ''
    if (configuredName && projectName.startsWith(`${configuredName}-`)) return entry || {}
  }
  return {}
}

function configuredGateMode() {
  const mode = configuredGateEntry().mode || 'full'
  if (!['full', 'none'].includes(mode)) throw new Error(`unsupported gate mode: ${mode}`)
  return mode
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`
}

function baselineContext(reuse = false) {
  return agentT('changedFiles', `Execute exactly one command and return its stdout JSON unchanged: python3 ~/.claude/skills/forge/scripts/run_context.py baseline --run-dir ${shellQuote(PARAMS.runDir)} --repo ${shellQuote(PARAMS.projectDir)}${reuse ? ' --reuse' : ''}`,
    { label: 'baseline', phase: 'Implement', schema: ACK_SCHEMA })
}

function fullTestPromptInstruction() {
  if (configuredGateMode() === 'none') return 'This personal repository has no tests or gates. Do not plan or run tests, lint, typecheck, migrations, Semgrep, or parity commands.'
  return `With ranged reads, read ~/.claude/skills/forge/forge.config.json, resolve the gate entry for ${PARAMS.projectDir}, and name its exact tests command in the Codex prompt under FULL TEST COMMAND. Tell Codex to run that full test command before returning; the gate re-runs it, and Codex's run is the first line of defense. Codex must include the test summary line in summary and never report tests as intentionally skipped.`
}

function claudeTestPromptInstruction() {
  if (configuredGateMode() === 'none') return fullTestPromptInstruction()
  return 'With ranged reads, read ~/.claude/skills/forge/forge.config.json, resolve the gate entry for this repository, and run its exact tests command before returning. The gate re-runs it; include the test summary line in summary and never report tests as intentionally skipped.'
}

function runBeforeReturningInstruction() {
  if (configuredGateMode() === 'none') return 'Do not run tests, lint, typecheck, migrations, Semgrep, or parity commands; the pre-ship checkpoint determines whether further verification is useful.'
  return 'Before returning, run service-free tests relevant to the touched files, ruff check, ruff format --check, makemigrations --check --dry-run in Django repositories, and Semgrep when installed. Fix what they report; the gate remains authoritative.'
}

function phaseScope(phase) {
  if (!phase) return ''
  const partial = phase.resumed
    ? ' An interrupted run may have left partial work for this phase in the working tree; keep it, finish the phase, and list those files in filesChanged.'
    : ''
  return `Implement only Phase ${phase.id}: ${phase.title}. The full plan is context: earlier phases are already committed, and later phases are implemented separately.${partial}`
}

// A PARTIAL result, or a null that did not come from the spawn cap, starts a fresh implementer
// from the progress file; the context guard hook is what makes an implementer hand off.
async function claudeImplement(prompt, opts, progressFile) {
  let result = await agentT('implementer', prompt, opts)
  for (let n = 1; ; n++) {
    const partial = Boolean(result && result.status === 'PARTIAL')
    if (result && !partial) return result
    if (!result && capBlocked) return null
    if (n > MAX_IMPL_CONTINUATIONS) throw new Error(`Claude implementation handoff limit reached at ${opts.label}`)
    const context = partial ? /\b(\d+)k context\b/.exec(String(result.summary || '')) : null
    await decide(`${opts.label} handoff ${n} of ${MAX_IMPL_CONTINUATIONS}: reason=${partial ? 'PARTIAL' : 'null result'} context=${context ? `${context[1]}k` : 'unknown'}`)
    PARAMS.spawnCap += 1
    const continuation = `## Continuation (${n} of ${MAX_IMPL_CONTINUATIONS})

An earlier implementer stopped before finishing this work. Progress file: ${(partial && result.progressFile) || progressFile}
First read the progress file, then run \`git -C ${shellQuote(PARAMS.projectDir)} diff --stat\` and \`git -C ${shellQuote(PARAMS.projectDir)} status --short\` to see the work already in the tree.

Continue from the progress file; do not redo work it marks done; do not re-read files the diff shows as complete. List every file changed by this work, including earlier implementers' files, in filesChanged.`
    result = await agentT('implementer', `${prompt}\n\n${continuation}`, { ...opts, label: `${opts.label}-h${n}` })
  }
}

function implement(phase = null) {
  const implementationRole = pickImplRole(PARAMS.lane, PARAMS.fullySpecified, PARAMS.planText, quickReviewThreshold())
  const suffix = phase ? `-phase-${phase.id}` : ''
  const label = `implement${suffix}`
  const summaryPath = `${PARAMS.runDir}/implementation-summary${suffix}.md`
  const scope = phaseScope(phase)
  if ((configuredRole(implementationRole) || {}).provider === 'claude') {
    const progressFile = `${PARAMS.runDir}/impl-progress-${phase ? phase.id : 'main'}.md`
    return claudeImplement(`Implement this confirmed Forge plan in ${PARAMS.projectDir}. ${scope ? `${scope} ` : ''}Never commit or ship. ${claudeTestPromptInstruction()} ${runBeforeReturningInstruction()} Write the implementation summary to ${summaryPath}. Report live-dependent capabilities under unverified. Keep the progress file ${progressFile} current (sections Done, In progress, Remaining, Notes) and return it as progressFile; return status DONE when the work is complete, or PARTIAL after a context-guard handoff.\n\nPLAN\n${PARAMS.planText}`,
      { label, phase: 'Implement', schema: IMPL_RESULT, agentType: 'claude-implementer' }, progressFile)
  }
  const promptPath = `${PARAMS.runDir}/implement${suffix}-prompt.md`
  const logPath = `${PARAMS.runDir}/codex-implement${suffix}.jsonl`
  const outPath = `${PARAMS.runDir}/codex-implement${suffix}-final.md`
  const scopeInstruction = scope
    ? `Put this scope instruction verbatim directly above the PLAN heading: "${scope}" Implement only that phase and the rows of its approved test table.`
    : 'Implement only the confirmed plan and its approved test table.'
  return codexAgent(`You orchestrate the IMPLEMENT stage. ${codexWrapper}
Read ~/.claude/skills/forge/references/implementer.md and ~/.claude/skills/forge/references/code-standards.md in full. ${fullTestPromptInstruction()} Write ${promptPath} as a self-contained Codex prompt containing the implementer contract, then the code-standards contents verbatim, then the full text of ${PLAN} under a PLAN heading and of ${PARAMS.runDir}/context.md (if present) under a CONTEXT heading, and of ${PARAMS.runDir}/recon.md (if present) under a RECON heading. Do not tell Codex to read those files, AGENTS.md, or CLAUDE.md; Codex loads AGENTS.md itself. ${scopeInstruction} ${runBeforeReturningInstruction()} Do not commit, and write ${summaryPath}. If ${PLAN} declares a Phase 0 evidence harness, build it first and keep it runnable; report every live-dependent capability as implemented-unverified — a worker-run harness against a live target is what marks it verified.
Run test -f ${CODEX_IMPL_THREAD} && MODE=resume || MODE=start, then invoke exactly: bash ${CODEX_SH} "$MODE" --thread-file ${CODEX_IMPL_THREAD} --prompt-file ${promptPath} --state-file ${PARAMS.runDir}/codex-state.md --cd ${PARAMS.projectDir} --sandbox workspace-write --writable ${PARAMS.runDir} ${codexImplFlags()} --log ${logPath} --out ${outPath}. Collect changed and untracked files. Return the structured result.`,
  { label, phase: 'Implement', schema: CODEX_RESULT }, { threadFile: CODEX_IMPL_THREAD, log: logPath })
}

function smokeRun(command) {
  return agentT('changedFiles', `Start exactly this command with the Bash tool using run_in_background=true and timeout=600000: \`python3 ~/.claude/skills/forge/scripts/run_context.py smoke-run --run-dir ${shellQuote(PARAMS.runDir)} --repo ${shellQuote(PARAMS.projectDir)} --command ${shellQuote(command)}\`. Poll the background task with TaskOutput calls using timeout=30000 until it completes. Return its stdout JSON unchanged. The background command has its own 900-second cap and must be allowed to finish; do not rerun it.`,
    { label: 'checkpoint-smoke', phase: 'Checkpoint', schema: SMOKE_RUN_SCHEMA })
}

function localGate(label = 'gate', gatePhase = 'Gate', files = [], only = [], sha = '') {
  const quote = value => `'${String(value).replace(/'/g, `'\\''`)}'`
  const filesArg = files.length ? ` --files ${files.map(quote).join(' ')}` : ''
  const onlyArg = only.length ? ` --only ${only.join(',')}` : ''
  const shaArg = sha ? ` --sha ${quote(sha)}` : ''
  return agentT('gate', `Run exactly: \`bash ~/.claude/skills/forge/scripts/gate.sh --repo ${quote(PARAMS.projectDir)} --run-dir ${quote(PARAMS.runDir)} --label ${label}${shaArg}${onlyArg}${filesArg}\`. Return its stdout JSON as your structured output without changes. If the script exits 2 or prints no JSON, return \`{ passed: false, failures: [{ tool: 'gate.sh', summary: "gate.sh could not run (exit 2: config or usage error): <stderr tail>", file: null, line: null }], commands: [] }\`.`,
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

// hooks.first is a gate result already collected; hooks.run gates a label and file list;
// hooks.afterFix(touched, files) runs after each applied fix and returns false to stop the loop;
// hooks.planExcerpt narrows the plan text the decider and applier see.
async function gateWithFixes(label, files, threadFile, context, phaseLabel, hooks = {}) {
  const runGate = hooks.run || ((gateLabel, gateFiles) => localGate(gateLabel, phaseLabel, gateFiles))
  const gate = 'first' in hooks ? hooks.first : await runGate(label, files)
  if (gate && gate.passed) return { gate, touchedFiles: [], blocked: false, needsJudge: false }
  return fixLoop({
    kind: 'gate', label: `fix-${label}`, gateLabel: label, gate, reviewItems: [], files, threadFile, context, phaseLabel,
    runGate, afterFix: hooks.afterFix, planExcerpt: hooks.planExcerpt, commitsPerRound: Boolean(hooks.afterFix),
  })
}

function stopped(state) {
  return state.needsJudge || state.status === 'BLOCKED' || state.status === 'READY_FOR_HUMAN' || state.status === 'PRE_SHIP'
}

function changedFiles(allDirty = false) {
  const mode = allDirty ? ' --all-dirty' : ''
  const base = PARAMS.lane === 'review' ? ` --base ${shellQuote(args.base || 'main')}` : ''
  return agentT('changedFiles', `Execute exactly one command and return its stdout JSON unchanged: python3 ~/.claude/skills/forge/scripts/run_context.py context --run-dir ${shellQuote(PARAMS.runDir)} --repo ${shellQuote(PARAMS.projectDir)} --plan-file ${shellQuote(PLAN)} --label gate${mode}${base}`,
  { label: 'changed-files', phase: 'Review', schema: CONTEXT_SCHEMA })
}

function checkpointReview(context, gate, implement, phases = null) {
  return agentT('checkpoint', `You are the fresh pre-ship checkpoint reviewer. Read the plan text below and the diff file ${context.diffPath} with the Read tool in ranges of at most 2,000 lines. Also consider the gate result below when present. Recommend ship when the change is prose or configuration, or when the passing gate already covers it. Recommend smoke when one command would prove the change works; command must be that exact command, runnable from ${PARAMS.projectDir}, and complete in under 600 seconds. Recommend qa when only a human or sandbox exercise would prove it. Set command to an empty string unless recommendation is smoke. Keep reason to at most two sentences. Write summary as 3-6 short Markdown bullets covering what changed and what the gate or implementer already verified.

PLAN
${PARAMS.planText}

GATE RESULT
${gate ? JSON.stringify(gate) : '(no gate result; this repository uses gate mode none)'}
${phases ? `\nPHASE COMMITS AND GATES\n${JSON.stringify(phases)}\n` : ''}
IMPLEMENTER RESULT
${JSON.stringify(implement || {})}`,
  { label: 'checkpoint', phase: 'Checkpoint', agentType: 'reviewer', schema: CHECKPOINT_SCHEMA })
}

function checkpointDocument(checkpoint, implement, context, decidedBy, state = {}) {
  return {
    recommendation: checkpoint.recommendation,
    command: checkpoint.recommendation === 'smoke' ? checkpoint.command : '',
    reason: checkpoint.reason,
    summary: checkpoint.summary,
    decidedBy,
    implementFilesChanged: (implement && implement.filesChanged) || [],
    context,
    ...(state.phases ? { branch: state.branch || '', phases: state.phases } : {}),
  }
}

function writeCheckpoint(checkpoint) {
  const script = 'import json, pathlib, sys; pathlib.Path(sys.argv[1]).write_text(json.dumps(json.loads(sys.argv[2]), indent=2) + "\\n", encoding="utf-8"); print(json.dumps({"written": True}))'
  const path = `${PARAMS.runDir}/checkpoint.json`
  return agentT('changedFiles', `Execute exactly one command and return its stdout JSON unchanged: python3 -c ${shellQuote(script)} ${shellQuote(path)} ${shellQuote(JSON.stringify(checkpoint))}`,
  { label: 'write-checkpoint', phase: 'Checkpoint', schema: ACK_SCHEMA })
}

function readCheckpoint() {
  const script = 'import pathlib, sys; print(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"), end="")'
  const path = `${PARAMS.runDir}/checkpoint.json`
  return agentT('changedFiles', `Execute exactly one command and return its stdout JSON unchanged: python3 -c ${shellQuote(script)} ${shellQuote(path)}`,
  { label: 'read-checkpoint', phase: 'Checkpoint', schema: CHECKPOINT_FILE_SCHEMA })
}

async function followCheckpoint(state, decision, command) {
  if (decision === 'ship') return state
  if (decision === 'smoke') {
    if (!command) {
      state.status = 'BLOCKED'
      await decide('Pre-ship checkpoint smoke command was empty; shipping was stopped.')
      return state
    }
    state.checkpointSmoke = await smokeRun(command)
    if (!state.checkpointSmoke || !state.checkpointSmoke.passed) {
      state.status = 'BLOCKED'
      await decide(`Pre-ship smoke failed or timed out; see ${(state.checkpointSmoke && state.checkpointSmoke.logPath) || `${PARAMS.runDir}/smoke.log`}.`)
    }
    return state
  }
  if (sandboxAllowed(configuredStage('sandbox'), PARAMS.repo, FORGE_CONFIG.repos)) return state
  state.status = 'PRE_SHIP'
  await decide('Pre-ship checkpoint recommends a QA round and no sandbox stage is configured; human decision needed before shipping')
  return state
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
Write ${PARAMS.runDir}/codex-review-prompt.md with the exact reviewer prompt below; add nothing (the helper prepends the prompt contract). Run test -f ${CODEX_REVIEW_THREAD} && MODE=resume || MODE=start, then invoke exactly: bash ${CODEX_SH} "$MODE" --thread-file ${CODEX_REVIEW_THREAD} --prompt-file ${PARAMS.runDir}/codex-review-prompt.md --inline-diff ${context.diffPath} --state-file ${PARAMS.runDir}/codex-state-review.md --cd ${PARAMS.projectDir} --sandbox read-only ${CODEX_REVIEW_FLAGS} --log ${PARAMS.runDir}/codex-review.jsonl --out ${PARAMS.runDir}/codex-review-final.md. Return invocation evidence plus Codex's REVIEW_SCHEMA result in the wrapper schema without adding findings.

${review}`,
  { label: 'review-codex', phase: 'Review', schema: CODEX_REVIEW_SCHEMA }, { threadFile: CODEX_REVIEW_THREAD, log: `${PARAMS.runDir}/codex-review.jsonl` })
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
const MAX_FIX_ROUNDS = 2
const MAX_IMPL_CONTINUATIONS = 2

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

// A ruling matches by finding id first, then by file and line. Any decision other than drop
// applies the finding; rescope also replaces its fix text with the ruling's instruction.
function rulingFor(item) {
  const rulings = (PARAMS.rulings || []).filter(ruling => ruling && typeof ruling === 'object')
  const id = findingKey(item)
  return rulings.find(ruling => ruling.id && ruling.id === id) ||
    rulings.find(ruling => !ruling.id && ruling.file === item.file && ruling.line === item.line) || null
}

function ruledItem(item, ruling) {
  const rescoped = ruling.decision === 'rescope' && ruling.instruction
  return { ...item, ruling: rescoped ? 'rescope' : 'apply', ...(rescoped ? { fix_hint: String(ruling.instruction) } : {}) }
}

async function applyRulings(findings, contradictions) {
  const dropped = new Set()
  const applied = new Map()
  const unresolved = []
  const record = (finding, ruling) => {
    if (ruling.decision === 'drop') dropped.add(findingKey(finding))
    else applied.set(findingKey(finding), ruledItem(finding, ruling))
  }
  for (const contradiction of contradictions) {
    const finding = contradiction.finding
    const ruling = rulingFor(finding)
    if (ruling) {
      record(finding, ruling)
    } else if (PARAMS.auto) {
      await decide(`Auto ruling applied ${finding.file}:${finding.line} conservatively: ${finding.claim}`)
    } else {
      unresolved.push(contradiction)
    }
  }
  for (const finding of findings) {
    const ruling = rulingFor(finding)
    if (ruling) record(finding, ruling)
  }
  return {
    unresolved,
    applied: findings.flatMap(finding => applied.has(findingKey(finding)) ? [applied.get(findingKey(finding))] : []),
    confirmed: findings.filter(finding => !dropped.has(findingKey(finding)) && !applied.has(findingKey(finding))),
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

// The applier gets only the decider's fix items, already verified, so it applies them without
// re-triage. The quick-impl role's provider picks the Claude or Codex branch.
async function fixAgent(items, context, label, threadFile, fixPhase, extra) {
  const { round, planExcerpt, diffStat } = extra
  const reviewDiffPath = (context && context.diffPath) || `${PARAMS.runDir}/gate-gate.diff`
  const implementationRole = configRoleForTier('applier')
  const spec = items.map(item => ({ id: findingKey(item), source: item.source || 'review', files: item.specFiles || [item.file].filter(Boolean), change: item.change || item.fix_hint, check: item.check || '', finding: { file: item.file, line: item.line, claim: item.claim } }))
  const inputs = `FIX SPEC\n${JSON.stringify(spec)}\n\nPLAN EXCERPT\n${planExcerpt}\n\nDIFF STAT\n${diffStat || '(not reported)'}`
  if ((configuredRole(implementationRole) || {}).provider === 'claude') {
    const result = await agentT('applier', `Apply only this verified fix spec in ${PARAMS.projectDir} (fix round ${round} of ${MAX_FIX_ROUNDS}). The fix decider already verified every item against current code: apply each change as written. Do not re-triage, re-check whether an item is real, or widen scope. Do not commit or ship. ${runBeforeReturningInstruction()} Return one results[] entry per item with the same id and a concise reason saying what you changed or why you could not apply it, list unapplied ids under couldNotFix, and include the fix diff in diff.\n\n${inputs}`,
      { label, phase: fixPhase, schema: FIX_SCHEMA, agentType: 'claude-implementer' })
    return result || null
  }
  const result = await codexAgent(`You orchestrate FIX ROUND ${round} (${label}). ${codexWrapper}
Read ~/.claude/skills/forge/references/code-standards.md in full. Write ${PARAMS.runDir}/${label}-prompt.md as a self-contained Codex prompt containing those standards verbatim, the fix spec, plan excerpt, and diff stat below verbatim, and the instruction that the fix decider already verified every item against current code, so Codex applies each change as written and does not re-triage or widen scope. With ranged reads, include the review diff at ${reviewDiffPath} when present. Do not refactor adjacent code or commit. ${runBeforeReturningInstruction()} Return one results[] entry per item with the same id and a concise reason explaining what changed or why it could not be applied. A failure caused by an unreachable service (Redis, Postgres, Docker, network, a missing binary) is environmental: list it under couldNotFix with the evidence and never change tests, fixtures, caches, or settings to route around it. Work in ${PARAMS.projectDir}.
Run MODE=start, then invoke exactly: bash ${CODEX_SH} "$MODE" --fresh --thread-file ${threadFile} --prompt-file ${PARAMS.runDir}/${label}-prompt.md --state-file ${PARAMS.runDir}/codex-state-fix-${round}.md --cd ${PARAMS.projectDir} --sandbox workspace-write --writable ${PARAMS.runDir} ${codexFlags(implementationRole, args.codexModelImpl || args.codexModel, args.codexEffortImpl)} --log ${PARAMS.runDir}/codex-${label}.jsonl --out ${PARAMS.runDir}/codex-${label}-final.md. Return invocation evidence plus touched files and git diff limited to 12000 characters in the wrapper schema.

${inputs}`,
  { label, phase: fixPhase, schema: CODEX_FIX_SCHEMA }, { threadFile, log: `${PARAMS.runDir}/codex-${label}.jsonl` })
  if (!assertCodex(result, label)) return null
  return result.fix
}

function verifyFixes(items, fixResult, label = 'verify-review') {
  const explanations = Array.isArray(fixResult.results) ? fixResult.results : []
  const diff = String(fixResult.diff || '').slice(0, 12000)
  return withTimeout(agentT('reviewer', `Verify only the original findings below after a fix round. Return exactly one result for each original id with status RESOLVED or UNRESOLVED and a one-line reason. Do not add findings or assess anything outside this list.

ORIGINAL FINDINGS
${JSON.stringify(items.map(item => ({ id: findingKey(item), finding: item })))}

IMPLEMENTER EXPLANATIONS
${JSON.stringify(explanations)}

FIX DIFF
${diff}`,
  { label, phase: 'Fix', schema: SCOPED_VERIFY_SCHEMA, agentType: 'reviewer', forceTier: true }), REVIEW_TIMEOUT_MS, label)
}

async function unresolvedAfterVerification(items, verify, label = 'verify-review') {
  if (!verify || !Array.isArray(verify.results)) {
    await decide(`${label} returned no usable result; every finding it checked remains unresolved.`)
    return items
  }
  const originals = new Map(items.map(item => [findingKey(item), item]))
  const accepted = new Map()
  for (const result of verify.results) {
    const key = result.id
    if (!originals.has(key) || accepted.has(key)) {
      await decide(`${label} dropped extra item ${String(result.id).slice(0, 200)}: ${String(result.reason || '').slice(0, 200)}`)
      continue
    }
    accepted.set(key, result)
  }
  return items.flatMap(item => {
    const result = accepted.get(findingKey(item))
    if (result && result.status === 'RESOLVED') return []
    return [{ ...item, verificationReason: result ? result.reason : `${label} omitted this original finding` }]
  })
}

async function converge(panel, context) {
  const originalFindings = panel.confirmed || []
  if (!originalFindings.length) {
    await decide('Fix stage skipped because the review panel returned no confirmed findings.')
    return { unresolved: [], unresolvedDisputes: [], fixesApplied: false, rounds: [], touchedFiles: [], blocked: false, needsJudge: false, gatePassed: true, gate: null, gateRan: false }
  }
  const gated = configuredGateMode() === 'full'
  return fixLoop({
    kind: 'review', label: 'fix', gateLabel: 'gate-fix', gate: null,
    reviewItems: originalFindings.map(finding => ({ ...finding, source: 'review' })),
    files: context.files || [], threadFile: `${PARAMS.runDir}/codex-fix.thread`, context, phaseLabel: 'Fix',
    runGate: gated ? (gateLabel, gateFiles) => localGate(gateLabel, 'Fix', gateFiles) : null,
    planExcerpt: PARAMS.planText, commitsPerRound: false,
  })
}

function fixDiffStatCommand() {
  const repo = shellQuote(PARAMS.projectDir)
  return `git -C ${repo} diff --stat "$(git -C ${repo} merge-base HEAD "$(cd ${repo} && bash ~/.claude/skills/ship-pr/scripts/resolve-base-branch.sh 2>/dev/null || echo main)")"`
}

function deciderPrompt(round, open, gate, opts, history) {
  const contract = opts.context && opts.context.contract && opts.context.contract !== PARAMS.planText ? opts.context.contract : '(see the plan excerpt)'
  const diffPath = (opts.context && opts.context.diffPath) || (gate && gate.diffPath) || ''
  const gateExcerpt = gate && !gate.passed
    ? JSON.stringify({ failures: gate.failures || [], commands: gate.commands || [] }).slice(0, 6000)
    : '(no failing gate this round)'
  const rulings = (PARAMS.rulings || []).filter(ruling => ruling && open.some(item => rulingFor(item) === ruling))
  return `You are the Forge fix DECIDER for round ${round} of ${MAX_FIX_ROUNDS} (${opts.label}) in ${PARAMS.projectDir}. Gate items come from a failing gate; review items were confirmed by triage. Turn the open items into an exact fix spec.
First run \`${fixDiffStatCommand()}\` and return its stdout as diffStat. Read the run's change set only for the files the open items touch: ${diffPath ? `ranged reads (at most 2,000 lines) of ${diffPath}, or ` : ''}\`git -C ${shellQuote(PARAMS.projectDir)} diff -- <file>\` for uncommitted edits, and ranged reads of current code.
Return one items[] entry per open item, with the same id and source:
- fix: files lists the files to edit, change states the exact edit (file, location, and what to write), and check states how the result will be confirmed.
- reject: current code proves the claim false; reason carries that evidence.
- defer: the item is real but outside this plan's scope; reason says why.
Put in cannotDecide every id whose evidence cannot support a decision. Rejected, deferred, and cannot-decide review items go to a human for a ruling; a gate item closes only when the gate passes. An item whose ruling is apply or rescope was decided by a human: its action is fix, using its fix_hint.
Small-fix rule: when the whole fix set of this round is at most about 20 changed lines across at most 2 files and adds no new function or control flow, make those edits yourself, set applied=true, and fill apply with fixed, couldNotFix, touchedFiles, the diff of your edits (at most 12000 characters), notes, and one results[] entry per fix item with the same id and what you changed. Otherwise edit nothing, set applied=false, and set apply=null. Never edit code for an item you do not list with action fix.
Respect the public API contract. Do not widen scope, redesign, commit, push, run tests or other checks, or delegate. Put what the next reader should know in notes.

OPEN ITEMS
${JSON.stringify(open.map(item => ({ id: findingKey(item), source: item.source, ruling: item.ruling || null, finding: item })))}

GATE OUTPUT
${gateExcerpt}

EARLIER ROUNDS
${history.length ? JSON.stringify(history) : '(none)'}

RULINGS
${rulings.length ? JSON.stringify(rulings) : '(none)'}

PUBLIC API CONTRACT
${contract}

PLAN EXCERPT
${opts.planExcerpt}`
}

// One capped loop for gate failures and review findings. Each round a decider writes the fix
// spec (applying a small fix set itself), an applier applies the rest, then the re-gate checks
// gate items and a separate verifier re-checks only this round's fixed review items. Gate item
// ids come from failure text and change across edits, so gate progress is a failure count.
async function fixLoop(opts) {
  const { kind, label, runGate } = opts
  const afterFix = opts.afterFix || (async () => true)
  opts.planExcerpt = opts.planExcerpt || PARAMS.planText
  let gate = opts.gate
  let gateOpen = kind === 'gate' ? gateFindings(gate || { failures: [{ tool: 'gate', summary: 'agent returned null', file: null, line: null }] }) : []
  const reviewOpen = new Map(opts.reviewItems.map(item => [findingKey(item), item]))
  const closedIds = new Set()
  const disputes = []
  const history = []
  const deciderNotes = []
  const rounds = []
  const touchedFiles = []
  let files = [...opts.files]
  let gateRan = false
  let reason = null
  PARAMS.spawnCap += MAX_FIX_ROUNDS * (3 + (opts.commitsPerRound ? 1 : 0))
  for (let round = 1; round <= MAX_FIX_ROUNDS; round++) {
    for (const [id, item] of [...reviewOpen]) {
      const ruling = rulingFor(item)
      if (!ruling) continue
      if (ruling.decision === 'drop') {
        reviewOpen.delete(id)
        closedIds.add(id)
        await decide(`${label} round ${round}: ruling dropped ${item.file}:${item.line}.`)
      } else {
        reviewOpen.set(id, ruledItem(item, ruling))
      }
    }
    gateOpen = gateOpen.map(item => {
      const ruling = rulingFor(item)
      return ruling && ruling.decision !== 'drop' ? ruledItem(item, ruling) : item
    })
    if (!reviewOpen.size && !gateOpen.length) break
    const before = { review: reviewOpen.size, gate: gateOpen.length }
    const open = [...gateOpen, ...reviewOpen.values()]
    const spec = await agentT('decider', deciderPrompt(round, open, gate, opts, history),
      { label: `decide-${label}-${round}`, phase: opts.phaseLabel, schema: FIX_SPEC_SCHEMA, agentType: 'judge' })
    if (!spec) {
      reason = capBlocked ? 'spawn-cap' : 'agent-null'
      await decide(`${label} round ${round}: the fix decider returned null; the loop stopped.`)
      break
    }
    if (spec.notes) deciderNotes.push(`Round ${round}: ${spec.notes}`)
    const openById = new Map(open.map(item => [findingKey(item), item]))
    const cannotDecide = new Set((spec.cannotDecide || []).filter(id => openById.has(id)))
    const fixItems = []
    const seen = new Set()
    for (const entry of spec.items || []) {
      const item = openById.get(entry.id)
      if (!item) {
        await decide(`${label} round ${round}: the decider named unknown item ${String(entry.id).slice(0, 200)}; ignored.`)
        continue
      }
      if (cannotDecide.has(entry.id) || seen.has(entry.id)) continue
      seen.add(entry.id)
      if (entry.action === 'fix') {
        fixItems.push({ ...item, specFiles: entry.files || [], change: entry.change || item.fix_hint, check: entry.check || '' })
      } else if (item.ruling) {
        await decide(`${label} round ${round}: the decider chose ${entry.action} for ${item.file}:${item.line}, which a ruling decided; it stays open.`)
      } else if (item.source === 'gate') {
        await decide(`${label} round ${round}: the decider chose ${entry.action} for gate item ${item.claim.slice(0, 200)}; only a passing gate closes it. ${String(entry.reason || '').slice(0, 300)}`)
      } else {
        reviewOpen.delete(entry.id)
        disputes.push({ finding: item, reason: `decider ${entry.action}: ${entry.reason || '(no reason given)'}` })
      }
    }
    for (const id of cannotDecide) {
      const item = openById.get(id)
      disputes.push({ finding: item, reason: 'decider could not decide from current evidence' })
      reviewOpen.delete(id)
    }
    const listed = new Set((spec.items || []).map(entry => entry.id))
    const unlisted = open.filter(item => !listed.has(findingKey(item)) && !cannotDecide.has(findingKey(item)))
    if (unlisted.length) await decide(`${label} round ${round}: the decider left ${unlisted.length} open item(s) unlisted; they stay open.`)
    let fix = null
    let appliedBy = null
    if (spec.applied) {
      appliedBy = 'decider'
      fix = spec.apply || { fixed: [], couldNotFix: [], touchedFiles: [], diff: '', notes: 'decider reported applied=true without an apply result', results: [] }
      if (!spec.apply) await decide(`${label} round ${round}: the decider reported applied=true without an apply result.`)
    } else if (fixItems.length) {
      appliedBy = 'applier'
      const threadFile = round === 1 ? opts.threadFile : `${opts.threadFile}-${round}`
      fix = await fixAgent(fixItems, opts.context, `${label}-${round}`, threadFile, opts.phaseLabel, { round, planExcerpt: opts.planExcerpt, diffStat: spec.diffStat })
      if (!fix) {
        reason = capBlocked ? 'spawn-cap' : 'agent-null'
        await decide(`${label} round ${round}: the fix applier returned null; the loop stopped.`)
        break
      }
    }
    const record = { round, appliedBy, fixIds: fixItems.map(item => findingKey(item)), fix: fix && { ...fix, diff: undefined }, verify: null, gatePassed: null }
    rounds.push(record)
    if (fix) {
      const touched = fix.touchedFiles || []
      touchedFiles.push(...touched)
      files = [...new Set([...files, ...touched])]
      if (!await afterFix(touched, files)) {
        reason = 'commit-failed'
        break
      }
      if (runGate) {
        gate = await runGate(round === 1 ? `${opts.gateLabel}-retry` : `${opts.gateLabel}-retry${round}`, files)
        gateRan = true
        gateOpen = gate && gate.passed ? [] : gateFindings(gate || { failures: [{ tool: 'gate', summary: 'agent returned null', file: null, line: null }] })
        record.gatePassed = Boolean(gate && gate.passed)
      }
      const reviewFixed = fixItems.filter(item => item.source !== 'gate' && reviewOpen.has(findingKey(item)))
      if (reviewFixed.length) {
        const verifyLabel = round === 1 ? 'verify-review' : `verify-review-${round}`
        const verify = await verifyFixes(reviewFixed, fix, verifyLabel)
        record.verify = verify
        const stillOpen = new Set((await unresolvedAfterVerification(reviewFixed, verify, verifyLabel)).map(item => findingKey(item)))
        for (const item of reviewFixed) {
          const id = findingKey(item)
          if (stillOpen.has(id)) continue
          reviewOpen.delete(id)
          closedIds.add(id)
        }
      }
    }
    history.push({
      round, appliedBy,
      spec: (spec.items || []).map(entry => ({ id: entry.id, action: entry.action, change: entry.change, reason: entry.reason })),
      cannotDecide: [...cannotDecide],
      gatePassed: record.gatePassed,
      stillOpen: [...reviewOpen.keys()],
      gateFailures: gateOpen.map(item => item.claim.slice(0, 300)),
    })
    if (!reviewOpen.size && !gateOpen.length) break
    const reopened = [...reviewOpen.keys()].some(id => closedIds.has(id))
    if (reopened || (reviewOpen.size >= before.review && gateOpen.length >= before.gate)) {
      reason = 'no-progress'
      break
    }
    if (round === MAX_FIX_ROUNDS) reason = 'fix-cap'
  }
  const open = [...gateOpen, ...reviewOpen.values()]
  if (open.length && !reason) reason = capBlocked ? 'spawn-cap' : 'fix-cap'
  const blocked = open.length > 0 || reason === 'commit-failed'
  // A gate item the decider could not decide needs a ruling only while the gate still fails.
  const openDisputes = gateOpen.length ? disputes : disputes.filter(item => item.finding.source !== 'gate')
  const needsJudge = openDisputes.length > 0
  if (blocked) await decide(`${label} stopped BLOCKED (${reason}) after ${rounds.length} round(s) with ${open.length} open item(s).`)
  if (needsJudge) await decide(`${label}: ${openDisputes.length} item(s) need a human ruling: ${openDisputes.map(item => `${item.finding.file}:${item.finding.line}`).join(', ').slice(0, 500)}`)
  const touched = [...new Set(touchedFiles)]
  const blockedFields = blocked ? { reason, open, deciderNotes } : { deciderNotes }
  if (kind === 'gate') return { gate, touchedFiles: touched, blocked, needsJudge, disputes: openDisputes, rounds, ...blockedFields }
  return {
    unresolved: open, unresolvedDisputes: openDisputes, fixesApplied: touched.length > 0, rounds,
    touchedFiles: touched, blocked, needsJudge,
    gatePassed: gateRan ? Boolean(gate && gate.passed) : true, gate, gateRan, ...blockedFields,
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

function ship(existing = null, files = [], context = {}, committedBranch = '') {
  const gateNotice = configuredGateMode() === 'none'
    ? 'The PR body must include the exact line `gates: none (personal repo)`.'
    : ''
  const prompt = existing
    ? `${ghEnvironmentInstruction()}You sync verified Forge fixes to the existing pull request. Follow ~/.claude/skills/ship-pr/SKILL.md and ~/.claude/skills/ship-pr/references/lessons.md. In ${PARAMS.projectDir}, stay on branch ${existing.branch}, commit current verified fixes, push them, and return the same non-draft PR metadata: ${JSON.stringify(existing)}. Update the PR body after the push. The body contains a summary, change list, and links; omit a testing-results section. ${gateNotice} Include only these configured ticket links: ${JSON.stringify(ticketLinks())}. ${stagingRules(files, context)}`
    : committedBranch
    ? `${ghEnvironmentInstruction()}You run the SHIP stage. Follow ~/.claude/skills/ship-pr/SKILL.md and ~/.claude/skills/ship-pr/references/lessons.md. In ${PARAMS.projectDir}, resolve the repository base branch and stay on branch ${committedBranch}, which already holds this run's phase commits; never create or switch branches. Commit only run files that are still uncommitted, if any, and skip the commit when nothing is left to stage. Push the branch, open a NON-draft PR, and return {branch, prUrl, prNumber, repo}. The PR body contains a summary, change list, and links; omit a testing-results section. ${gateNotice} Include only these configured ticket links: ${JSON.stringify(ticketLinks())}. ${stagingRules(files, context)}`
    : `${ghEnvironmentInstruction()}You run the SHIP stage. Follow ~/.claude/skills/ship-pr/SKILL.md and ~/.claude/skills/ship-pr/references/lessons.md. In ${PARAMS.projectDir}, resolve the repository base branch, create a descriptive branch, commit the implementation, push it, open a NON-draft PR, and return {branch, prUrl, prNumber, repo}. The PR body contains a summary, change list, and links; omit a testing-results section. ${gateNotice} Include only these configured ticket links: ${JSON.stringify(ticketLinks())}. ${stagingRules(files, context)}`
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
  const noGates = configuredGateMode() === 'none'
  const gateNotice = noGates
    ? `State exactly \`gates: none (personal repo)\`. Cite the checkpoint result at ${PARAMS.runDir}/checkpoint.json.`
    : ''
  const cleanup = usesGateCheckout()
    ? `Before anything else, run exactly this command once and continue regardless of its output: \`${gateCheckoutCleanupCommand()}\`. `
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
  if (state.status === 'PRE_SHIP') {
    return agentT('handoff', `${cleanup}Write a short pre-ship handoff at ${PARAMS.runDir}/handoff.md stating that the checkpoint completed and shipping is paused for a human decision. Include the checkpoint recommendation, command, reason, and summary from this data: ${JSON.stringify(state.checkpoint)}. ${gateNotice}
APPEND to ${PARAMS.runDir}/decisions.md (create it if missing; never truncate or rewrite existing content) a section headed \`## Workflow <current UTC timestamp in ISO 8601, which you generate because the script cannot>\` followed by one line per entry of this decisions array: ${JSON.stringify(decisions)}.
Then rewrite ${PARAMS.runDir}/STATE.md whole (never append) from ~/.claude/references/state-template.md with status PRE_SHIP, the checkpoint decision as the next step, and pointers to the plan, decisions, STATUS.json, checkpoint.json, and handoff.md. Return the handoff path.`,
    { label: 'handoff', phase: 'Handoff', schema: HANDOFF_SCHEMA })
  }
  return agentT('handoff', `${cleanup}You write the Forge HANDOFF at ${PARAMS.runDir}/handoff.md. First APPEND to ${PARAMS.runDir}/decisions.md (create it if missing; never truncate or rewrite existing content) a section headed \`## Workflow <current UTC timestamp in ISO 8601, which you generate because the script cannot>\` followed by one line per entry of this decisions array: ${JSON.stringify(decisions)}. Use only the run data below, ${PARAMS.runDir}/STATUS.json, and ${PARAMS.runDir}/decisions.md. Do not read the diff or repository files; file names come from the run data.
${gateNotice}
Write these sections exactly: What changed and why; Gate results; Sandbox + smoke results (include login URL, preview URL, sandbox id, and any post-fix re-run, with no expiry caveats); Review scores and findings; Manual QA checklist (one item per acceptance criterion); Judgment calls; Status. Status must be ${state.status}. Judgment calls must include every entry from ${JSON.stringify(decisions)}.
Read ${PARAMS.runDir}/STATUS.json and render the Manual QA checklist from its criteria (status + evidence per item) when it exists.
Acceptance criteria: ${JSON.stringify(acceptanceCriteria(context))}
Run data: ${JSON.stringify(handoffState)}
Then rewrite ${PARAMS.runDir}/STATE.md whole (never append) from ~/.claude/references/state-template.md with the run's current state, next steps, blockers, pointers (plan, decisions, STATUS.json, PR, branch, sandbox), and do-not-redo facts.
Return the handoff path.`,
  { label: 'handoff', phase: 'Handoff', schema: HANDOFF_SCHEMA })
}

function usesGateCheckout() {
  return PHASED && configuredGateMode() !== 'none'
}

function gateCheckoutCleanupCommand() {
  const dir = shellQuote(GATE_CHECKOUT)
  const repo = shellQuote(PARAMS.projectDir)
  return `if [ -e ${dir} ]; then git -C ${repo} worktree remove --force ${dir} || { find ${dir} -mindepth 1 -delete; rmdir ${dir}; }; fi; git -C ${repo} worktree prune`
}

function removeGateCheckout() {
  return agentT('changedFiles', `Execute exactly one command and return {"written": true} when it finishes: ${gateCheckoutCleanupCommand()}`,
    { label: 'remove-gate-checkout', phase: 'Handoff', schema: ACK_SCHEMA })
}

function readPhases() {
  const empty = JSON.stringify(EMPTY_PHASES_FILE).replace(/null/g, 'None')
  const script = `import json, pathlib, sys; path = pathlib.Path(sys.argv[1]); print(path.read_text(encoding="utf-8") if path.is_file() else json.dumps(${empty}), end="")`
  return agentT('changedFiles', `Execute exactly one command and return its stdout JSON unchanged: python3 -c ${shellQuote(script)} ${shellQuote(`${PARAMS.runDir}/phases.json`)}`,
    { label: 'read-phases', phase: 'Implement', schema: PHASES_FILE_SCHEMA })
}

function writePhases(run, extraPending = []) {
  const document = {
    branch: run.branch,
    phases: run.rows,
    lastCommittedPhase: run.lastCommittedPhase,
    headSha: run.headSha,
    pendingGates: [...extraPending, ...run.unresolved, ...run.pending.map(entry => ({ id: entry.id, sha: entry.sha, label: entry.label }))],
  }
  const script = 'import json, pathlib, sys; pathlib.Path(sys.argv[1]).write_text(json.dumps(json.loads(sys.argv[2]), indent=2) + "\\n", encoding="utf-8"); print(json.dumps({"written": True}))'
  return agentT('changedFiles', `Execute exactly one command and return its stdout JSON unchanged: python3 -c ${shellQuote(script)} ${shellQuote(`${PARAMS.runDir}/phases.json`)} ${shellQuote(JSON.stringify(document))}`,
    { label: 'write-phases', phase: 'Implement', schema: ACK_SCHEMA })
}

function planBranchName() {
  const heading = (/^#\s+(.+)$/m.exec(PARAMS.planText) || [])[1] || PHASES[0].title
  const slug = value => String(value).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  const words = slug(heading.replace(/^plan:\s*/i, '')).split('-').filter(Boolean).slice(0, 6).join('-')
  return [slug(PARAMS.ticket), words].filter(Boolean).join('-').slice(0, 60).replace(/-+$/, '') || 'forge-phases'
}

// ship-pr's rule: create a branch only when the checkout is on the base branch (or detached).
function phaseBranch(name) {
  const repo = shellQuote(PARAMS.projectDir)
  const branch = shellQuote(name)
  const report = `python3 -c 'import json, subprocess; print(json.dumps({"branch": subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, check=True).stdout.strip()}))'`
  return agentT('changedFiles', `Execute exactly one command and return its stdout JSON unchanged: cd ${repo} && current=$(git branch --show-current) && base=$(bash ~/.claude/skills/ship-pr/scripts/resolve-base-branch.sh 2>/dev/null || true) && case "$current" in ''|develop|main|master|"$base") git switch -c ${branch} >/dev/null 2>&1 || git switch -c ${branch}-$(date +%s) >/dev/null ;; esac && ${report}`,
    { label: 'phase-branch', phase: 'Implement', schema: BRANCH_SCHEMA })
}

// gate.sh drops absolute paths, so implementer-reported paths are made repository-relative first.
function repoRelative(files) {
  const prefix = `${String(PARAMS.projectDir).replace(/\/+$/, '')}/`
  return files.map(file => String(file).startsWith(prefix) ? String(file).slice(prefix.length) : String(file))
}

async function commitFiles(label, message, files) {
  if (!files.length) return { sha: null, empty: true, error: '' }
  const quote = shellQuote
  const subject = String(message).replace(/`/g, '')
  const result = await agentT('gate', `Run exactly: \`bash ~/.claude/skills/forge/scripts/gate.sh --repo ${quote(PARAMS.projectDir)} --run-dir ${quote(PARAMS.runDir)} --label ${label} --no-stages --commit ${quote(subject)} --files ${files.map(quote).join(' ')}\`. Return its stdout JSON as your structured output without changes, including when the script exits 2 after printing JSON. If it prints no JSON, return \`{ passed: false, failures: [{ tool: 'gate.sh', summary: "gate.sh could not run: <stderr tail>", file: null, line: null }], commands: [], commit: null }\`.`,
    { label, phase: 'Implement', schema: GATE_SCHEMA })
  const commit = result && result.commit
  if (commit && commit.sha) return { sha: commit.sha, empty: false, error: '' }
  const error = (commit && commit.error) || (result && (result.failures || [])[0] && result.failures[0].summary) || 'commit agent returned null'
  if (/^no (?:staged changes to commit|committable --files paths remain)/.test(error)) return { sha: null, empty: true, error: '' }
  return { sha: null, empty: false, error }
}

// Gates share one checkout and label-keyed state files, so they run strictly one at a time.
// A gate with nothing ahead of it starts at once instead of on a later microtask.
let gateTail = Promise.resolve()
let gatesInFlight = 0
function serialGate(start) {
  gatesInFlight++
  const started = gatesInFlight === 1 ? start() : gateTail.then(start)
  const done = () => { gatesInFlight-- }
  gateTail = started.then(done, done)
  return started
}

function queuePhaseGate(run, entry) {
  entry.settled = false
  entry.promise = serialGate(() => localGate(entry.label, 'Gate', entry.files, [], entry.sha)).catch(() => null)
  entry.promise.then(() => { entry.settled = true })
  run.pending.push(entry)
}

async function collectPhaseGate(run, entry, allowFix) {
  const gate = await entry.promise
  run.pending = run.pending.filter(item => item !== entry)
  journal(`gate-collected-phase-${entry.id}`)
  const row = run.rows.find(item => item.id === entry.id)
  run.lastGate = gate
  if (gate && gate.passed) {
    row.gate = 'passed'
    await decide(`Phase ${entry.id} gate passed on ${entry.sha.slice(0, 12)}.`)
    return
  }
  row.gate = 'failed'
  if (!allowFix) {
    run.unresolved.push({ id: entry.id, sha: entry.sha, label: entry.label })
    return
  }
  let sha = entry.sha
  let fixes = 0
  const planned = PHASES.find(item => item.id === entry.id)
  const gateRun = await gateWithFixes(entry.label, entry.files, `${PARAMS.runDir}/codex-fix-${entry.label}.thread`, { standards: '', contract: PARAMS.planText }, 'Gate', {
    first: gate,
    planExcerpt: planned ? `### Phase ${planned.id}: ${planned.title}\n${planned.text}` : PARAMS.planText,
    run: (label, files) => serialGate(() => localGate(label, 'Gate', files, [], sha)),
    afterFix: async (touched, files) => {
      fixes++
      run.files = [...new Set([...run.files, ...repoRelative(touched)])]
      const commit = await commitFiles(`commit-fix-phase-${entry.id}-${fixes}`, `Fix Phase ${entry.id} gate`, [...new Set(repoRelative(files))])
      if (commit.error) {
        await decide(`Fix Phase ${entry.id} gate could not be committed: ${commit.error.slice(0, 300)}`)
        return false
      }
      if (commit.sha) {
        sha = commit.sha
        run.headSha = commit.sha
        await decide(`Fix Phase ${entry.id} gate committed as ${sha.slice(0, 12)}.`)
        await writePhases(run, [{ id: entry.id, sha, label: entry.label }])
      }
      return true
    },
  })
  run.lastGate = gateRun.gate
  row.gate = gateRun.blocked ? 'failed' : 'passed'
  if (gateRun.disputes && gateRun.disputes.length) run.disputes.push(...gateRun.disputes)
  if (gateRun.needsJudge) run.needsJudge = true
  if (gateRun.blocked) {
    run.blocked = true
    run.unresolved.push({ id: entry.id, sha, label: entry.label })
    run.gateFix = { phase: entry.id, reason: gateRun.reason, open: gateRun.open, rounds: gateRun.rounds.length, deciderNotes: gateRun.deciderNotes }
    await decide(`Phase ${entry.id} gate did not pass after the fix loop (${gateRun.reason}); later phases were stopped.`)
  }
}

async function collectSettledGates(run) {
  while (run.pending.length && run.pending[0].settled && !run.blocked) await collectPhaseGate(run, run.pending[0], true)
}

// Each phase is implemented and committed in the primary worktree; its gate runs on the
// committed SHA in the gate checkout while the next phase is implemented. Gate failures are
// fixed only at phase boundaries, never while an implementer is editing. The final gate runs on
// HEAD over every run file only after all earlier gates and their fix commits have settled.
async function phasedImplement(state) {
  const gated = configuredGateMode() !== 'none'
  const saved = PHASES_SAVED
  const lastPhase = PHASES[PHASES.length - 1]
  const finalLabel = `gate-phase-${lastPhase.id}`
  const run = {
    branch: saved.branch || '', rows: PHASES.map(item => ({ id: item.id, title: item.title, sha: null, gate: null })),
    lastCommittedPhase: null, pending: [], unresolved: [], files: [], headSha: null, blocked: false, needsJudge: false, lastGate: null, results: [], disputes: [], gateFix: null,
  }
  for (const row of saved.phases || []) {
    const target = run.rows.find(item => item.id === row.id)
    if (target) Object.assign(target, { sha: row.sha, gate: row.gate })
  }
  let startIndex = 0
  let resumeFiles = []
  if (PHASES_RECORDED) {
    if (saved.lastCommittedPhase) {
      const index = PHASES.findIndex(item => item.id === saved.lastCommittedPhase)
      if (index < 0) throw new Error(`${PARAMS.runDir}/phases.json records committed phase ${saved.lastCommittedPhase}, which the plan does not contain`)
      startIndex = index + 1
      run.lastCommittedPhase = saved.lastCommittedPhase
      run.headSha = saved.headSha || [...run.rows.slice(0, index + 1)].reverse().map(row => row.sha).find(Boolean) || null
    }
    const context = await changedFiles()
    if (contextFailed(context)) {
      state.status = 'BLOCKED'
      await decide(`Changed-file collection failed while resuming the phase loop: ${(context && context.error) || 'agent returned null'}`)
      return state
    }
    resumeFiles = context.files || []
    run.files = [...resumeFiles]
    // The final gate always runs after the loop, so a saved final gate is not queued twice.
    const requeue = gated && resumeFiles.length ? saved.pendingGates.filter(pending => pending.label !== finalLabel) : []
    for (const pending of requeue) queuePhaseGate(run, { id: pending.id, sha: pending.sha, label: pending.label, files: resumeFiles })
    await decide(saved.lastCommittedPhase
      ? `Resuming the phase loop after Phase ${saved.lastCommittedPhase}; ${requeue.length} pending or failed gate(s) re-queued.`
      : `Resuming the phase loop at Phase ${PHASES[0].id}; no phase was committed before the interruption.`)
  }
  if (!run.branch) {
    const branch = await phaseBranch(planBranchName())
    if (!branch || !branch.branch) {
      state.status = 'BLOCKED'
      await decide('Could not switch to a branch for the phase commits; the phase loop did not start.')
      return state
    }
    run.branch = branch.branch
    await decide(`Phase commits go on branch ${run.branch}.`)
  }
  // Written before Phase 1 so an interrupted first phase resumes with this run's baseline.
  if (!PHASES_RECORDED) await writePhases(run)
  for (let index = startIndex; index < PHASES.length && !run.blocked; index++) {
    const phase = PHASES[index]
    const row = run.rows[index]
    const resumed = index === startIndex && PHASES_RECORDED
    const result = await implement({ ...phase, resumed })
    if (capBlocked || !assertImplementation(result, `implement-phase-${phase.id}`)) {
      run.blocked = true
      break
    }
    run.results.push({ id: phase.id, result })
    const phaseFiles = [...new Set(repoRelative([...(result.filesChanged || []), ...(resumed ? resumeFiles : [])]))]
    run.files = [...new Set([...run.files, ...phaseFiles])]
    const commit = await commitFiles(`commit-phase-${phase.id}`, `Phase ${phase.id}: ${phase.title}`, phaseFiles)
    if (commit.error) {
      run.blocked = true
      await decide(`Phase ${phase.id} could not be committed: ${commit.error.slice(0, 300)}`)
      break
    }
    row.sha = commit.sha
    row.gate = !gated ? 'none' : commit.sha ? 'pending' : 'skipped'
    run.lastCommittedPhase = phase.id
    if (commit.sha) run.headSha = commit.sha
    await decide(commit.sha ? `Phase ${phase.id} committed as ${commit.sha.slice(0, 12)}.` : `Phase ${phase.id} left nothing committable; no commit was made.`)
    if (gated) {
      await collectSettledGates(run)
      if (run.blocked) break
      if (commit.sha && phase !== lastPhase) queuePhaseGate(run, { id: phase.id, sha: commit.sha, label: `gate-phase-${phase.id}`, files: phaseFiles })
    }
    await writePhases(run)
  }
  while (run.pending.length) await collectPhaseGate(run, run.pending[0], !run.blocked)
  if (gated && !run.blocked && !capBlocked && run.headSha && run.files.length) {
    run.rows[run.rows.length - 1].gate = 'pending'
    queuePhaseGate(run, { id: lastPhase.id, sha: run.headSha, label: finalLabel, files: run.files })
    await collectPhaseGate(run, run.pending[0], true)
  }
  await writePhases(run)
  state.branch = run.branch
  state.phases = run.rows
  state.gate = run.lastGate
  state.implement = {
    filesChanged: run.files,
    testsWritten: run.results.some(item => item.result.testsWritten === true || item.result.testsWritten > 0),
    summary: run.results.map(item => `Phase ${item.id}: ${item.result.summary || ''}`).join('\n'),
    unverified: run.results.flatMap(item => item.result.unverified || []),
    error: null,
  }
  if (run.needsJudge) state.needsJudge = true
  if (run.disputes.length) state.fixDisputes = run.disputes
  if (run.gateFix) state.gateFix = run.gateFix
  if (run.blocked || capBlocked) state.status = 'BLOCKED'
  return state
}

async function fullLane() {
  phase('Implement')
  const implementationRole = pickImplRole(PARAMS.lane, PARAMS.fullySpecified, PARAMS.planText, quickReviewThreshold())
  if (!PARAMS.checkpointDecision) await decide(`Implementation role selected: ${implementationRole} (${plannedSourceFiles(PARAMS.planText)} planned source files; threshold ${quickReviewThreshold()}).`)
  if (PHASED && !PARAMS.checkpointDecision) {
    await decide(configuredGateMode() === 'none'
      ? `Plan has ${PHASES.length} phases (${PHASES.map(item => item.id).join(', ')}); each is committed on its own, and gate mode none runs no gates.`
      : `Plan has ${PHASES.length} phases (${PHASES.map(item => item.id).join(', ')}); each is committed, then gated on its SHA in ${GATE_CHECKOUT} while the next phase runs.`)
  }
  const initial = { status: 'DONE', implement: null, checkpoint: null, checkpointSmoke: null, gate: null, ship: null, qaDraft: null, sandbox: null, smoke: null, review: null, convergence: null, sandboxRefresh: null }
  if (PARAMS.checkpointDecision) {
    const saved = await readCheckpoint()
    if (!saved || !saved.context || !Array.isArray(saved.implementFilesChanged)) {
      throw new Error(`checkpointDecision requires a readable ${PARAMS.runDir}/checkpoint.json with saved context`)
    }
    initial.implement = { filesChanged: saved.implementFilesChanged }
    initial.context = saved.context
    if (saved.phases) {
      initial.branch = saved.branch || ''
      initial.phases = saved.phases
    }
    initial.checkpoint = { ...saved, decidedBy: 'user' }
    await decide(`Pre-ship checkpoint decision: ${PARAMS.checkpointDecision} (user)`)
    if (!await writeCheckpoint(initial.checkpoint)) throw new Error(`could not update ${PARAMS.runDir}/checkpoint.json for the user decision`)
  }
  const rows = await pipeline(
    [initial],
    async state => {
      phase('Implement')
      if (PARAMS.checkpointDecision) return state
      if (PHASED) return phasedImplement(state)
      state.implement = await implement()
      if (!assertImplementation(state.implement, 'implement')) state.status = 'BLOCKED'
      if (capBlocked && state.status !== 'READY_FOR_HUMAN') state.status = 'BLOCKED'
      return state
    },
    async state => {
      phase('Gate')
      if (stopped(state)) return state
      if (PARAMS.checkpointDecision || PHASED || configuredGateMode() === 'none') return state
      const gateRun = await gateWithFixes('gate', (state.implement && state.implement.filesChanged) || [], `${PARAMS.runDir}/codex-fix-gate.thread`, { standards: '', contract: PARAMS.planText }, 'Gate')
      state.gate = gateRun.gate
      if (state.implement) state.implement.filesChanged = [...new Set([...(state.implement.filesChanged || []), ...(gateRun.touchedFiles || [])])]
      if (gateRun.needsJudge) state.needsJudge = true
      if (gateRun.disputes && gateRun.disputes.length) state.fixDisputes = gateRun.disputes
      if (!state.gate || !state.gate.passed) {
        state.status = 'BLOCKED'
        if (gateRun.reason) state.gateFix = { reason: gateRun.reason, open: gateRun.open, rounds: gateRun.rounds.length, deciderNotes: gateRun.deciderNotes }
        await decide('Pre-ship local gate did not pass; later stages were stopped.')
      }
      return state
    },
    async state => {
      phase('Checkpoint')
      if (stopped(state) || PARAMS.noShip) return state
      if (PARAMS.checkpointDecision) {
        const command = PARAMS.checkpointDecision === 'smoke'
          ? (PARAMS.smokeCommand || state.checkpoint.command)
          : ''
        return followCheckpoint(state, PARAMS.checkpointDecision, command)
      }
      state.context = await changedFiles()
      if (contextFailed(state.context)) {
        state.status = 'BLOCKED'
        await decide(`Changed-file collection failed before checkpoint: ${(state.context && state.context.error) || 'agent returned null'}`)
        return state
      }
      const result = await checkpointReview(state.context, state.gate, state.implement, state.phases || null)
      if (!result) {
        state.status = 'BLOCKED'
        await decide('Pre-ship checkpoint agent returned null; shipping was stopped.')
        return state
      }
      state.checkpoint = checkpointDocument(result, state.implement, state.context, PARAMS.auto ? 'auto' : 'pending', state)
      if (!await writeCheckpoint(state.checkpoint)) {
        state.status = 'BLOCKED'
        await decide('Pre-ship checkpoint result could not be written; shipping was stopped.')
        return state
      }
      await decide(`Pre-ship checkpoint: recommends ${state.checkpoint.recommendation} - ${state.checkpoint.reason}`)
      if (!PARAMS.auto) {
        state.status = 'PRE_SHIP'
        return state
      }
      return followCheckpoint(state, state.checkpoint.recommendation, state.checkpoint.command)
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
      const phasesCommitted = (state.phases || []).some(row => row.sha)
      state.ship = await ship(null, (state.implement && state.implement.filesChanged) || [], state.context, phasesCommitted ? state.branch : '')
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
      if (state.convergence.blocked || (state.convergence.needsJudge && state.convergence.fixesApplied)) {
        const branch = (state.ship && state.ship.branch) || '(unknown branch)'
        await decide(state.convergence.blocked
          ? `Fixes stayed unpushed on ${branch} because ${state.convergence.unresolved.length} item(s) stayed open after the fix loop (${state.convergence.reason}).`
          : `Fixes stayed unpushed on ${branch} until ${state.convergence.unresolvedDisputes.length} disputed item(s) get a human ruling.`)
      }
      if (!state.convergence.blocked && !state.convergence.needsJudge && state.convergence.fixesApplied && state.ship) {
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
const PHASES_SAVED = (PHASED && !PARAMS.checkpointDecision && await readPhases()) || EMPTY_PHASES_FILE
// writePhases always records every phase row, so rows mean this run already started the phase loop.
const PHASES_RECORDED = (PHASES_SAVED.phases || []).length > 0
await baselineContext(Boolean(PARAMS.checkpointDecision || PHASES_RECORDED))
let state
try {
  state = PARAMS.lane === 'review' ? await reviewLane() : await fullLane()
} catch (error) {
  if (usesGateCheckout()) await removeGateCheckout()
  throw error
}
if (state.needsJudge) {
  if (usesGateCheckout()) await removeGateCheckout()
  const disputes = [
    ...((state.review && state.review.unresolvedDisputes) || []),
    ...((state.convergence && state.convergence.unresolvedDisputes) || []),
    ...(state.fixDisputes || []),
  ]
  return { status: 'needsJudge', findings: (state.review && state.review.findings) || [], disputes, runDir: PARAMS.runDir }
}
if (capBlocked && !['READY_FOR_HUMAN', 'PRE_SHIP'].includes(state.status)) state.status = 'BLOCKED'
phase('Handoff')
const ho = await handoff(state, state.context || { criteria: PARAMS.criteria })
if (!ho) {
  if (!['READY_FOR_HUMAN', 'PRE_SHIP'].includes(state.status)) state.status = 'BLOCKED'
  await decide('Handoff agent returned null; no handoff path was produced.')
}
if (capBlocked && !['READY_FOR_HUMAN', 'PRE_SHIP'].includes(state.status)) state.status = 'BLOCKED'
return {
  status: state.status,
  runDir: PARAMS.runDir,
  handoffPath: (ho && ho.handoffPath) || '',
  prUrl: (state.ship && state.ship.prUrl) || '',
  qaDraft: qaDraftSummary(state.qaDraft),
  sandboxId: (state.sandbox && state.sandbox.sandboxId) || '',
  recommendation: (state.checkpoint && state.checkpoint.recommendation) || '',
  command: (state.checkpoint && state.checkpoint.command) || '',
  reason: (state.checkpoint && state.checkpoint.reason) || '',
  summary: (state.checkpoint && state.checkpoint.summary) || '',
  checkpointPath: state.checkpoint ? `${PARAMS.runDir}/checkpoint.json` : '',
  phases: PHASED ? (state.phases || []) : undefined,
  decisions,
  dryRunJournal: PARAMS.dryRun ? dryRunJournal.map(entry => entry.label) : undefined,
}
