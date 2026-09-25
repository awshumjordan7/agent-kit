#!/usr/bin/env python3
"""Render a forge artifact page from a template in ../references/ and a data file.

Usage:
  render_artifact.py plan --data plan-data.json --markdown plan.md --out plan-artifact.html
  render_artifact.py qa --data qa-data.json --out qa-artifact.html
  render_artifact.py generic --data data.json --markdown notes.md --out page.html

Exit codes: 0 rendered, 1 the template has a slot this renderer did not fill, 2 bad input.
Each template's leading comment is its data contract; it is removed before slots are filled.
Warnings (unknown keys, a missing summary) go to stderr and do not change the exit code.
Relative file paths inside a data file resolve against the data file's directory.
"""

import argparse
import base64
import html
import json
import re
import sys
from pathlib import Path

REFERENCES = Path(__file__).resolve().parent.parent / "references"
SLOT_RE = re.compile(r"\{\{([A-Z_]+)\}\}")
SECTION_RE = re.compile(r'<section id="([^"]+)" data-toc="([^"]*)"')
TOC_SOURCE_RE = re.compile(r'<section id="([^"]+)" data-toc="([^"]*)"|\{\{([A-Z_]*SECTIONS?)\}\}')
# Ids the templates use for their fixed sections; markdown sections never reuse them.
FIXED_IDS = {
    "tests", "access-rules", "plan-review", "pending", "links", "access", "users", "jira",
    "context", "qa-items", "handoff",
}
KNOWN_KEYS = {
    "plan": {
        "ticket", "title", "lane", "repo", "date", "runDir", "sandboxTier", "lenses", "status",
        "accessRules", "planReview", "pending", "links", "next", "decision",
    },
    "qa": {
        "summary", "ticket", "shortTitle", "date", "tier", "branch", "sandboxId", "previewUrl",
        "rootLoginEmail", "rootLoginPassword", "adminCreds", "users", "jiraTickets", "links",
        "contextItems", "qaItems", "handoff", "groups", "explore", "round",
    },
    "generic": {"summary", "title", "eyebrow", "status", "statusTone", "keyNumbers", "nextSteps", "links"},
}
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
HANDOFF_KEYS = [
    ("WHAT_CHANGED_HTML", "whatChanged"),
    ("GATE_RESULTS_HTML", "gateResults"),
    ("REVIEW_SCORES_HTML", "reviewScores"),
    ("OPEN_FINDINGS_HTML", "openFindings"),
    ("BOT_VERDICTS_HTML", "botVerdicts"),
    ("JUDGMENT_CALLS_HTML", "judgmentCalls"),
    ("FOLLOWUPS_HTML", "followUps"),
    ("PR_LINKS_HTML", "prLinks"),
]


class InputError(Exception):
    pass


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def warn(message: str) -> None:
    print(f"render_artifact: warning: {message}", file=sys.stderr)


def is_web_url(target: str) -> bool:
    return target.startswith(("http://", "https://"))


def web_link(target: str, label: str) -> str:
    return f'<a href="{esc(target)}" target="_blank" rel="noopener">{label}</a>'


def bold_and_links(text: str) -> str:
    out = []
    pos = 0
    for m in LINK_RE.finditer(text):
        out.append(re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(text[pos:m.start()])))
        if is_web_url(m.group(2)):
            out.append(web_link(m.group(2), esc(m.group(1))))
        else:
            out.append(esc(m.group(0)))
        pos = m.end()
    out.append(re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(text[pos:])))
    return "".join(out)


def inline(text: object) -> str:
    """Escape text; `code` spans become <code>, **bold** becomes <strong>, and [label](url)
    becomes a link when url is http(s). Inline code never gets a Copy button."""
    parts = re.split(r"(`[^`]+`)", "" if text is None else str(text))
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{esc(part[1:-1])}</code>")
        else:
            out.append(bold_and_links(part))
    return "".join(out)


def copy_button(text: str) -> str:
    return f'<button type="button" class="copy-btn copy-code-btn" data-copy="{esc(text)}">Copy</button>'


def code_block(text: str) -> str:
    return f'<div class="codeblock"><pre><code>{esc(text)}</code></pre>{copy_button(text)}</div>'


def command_block(block: dict) -> str:
    """{"command", "cwd", "note"?}: a "Run in" line and a block whose Copy copies the command only."""
    command, cwd = block.get("command"), block.get("cwd")
    if not isinstance(command, str) or not isinstance(cwd, str) or not command or not cwd:
        raise InputError(f"a command block needs non-empty command and cwd strings; got keys {sorted(block)}")
    note = f'<p class="cmd-note">{inline(block["note"])}</p>' if block.get("note") else ""
    return f'<div class="cmd"><div class="cmd-cwd">Run in: <code>{esc(cwd)}</code></div>{code_block(command)}{note}</div>'


def text_or_command(value: object) -> str:
    return command_block(value) if isinstance(value, dict) else inline(value)


def summary_box(inner: str) -> str:
    return f'<div class="summary" role="note"><div class="summary-label">Summary</div>{inner}</div>'


def data_summary(data: dict) -> str:
    text = str(data.get("summary") or "").strip()
    if not text:
        warn("no summary key; the page renders without a Summary box")
        return ""
    return summary_box(f"<p>{inline(text)}</p>")


def data_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"


def split_row(line: str) -> list[str]:
    cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    return [c.strip().replace("\\|", "|") for c in cells]


def parse_blocks(lines: list[str]) -> list[tuple[str, object]]:
    """Group markdown lines into p, ul, ol, h3, pre, and table blocks."""
    blocks: list[tuple[str, object]] = []
    cur: tuple[str, object] | None = None
    fence: list[str] | None = None

    def flush() -> None:
        nonlocal cur
        if cur is not None:
            blocks.append(cur)
        cur = None

    for raw in lines:
        line = raw.rstrip()
        if fence is not None:
            if line.lstrip().startswith("```"):
                blocks.append(("pre", "\n".join(fence)))
                fence = None
            else:
                fence.append(raw.rstrip("\n"))
            continue
        if line.lstrip().startswith("```"):
            flush()
            fence = []
            continue
        if not line.strip():
            if cur and cur[0] in ("p", "table"):
                flush()
            continue
        if line.startswith(("### ", "#### ")):
            flush()
            blocks.append(("h3", line.split(" ", 1)[1].strip()))
            continue
        if line.lstrip().startswith("|"):
            if not cur or cur[0] != "table":
                flush()
                cur = ("table", [])
            if not re.fullmatch(r"\|?[\s:|-]+\|?", line.strip()):
                cur[1].append(split_row(line))
            continue
        m_ul = re.match(r"^[-*] (.*)$", line)
        m_ol = re.match(r"^(\d+)\. (.*)$", line)
        if m_ul:
            if not cur or cur[0] != "ul":
                flush()
                cur = ("ul", [])
            cur[1].append(m_ul.group(1))
        elif m_ol:
            if not cur or cur[0] != "ol":
                flush()
                cur = ("ol", [])
            cur[1].append((m_ol.group(1), m_ol.group(2)))
        elif line.startswith(" ") and cur and cur[0] in ("ul", "ol"):
            items = cur[1]
            if cur[0] == "ul":
                items[-1] = items[-1] + " " + line.strip()
            else:
                n, t = items[-1]
                items[-1] = (n, t + " " + line.strip())
        elif cur and cur[0] == "p":
            cur = ("p", cur[1] + " " + line.strip())
        else:
            flush()
            cur = ("p", line.strip())
    if fence is not None:
        blocks.append(("pre", "\n".join(fence)))
    flush()
    return blocks


def render_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    head = "".join(f"<th>{inline(c)}</th>" for c in rows[0])
    body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>" for row in rows[1:])
    return f'<div class="tbl"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def render_blocks(blocks: list[tuple[str, object]], ol_label: str = "Item") -> str:
    out = []
    in_sub = False
    for kind, val in blocks:
        if kind == "h3":
            if in_sub:
                out.append("</div>")
            out.append(f'<div class="sub"><h3 id="{slug(val)}">{inline(val)}</h3>')
            in_sub = True
        elif kind == "p":
            out.append(f"<p>{inline(val)}</p>")
        elif kind == "pre":
            out.append(code_block(val))
        elif kind == "table":
            out.append(render_table(val))
        elif kind == "ul":
            rows = "".join(f"<li>{inline(i)}</li>" for i in val)
            out.append(f'<ul class="rows">{rows}</ul>')
        elif kind == "ol":
            rows = "".join(f'<tr><td class="num">{esc(n)}</td><td>{inline(t)}</td></tr>' for n, t in val)
            out.append(
                f'<div class="tbl"><table class="numbered"><thead><tr><th>#</th><th>{esc(ol_label)}</th></tr>'
                f"</thead><tbody>{rows}</tbody></table></div>"
            )
    if in_sub:
        out.append("</div>")
    return "\n".join(out)


def parse_markdown(text: str) -> tuple[str, list[tuple[str, list[str]]]]:
    """Return the first `# ` title and the `## ` sections as (name, body lines)."""
    title = ""
    sections: list[tuple[str, list[str]]] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("# ") and not title:
            title = line[2:].strip()
        elif not in_fence and line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif sections:
            sections[-1][1].append(line)
    return title, sections


def render_sections(sections: list[tuple[str, list[str]]], collapsed: frozenset[str] = frozenset()) -> str:
    """Render `## ` sections; a name in collapsed (lower-case) renders inside a closed <details>."""
    used = set(FIXED_IDS)
    out = []
    for name, body in sections:
        sid = slug(name)
        n = 2
        while sid in used:
            sid = f"{slug(name)}-{n}"
            n += 1
        used.add(sid)
        label = "Criterion" if "criteri" in name.lower() else "Item"
        inner = render_blocks(parse_blocks(body), label)
        if name.strip().lower() in collapsed:
            out.append(fold_section(sid, name, "", inner))
        else:
            out.append(f'<section id="{sid}" data-toc="{esc(name)}"><h2>{esc(name)}</h2>{inner}</section>')
    return "\n".join(out)


def fold_section(sid: str, label: str, line: str, inner: str) -> str:
    """A section whose body starts closed; line is shown beside the heading while it is closed."""
    line_html = f'<span class="fold-line">{line}</span>' if line else ""
    return (
        f'<section id="{sid}" data-toc="{esc(label)}"><details class="fold"><summary>'
        f"<h2>{esc(label)}</h2>{line_html}</summary>{inner}</details></section>"
    )


def pairs(value: object, keys: tuple[str, str]) -> list[tuple[str, str]]:
    """Accept [[a, b], ...] or [{keys[0]: a, keys[1]: b}, ...]."""
    out = []
    for row in value or []:
        if isinstance(row, dict):
            out.append((str(row.get(keys[0], "")), str(row.get(keys[1], ""))))
        else:
            first, second = row
            out.append((str(first), str(second)))
    return out


def link_rows(links: object) -> str:
    out = []
    for label, target in pairs(links, ("label", "url")):
        if is_web_url(target):
            value = web_link(target, esc(target))
        else:
            value = f"<code>{esc(target)}</code>"
        out.append(
            f"<tr><td>{esc(label)}</td><td>{value}</td>"
            f'<td><button type="button" class="copy-btn copy-link-btn" data-copy="{esc(target)}">Copy</button></td></tr>'
        )
    return "".join(out) or '<tr><td colspan="3" class="muted">No links yet.</td></tr>'


def keep_block(page: str, name: str, keep: bool) -> str:
    """Drop <!--NAME_START-->...<!--NAME_END--> when keep is false; otherwise strip only the markers."""
    pattern = rf"<!--\s*{name}_START\s*-->(.*?)<!--\s*{name}_END\s*-->"
    return re.sub(pattern, (lambda m: m.group(1)) if keep else "", page, flags=re.S)


def section_html(sid: str, label: str, inner: str) -> str:
    return f'<section id="{sid}" data-toc="{esc(label)}"><h2>{esc(label)}</h2>{inner}</section>'


PLAN_FIXED_SECTIONS = ("out of scope", "risks", "alternatives", "open questions")
PLAN_COLLAPSED = frozenset({"public api contract", "phases"})


def plan_tests(tests: list[str] | None) -> tuple[str, str]:
    """Return the Tests section body and the one-line Tests entry for the Decision box."""
    if tests is None:
        return (
            '<p class="warn">plan.md has no <code>## Tests</code> section.</p>',
            '<span class="warn">plan.md has no Tests section</span>',
        )
    blocks = parse_blocks(tests)
    if len(blocks) == 1 and blocks[0][0] == "p" and str(blocks[0][1]).startswith("None:"):
        line = inline(blocks[0][1])
        return f'<p class="muted">{line}</p>', line
    tables = [val for kind, val in blocks if kind == "table"]
    count = max(len(tables[0]) - 1, 0) if tables else 0
    return render_blocks(blocks), f"{count} test{'' if count == 1 else 's'} in the Tests section"


def decision_box(decision: object, tests_line: str, has_risks: bool) -> str:
    decision = decision if isinstance(decision, dict) else {}
    rows = [
        (label, inline(decision[key]))
        for label, key in (("Approving", "approving"), ("Size", "size"), ("Top risk", "topRisk"))
        if decision.get(key)
    ]
    rows.append(("Tests", tests_line))
    if not has_risks:
        rows.append(("Risks", "none listed"))
    body = "".join(f"<dt>{esc(label)}</dt><dd>{value}</dd>" for label, value in rows)
    return f'<div class="decision" role="note"><div class="summary-label">Decision</div><dl>{body}</dl></div>'


def review_count(findings: list[dict]) -> str:
    counts = {"folded": 0, "rejected": 0, "other": 0}
    for finding in findings:
        disposition = str(finding.get("disposition", "")).strip().lower()
        kind = next((k for k in ("folded", "rejected") if disposition.startswith(k)), "other")
        counts[kind] += 1
    total = len(findings)
    return (
        f"{total} finding{'' if total == 1 else 's'}: {counts['folded']} folded, "
        f"{counts['rejected']} rejected, {counts['other']} other"
    )


def plan_slots(data: dict, markdown: str, _base: Path) -> tuple[dict[str, str], dict[str, bool]]:
    md_title, sections = parse_markdown(markdown)
    by_name: dict[str, list[str]] = {}
    for name, body in sections:
        by_name.setdefault(name.strip().lower(), body)
    if "summary" in by_name:
        summary_html = summary_box(render_blocks(parse_blocks(by_name["summary"])))
    else:
        summary_html = ""
        warn("plan.md has no ## Summary section; the page renders without a Summary box")
    has_risks = "risks" in by_name
    if not has_risks:
        warn('plan.md has no ## Risks section; the Decision box shows "Risks: none listed"')
    if not data.get("decision"):
        warn("no decision key; the Decision box shows only the Tests line")
    tests_html, tests_line = plan_tests(by_name.get("tests"))

    fixed = [(name, body) for key in PLAN_FIXED_SECTIONS for name, body in sections if name.strip().lower() == key]
    skip = {"summary", "tests", *PLAN_FIXED_SECTIONS}
    rest = [(name, body) for name, body in sections if name.strip().lower() not in skip]

    meta = []
    if data.get("ticket"):
        meta.append(f'<span class="pill">{esc(data["ticket"])}</span>')
    for key in ("repo", "date"):
        if data.get(key):
            meta.append(f"<span>{esc(data[key])}</span>")
    lenses = data.get("lenses")
    if isinstance(lenses, list):
        lenses = ", ".join(str(x) for x in lenses)
    run_rows = [
        [label, str(value)]
        for label, value in (("Run dir", data.get("runDir")), ("Sandbox", data.get("sandboxTier")), ("Lenses", lenses))
        if value
    ]

    rules = [str(r) for r in data.get("accessRules") or []]
    access = section_html(
        "access-rules", "Access rules", '<ul class="rows">' + "".join(f"<li>{inline(r)}</li>" for r in rules) + "</ul>"
    ) if rules else ""

    review = data.get("planReview") or {}
    findings = review.get("findings") or []
    review_html = ""
    if review.get("verdict") or findings:
        inner = f'<p><b>Verdict:</b> {inline(review.get("verdict", ""))}</p>' if review.get("verdict") else ""
        if findings:
            rows = "".join(
                f'<tr><td>{inline(f.get("severity", ""))}</td><td>{inline(f.get("text", ""))}</td>'
                f'<td>{inline(f.get("disposition", ""))}</td></tr>'
                for f in findings
            )
            inner += (
                '<div class="tbl"><table class="review"><thead><tr><th>Severity</th><th>Finding</th>'
                f"<th>Disposition</th></tr></thead><tbody>{rows}</tbody></table></div>"
            )
        line = review_count(findings) if findings else "no findings"
        review_html = fold_section("plan-review", "Plan review", esc(line), inner)

    pending = pairs(data.get("pending"), ("item", "state"))
    pending_html = fold_section(
        "pending",
        "Pending additions",
        esc(f"{len(pending)} item{'' if len(pending) == 1 else 's'}"),
        '<div class="tbl"><table class="pending"><thead><tr><th>Item</th><th>State</th></tr></thead><tbody>'
        + "".join(f"<tr><td>{inline(i)}</td><td>{inline(s)}</td></tr>" for i, s in pending)
        + "</tbody></table></div>",
    ) if pending else ""

    nxt = data.get("next", "")
    go_html = (
        '<div class="next go" role="note"><div class="summary-label">To start</div><ol>'
        f"<li>Reply <strong>{esc(nxt)}</strong> to approve the plan.</li>"
        "<li>Reply <strong>tests yes</strong> (or confirm the None reason) to approve the tests.</li>"
        "</ol></div>"
    ) if nxt else ""
    lane = data.get("lane", "")
    slots = {
        "TITLE": esc(data.get("title") or md_title),
        "EYEBROW": esc(f"Forge plan - {lane} lane" if lane else "Forge plan"),
        "META_HTML": "".join(meta),
        "STATUS": inline(data.get("status") or "Awaiting approval"),
        "SUMMARY_HTML": summary_html,
        "DECISION_HTML": decision_box(data.get("decision"), tests_line, has_risks),
        "SECTIONS": render_sections(fixed + rest, PLAN_COLLAPSED),
        "TESTS_HTML": tests_html,
        "ACCESS_RULES_SECTION": access,
        "PLAN_REVIEW_SECTION": review_html,
        "PENDING_SECTION": pending_html,
        "LINKS": link_rows(run_rows + pairs(data.get("links"), ("label", "url"))),
        "NEXT": go_html,
    }
    return slots, {"SUMMARY": bool(summary_html)}


TONE_WORDS = {"ok": "OK", "warn": "Warning", "fail": "Failed"}


def tone(value: object, where: str) -> str:
    """Return a known tone ("ok", "warn", "fail") or "" after warning about an unknown one."""
    if not value:
        return ""
    if value not in TONE_WORDS:
        warn(f"{where} {value!r} is not one of ok, warn, fail; shown without a colour")
        return ""
    return str(value)


def key_numbers_html(rows: object) -> str:
    tiles = []
    for row in rows or []:
        if not isinstance(row, dict):
            raise InputError(f"keyNumbers entries must be objects with label and value; got {row!r}")
        row_tone = tone(row.get("status"), f"keyNumbers status for {row.get('label', '')!r}")
        word = f'<div class="kpi-word">{TONE_WORDS[row_tone]}</div>' if row_tone else ""
        tone_class = f" tone-{row_tone}" if row_tone else ""
        tiles.append(
            f'<div class="kpi{tone_class}"><div class="kpi-label">{esc(row.get("label", ""))}</div>'
            f'<div class="kpi-value">{esc(row.get("value", ""))}</div>{word}</div>'
        )
    return f'<div class="kpis">{"".join(tiles)}</div>' if tiles else ""


def next_steps_html(steps: object) -> str:
    items = "".join(f"<li>{inline(step)}</li>" for step in steps or [])
    if not items:
        return ""
    return f'<div class="next" role="note"><div class="summary-label">Next steps</div><ol class="steps">{items}</ol></div>'


def generic_slots(data: dict, markdown: str, _base: Path) -> tuple[dict[str, str], dict[str, bool]]:
    md_title, sections = parse_markdown(markdown)
    status = data.get("status", "")
    status_tone = tone(data.get("statusTone"), "statusTone")
    slots = {
        "TITLE": esc(data.get("title") or md_title),
        "EYEBROW": esc(data.get("eyebrow", "")),
        "STATUS": inline(status),
        "STATUS_TONE": f"tone-{status_tone}" if status_tone else "",
        "STATUS_LABEL": f"Status: {TONE_WORDS[status_tone]}" if status_tone else "Status",
        "SUMMARY_HTML": data_summary(data),
        "KEY_NUMBERS_HTML": key_numbers_html(data.get("keyNumbers")),
        "NEXT_STEPS_HTML": next_steps_html(data.get("nextSteps")),
        "SECTIONS": render_sections(sections),
        "LINKS": link_rows(data.get("links")),
    }
    keep = {
        "STATUS": bool(status),
        "SUMMARY": bool(slots["SUMMARY_HTML"]),
        "KEY_NUMBERS": bool(slots["KEY_NUMBERS_HTML"]),
        "NEXT_STEPS": bool(slots["NEXT_STEPS_HTML"]),
    }
    return slots, keep


DB_ID_BAD_RE = re.compile(r"[^A-Za-z0-9_\-.~:@+]")
DB_ID_MAX_BYTES = 200
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
MAX_IMAGE_BYTES = 1_572_864
MAX_PAGE_IMAGE_BYTES = 8 * 1_048_576
COLLAPSE_LINES = 15
VERDICT_CONTROLS = (
    '<div class="verdict" role="group" aria-label="Result">'
    '<button type="button" class="verdict-btn" data-verdict="pass" aria-pressed="false">Pass</button>'
    '<button type="button" class="verdict-btn" data-verdict="fail" aria-pressed="false">Fail</button>'
    '<button type="button" class="verdict-btn" data-verdict="blocked" aria-pressed="false">Blocked</button>'
    '<input type="text" class="verdict-note" maxlength="300" placeholder="What I saw" aria-label="What I saw">'
    "</div>"
)


def qa_round(data: dict) -> str:
    raw = str(data.get("round") or "1")
    if len(raw) > 100 or DB_ID_BAD_RE.search(raw):
        raise InputError(f"round {raw!r} must be at most 100 letters, digits or _ - . ~ : @ +")
    return raw


def qa_ids(items: list[dict], round_id: str, has_explore: bool) -> list[str]:
    """Item ids limited to the page-storage id charset, so "<round>:<id>" is one valid document id."""
    limit = DB_ID_MAX_BYTES - len(round_id) - 1
    ids: list[str] = []
    seen: dict[str, str] = {"explore": "the explore item"} if has_explore else {}
    for idx, item in enumerate(items, start=1):
        raw = str(item.get("id") or idx)
        sid = DB_ID_BAD_RE.sub("-", raw)[:limit]
        if sid in seen:
            raise InputError(f"qaItems id {raw!r} and {seen[sid]} both become {sid!r}; give each item a distinct id")
        seen[sid] = f"id {raw!r}"
        ids.append(sid)
    return ids


def pre_block(text: object, collapse: bool = True) -> str:
    body = text if isinstance(text, str) else json.dumps(text, indent=2)
    pre = f"<pre><code>{esc(body)}</code></pre>"
    lines = body.count("\n") + 1
    if collapse and lines > COLLAPSE_LINES:
        return f'<details class="long-output"><summary>Show all {lines} lines</summary>{pre}</details>'
    return pre


class ImageBudget:
    def __init__(self) -> None:
        self.used = 0

    def embed(self, path: Path, caption: str) -> str:
        mime = IMAGE_TYPES.get(path.suffix.lower())
        size = path.stat().st_size
        reason = ""
        if not mime:
            reason = f"{path.suffix or 'no extension'} is not PNG, JPEG or WebP"
        elif size > MAX_IMAGE_BYTES:
            reason = f"{size} bytes is over the {MAX_IMAGE_BYTES}-byte image cap"
        elif self.used + size > MAX_PAGE_IMAGE_BYTES:
            reason = f"the page already holds {self.used} bytes of images (cap {MAX_PAGE_IMAGE_BYTES})"
        if reason:
            warn(f"screenshot {path} not embedded: {reason}")
            label = f"{esc(caption)} " if caption else ""
            return f'<p class="shot-text">{label}<span class="muted">({esc(path)})</span></p>'
        self.used += size
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f'<img class="shot" src="data:{mime};base64,{data}" alt="{esc(caption or path.name)}">'


def before_after(before: str, after: str) -> str:
    if not before:
        return after
    return (
        f'<div class="before-after"><div><div class="ba-label">Before</div>{before}</div>'
        f'<div><div class="ba-label">After</div>{after}</div></div>'
    )


def example_html(item_id: str, example: object, base: Path, images: ImageBudget) -> str:
    """Render a captured example, or "" (with a warning) when it cannot be shown truthfully."""
    if not isinstance(example, dict):
        warn(f"item {item_id}: example must be an object; dropped")
        return ""
    kind = example.get("kind")
    captured = str(example.get("capturedFrom") or "")
    if not captured or not data_path(captured, base).exists():
        warn(f"item {item_id}: example dropped, capturedFrom {captured or '(missing)'} does not exist")
        return ""
    source = f'<p class="example-source muted">Captured from <code>{esc(data_path(captured, base))}</code></p>'
    if kind == "screenshot":
        paths = {key: str(example.get(key) or "") for key in ("path", "beforePath")}
        if not paths["path"]:
            warn(f"item {item_id}: screenshot example has no path; dropped")
            return ""
        for key, value in paths.items():
            if value and not data_path(value, base).is_file():
                warn(f"item {item_id}: example dropped, {key} {value} does not exist")
                return ""
        caption = str(example.get("caption") or "")
        after = images.embed(data_path(paths["path"], base), caption)
        before = images.embed(data_path(paths["beforePath"], base), caption) if paths["beforePath"] else ""
        body = before_after(before, after)
        if caption:
            body += f'<p class="muted">{inline(caption)}</p>'
    elif kind == "terminal":
        body = pre_block(example.get("command", ""), collapse=False)
        before = pre_block(example["beforeOutput"]) if example.get("beforeOutput") else ""
        body += before_after(before, pre_block(example.get("output", "")))
    elif kind == "http":
        body = pre_block(example.get("request", ""), collapse=False)
        before = pre_block(example["beforeResponse"]) if example.get("beforeResponse") else ""
        body += before_after(before, pre_block(example.get("response", "")))
    else:
        warn(f"item {item_id}: example kind {kind!r} is not screenshot, terminal or http; dropped")
        return ""
    return f"<dt>Example</dt><dd>{body}{source}</dd>"


def automated_check(click: dict, base: Path) -> str:
    status = str(click.get("status", "PENDING")).upper()
    label = "pending" if status == "PENDING" else status
    shot = str(click.get("screenshot") or "")
    if shot and not is_web_url(shot):
        shot = str(data_path(shot, base))
    shot_link = f' <a href="{esc(shot)}">screenshot</a>' if shot else ""
    note = f" - {esc(click['note'])}" if click.get("note") else ""
    return (
        f'<div class="auto-check"><span class="auto-label">Automated check</span> '
        f'<span class="status-{esc(status.lower())}">{esc(label)}</span>{note}{shot_link}</div>'
    )


def item_shell(idx: object, item_id: str, title: str, pr: str, group: str, body: str) -> str:
    return (
        f'<details class="qa-item" data-id="{esc(item_id)}" data-pr="{esc(pr)}" data-group="{esc(group)}" '
        f'data-verdict="untested">'
        f'<summary><span class="qa-num">{esc(idx)}.</span> <span class="qa-title">{esc(title)}</span>'
        f'<span class="qa-badges"><span class="pill pr">{esc(pr)}</span>'
        f'<span class="pill verdict-pill">untested</span></span></summary>'
        f'<div class="qa-body">{VERDICT_CONTROLS}{body}</div></details>'
    )


def qa_item_html(idx: int, item_id: str, item: dict, group_why: str, base: Path, images: ImageBudget) -> str:
    group = item.get("screenGroup") or "Other"
    click = item.get("clickPass")
    rows = []
    if item.get("ticketKey") or item.get("ticketUrl"):
        url = str(item.get("ticketUrl") or "")
        key = esc(item.get("ticketKey") or url)
        rows.append(f"<dt>Ticket</dt><dd>{web_link(url, key) if is_web_url(url) else key}</dd>")
    why = str(item.get("why") or "").strip()
    if not why and str(item.get("before") or "").strip():
        why = str(item["before"]).strip()
    if why and why != group_why.strip():
        rows.append(f"<dt>Why</dt><dd>{inline(why)}</dd>")
    if item.get("whatChanged"):
        rows.append(f'<dt>What changed</dt><dd>{inline(item["whatChanged"])}</dd>')
    steps = "".join(f"<li>{text_or_command(s)}</li>" for s in item.get("steps") or [])
    rows.append(f"<dt>Steps</dt><dd><ol>{steps}</ol></dd>")
    rows.append(f'<dt>Expected</dt><dd>{inline(item.get("expected", ""))}</dd>')
    if "example" in item:
        rows.append(example_html(item_id, item["example"], base, images))
    if item.get("evidence"):
        rows.append(f'<dt>Evidence</dt><dd>{inline(item["evidence"])}</dd>')
    auto = automated_check(click, base) if click else ""
    return item_shell(idx, item_id, str(item.get("title", "")), str(item.get("pr", "")), group,
                      f'{auto}<dl>{"".join(rows)}</dl>')


def setup_html(setup: object) -> str:
    if not isinstance(setup, dict):
        return ""
    parts = []
    for key, label in (("preconditions", "Before you start"), ("testData", "Test data")):
        values = setup.get(key) or []
        if values:
            parts.append(f'<div class="setup-label">{label}</div><ul>' + "".join(f"<li>{inline(v)}</li>" for v in values) + "</ul>")
    commands = setup.get("commands") or []
    if commands:
        parts.append('<div class="setup-label">Commands</div>' + "".join(command_block(c) for c in commands))
    cleanup = setup.get("cleanup") or []
    if cleanup:
        parts.append('<div class="setup-label">Cleanup</div><ul>' + "".join(f"<li>{text_or_command(c)}</li>" for c in cleanup) + "</ul>")
    return f'<div class="setup"><div class="setup-title">Setup</div>{"".join(parts)}</div>' if parts else ""


def qa_group_html(name: str, group: dict | None, items_html: str) -> str:
    why = f'<p class="group-why"><b>Why:</b> {inline(group["why"])}</p>' if group and group.get("why") else ""
    setup = setup_html(group.get("setup")) if group else ""
    spot = (
        f'<p class="spot-check"><b>Spot check:</b> {inline(group["spotCheck"])}</p>'
        if group and group.get("spotCheck") else ""
    )
    return (
        f'<div class="qa-group" data-group="{esc(name)}"><div class="group-head"><h3>{esc(name)}</h3>'
        f'<span class="group-counts"></span></div>{why}{setup}{spot}<div class="qa-items-list">{items_html}</div></div>'
    )


def explore_html(explore: object) -> str:
    if not isinstance(explore, dict) or not isinstance(explore.get("minutes"), int):
        raise InputError('explore must be {"minutes": int, "focus": str}')
    minutes = explore["minutes"]
    title = f"Explore freely for {minutes} minute{'' if minutes == 1 else 's'}"
    body = f'<dl><dt>Focus</dt><dd>{inline(explore.get("focus", ""))}</dd></dl>'
    return qa_group_html("Explore", None, item_shell("E", "explore", title, "", "Explore", body))


def qa_groups_html(data: dict, items: list[dict], ids: list[str], base: Path) -> tuple[str, int]:
    groups = [g for g in data.get("groups") or [] if isinstance(g, dict) and g.get("name")]
    by_name = {str(g["name"]): g for g in reversed(groups)}
    order = list(dict.fromkeys(str(g["name"]) for g in groups))
    for item in items:
        name = str(item.get("screenGroup") or "Other")
        if name not in order:
            order.append(name)
    images = ImageBudget()
    deprecated = sum(1 for i in items if not str(i.get("why") or "").strip() and str(i.get("before") or "").strip())
    if deprecated:
        warn(f"{deprecated} qaItems use the deprecated key before; rename it to why")
    out = []
    num = 0
    shown = 0
    for name in order:
        group = by_name.get(name)
        group_why = str(group.get("why") or "") if group else ""
        members = [(i, item) for i, item in enumerate(items) if str(item.get("screenGroup") or "Other") == name]
        if not members:
            continue
        parts = []
        for i, item in members:
            num += 1
            parts.append(qa_item_html(num, ids[i], item, group_why, base, images))
        shown += 1
        out.append(qa_group_html(name, group, "".join(parts)))
    if "explore" in data:
        out.append(explore_html(data["explore"]))
        shown += 1
    return "".join(out), shown


def qa_status(items: list[dict], groups: int, has_explore: bool) -> str:
    total = len(items) + (1 if has_explore else 0)
    text = (
        f'{total} items in {groups} group{"" if groups == 1 else "s"}: '
        f'<span class="verdict-counts">untested {total}</span>'
    )
    checks = [str(i["clickPass"].get("status", "PENDING")).upper() for i in items if i.get("clickPass")]
    ran = [c for c in checks if c != "PENDING"]
    if ran:
        text += (
            f' &middot; automated checks: <span class="status-pass">PASS {ran.count("PASS")}</span>, '
            f'<span class="status-fail">FAIL {ran.count("FAIL")}</span>'
        )
        if ran.count("SKIP"):
            text += f", SKIP {ran.count('SKIP')}"
        if ran.count("BLOCKED"):
            text += f', <span class="status-blocked">BLOCKED {ran.count("BLOCKED")}</span>'
    return text


def qa_slots(data: dict, _markdown: str, base: Path) -> tuple[dict[str, str], dict[str, bool]]:
    items = data.get("qaItems") or []
    round_id = qa_round(data)
    ids = qa_ids(items, round_id, "explore" in data)
    items_html, group_count = qa_groups_html(data, items, ids, base)
    users = data.get("users") or []
    jira = data.get("jiraTickets") or []
    context = data.get("contextItems") or []
    handoff = data.get("handoff") or {}

    def handoff_html(key: str) -> str:
        text = str(handoff.get(key) or "")
        return render_blocks(parse_blocks(text.splitlines())) if text.strip() else ""

    slots = {
        "TICKET": esc(data.get("ticket", "")),
        "SHORT_TITLE": esc(data.get("shortTitle", "")),
        "DATE": esc(data.get("date", "")),
        "TIER": esc(data.get("tier", "")),
        "BRANCH": esc(data.get("branch", "")),
        "SANDBOX_ID": esc(data.get("sandboxId", "")),
        "PREVIEW_URL": esc(data.get("previewUrl", "")),
        "ROOT_LOGIN_EMAIL": esc(data.get("rootLoginEmail", "")),
        "ROOT_LOGIN_PASSWORD": esc(data.get("rootLoginPassword", "")),
        "ADMIN_CREDS": esc(data.get("adminCreds", "")),
        "ROUND": esc(round_id),
        "STATUS": qa_status(items, group_count, "explore" in data),
        "SUMMARY_HTML": data_summary(data),
        "USERS_ROWS_HTML": "".join(
            f'<tr class="copy-row"><td>{esc(u.get("role", ""))}</td><td><span class="copy-value" data-role="value"></span></td>'
            f'<td><button type="button" class="copy-btn" data-copy="{esc(u.get("email", ""))}">Copy</button></td>'
            f'<td>{esc(u.get("note", ""))}</td></tr>'
            for u in users
        ),
        "JIRA_TICKET_ROWS_HTML": "".join(
            f'<tr><td><a href="{esc(r.get("url", ""))}">{esc(r.get("key", ""))}</a></td>'
            f'<td>{esc(r.get("title", ""))}</td><td>{esc(r.get("role", ""))}</td></tr>'
            for r in jira
        ),
        "LINKS_HTML": link_rows(data.get("links")),
        "CONTEXT_ITEMS_HTML": "".join(f"<li>{text_or_command(c)}</li>" for c in context),
        "QA_ITEMS_HTML": items_html,
    }
    keep = {
        "USERS_SECTION": bool(users), "JIRA_SECTION": bool(jira), "CONTEXT_SECTION": bool(context),
        "SUMMARY": bool(slots["SUMMARY_HTML"]),
    }
    any_handoff = False
    for slot, key in HANDOFF_KEYS:
        slots[slot] = handoff_html(key)
        keep[slot.removesuffix("_HTML")] = bool(slots[slot])
        any_handoff = any_handoff or bool(slots[slot])
    keep["HANDOFF_SECTION"] = any_handoff
    return slots, keep


def build_toc(page: str, slots: dict[str, str]) -> str:
    entries: list[tuple[str, str]] = []
    for m in TOC_SOURCE_RE.finditer(page):
        if m.group(3):
            entries.extend(SECTION_RE.findall(slots.get(m.group(3), "")))
        else:
            entries.append((m.group(1), m.group(2)))
    return "".join(f'<a href="#{sid}">{label}</a>' for sid, label in entries)


def render(kind: str, data: dict, markdown: str, base: Path) -> tuple[str, list[str]]:
    for key in sorted(set(data) - KNOWN_KEYS[kind]):
        warn(f"unknown key {key} ignored")
    template = (REFERENCES / f"{kind}-artifact.html").read_text()
    page = re.sub(r"\A\s*<!--.*?-->\s*", "", template, count=1, flags=re.S)
    builder = {"plan": plan_slots, "qa": qa_slots, "generic": generic_slots}[kind]
    slots, keep = builder(data, markdown, base)
    for name, kept in keep.items():
        page = keep_block(page, name, kept)
    slots["TOC"] = build_toc(page, slots)
    missing = sorted(set(SLOT_RE.findall(page)) - set(slots))
    page = SLOT_RE.sub(lambda m: slots.get(m.group(1), m.group(0)), page)
    return page, missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a forge artifact page from a template and data.")
    parser.add_argument("kind", choices=["plan", "qa", "generic"])
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.kind != "qa" and args.markdown is None:
        parser.error(f"{args.kind} needs --markdown")
    try:
        data = json.loads(args.data.read_text())
        markdown = args.markdown.read_text() if args.markdown else ""
        if not isinstance(data, dict):
            raise InputError(f"{args.data} must hold a JSON object")
        page, missing = render(args.kind, data, markdown, args.data.resolve().parent)
    except (OSError, json.JSONDecodeError, InputError) as exc:
        print(f"render_artifact: {exc}", file=sys.stderr)
        return 2
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        print(f"render_artifact: {args.data} does not match the {args.kind} contract: {exc!r}", file=sys.stderr)
        return 2
    if missing:
        print("render_artifact: unfilled slots: " + ", ".join("{{" + m + "}}" for m in missing), file=sys.stderr)
        return 1
    args.out.write_text(page)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
