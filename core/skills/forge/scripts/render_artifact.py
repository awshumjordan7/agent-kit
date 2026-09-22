#!/usr/bin/env python3
"""Render a forge artifact page from a template in ../references/ and a data file.

Usage:
  render_artifact.py plan --data plan-data.json --markdown plan.md --out plan-artifact.html
  render_artifact.py qa --data qa-data.json --out qa-artifact.html
  render_artifact.py generic --data data.json --markdown notes.md --out page.html

Exit codes: 0 rendered, 1 the template has a slot this renderer did not fill, 2 bad input.
Each template's leading comment is its data contract; it is removed before slots are filled.
"""

import argparse
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


def inline(text: str) -> str:
    """Escape text; `code` spans become <code>, **bold** becomes <strong>."""
    parts = re.split(r"(`[^`]+`)", str(text))
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{esc(part[1:-1])}</code>")
        else:
            out.append(re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(part)))
    return "".join(out)


def copy_spans(text: object) -> str:
    """Escape text; each `code` span becomes copyable code with its own Copy button."""
    parts = re.split(r"(`[^`]+`)", "" if text is None else str(text))
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) >= 2:
            raw = esc(part[1:-1])
            out.append(
                f'<code class="copy-code">{raw}</code><button type="button" '
                f'class="copy-btn copy-code-btn" data-copy="{raw}">Copy</button>'
            )
        else:
            out.append(esc(part))
    return "".join(out)


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
            out.append(f"<pre><code>{esc(val)}</code></pre>")
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


def render_sections(sections: list[tuple[str, list[str]]]) -> str:
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
        out.append(
            f'<section id="{sid}" data-toc="{esc(name)}"><h2>{esc(name)}</h2>'
            f"{render_blocks(parse_blocks(body), label)}</section>"
        )
    return "\n".join(out)


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
        if target.startswith(("http://", "https://")):
            value = f'<a href="{esc(target)}" target="_blank" rel="noopener">{esc(target)}</a>'
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


def plan_slots(data: dict, markdown: str) -> tuple[dict[str, str], dict[str, bool]]:
    md_title, sections = parse_markdown(markdown)
    tests = [body for name, body in sections if name.strip().lower() == "tests"]
    others = [(name, body) for name, body in sections if name.strip().lower() != "tests"]
    if tests:
        blocks = parse_blocks(tests[0])
        if len(blocks) == 1 and blocks[0][0] == "p" and str(blocks[0][1]).startswith("None:"):
            tests_html = f'<p class="muted">{inline(blocks[0][1])}</p>'
        else:
            tests_html = render_blocks(blocks)
    else:
        tests_html = '<p class="warn">plan.md has no <code>## Tests</code> section.</p>'

    meta = []
    if data.get("ticket"):
        meta.append(f'<span class="pill">{esc(data["ticket"])}</span>')
    for key in ("repo", "date"):
        if data.get(key):
            meta.append(f"<span>{esc(data[key])}</span>")
    if data.get("runDir"):
        meta.append(f"<span>run dir <code>{esc(data['runDir'])}</code></span>")
    if data.get("sandboxTier"):
        meta.append(f'<span class="pill">sandbox: {esc(data["sandboxTier"])}</span>')
    lenses = data.get("lenses")
    if isinstance(lenses, list):
        lenses = ", ".join(str(x) for x in lenses)
    if lenses:
        meta.append(f'<span class="pill">lenses: {esc(lenses)}</span>')

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
        review_html = section_html("plan-review", "Plan review", inner)

    pending = pairs(data.get("pending"), ("item", "state"))
    pending_html = section_html(
        "pending",
        "Pending additions",
        '<div class="tbl"><table class="pending"><thead><tr><th>Item</th><th>State</th></tr></thead><tbody>'
        + "".join(f"<tr><td>{inline(i)}</td><td>{inline(s)}</td></tr>" for i, s in pending)
        + "</tbody></table></div>",
    ) if pending else ""

    nxt = data.get("next", "")
    lane = data.get("lane", "")
    slots = {
        "TITLE": esc(data.get("title") or md_title),
        "EYEBROW": esc(f"Forge plan - {lane} lane" if lane else "Forge plan"),
        "META_HTML": "".join(meta),
        "STATUS": inline(data.get("status") or "Awaiting approval"),
        "SECTIONS": render_sections(others),
        "TESTS_HTML": tests_html,
        "ACCESS_RULES_SECTION": access,
        "PLAN_REVIEW_SECTION": review_html,
        "PENDING_SECTION": pending_html,
        "LINKS": link_rows(data.get("links")),
        "NEXT": f'<div class="next"><strong>Say "{esc(nxt)}" to run it.</strong></div>' if nxt else "",
    }
    return slots, {}


def generic_slots(data: dict, markdown: str) -> tuple[dict[str, str], dict[str, bool]]:
    md_title, sections = parse_markdown(markdown)
    status = data.get("status", "")
    slots = {
        "TITLE": esc(data.get("title") or md_title),
        "EYEBROW": esc(data.get("eyebrow", "")),
        "STATUS": inline(status),
        "SECTIONS": render_sections(sections),
        "LINKS": link_rows(data.get("links")),
    }
    return slots, {"STATUS": bool(status)}


def qa_item_html(idx: int, item: dict) -> str:
    click = item.get("clickPass")
    status = str(click.get("status", "PENDING")).upper() if click else "none"
    label = "pending" if status == "PENDING" else (status if click else "not run")
    group = item.get("screenGroup") or "Other"
    rows = [
        f'<dt>Ticket</dt><dd><a href="{esc(item.get("ticketUrl", ""))}">{esc(item.get("ticketKey", ""))}</a></dd>',
        f'<dt>Before</dt><dd>{copy_spans(item.get("before", ""))}</dd>',
    ]
    if item.get("whatChanged"):
        rows.append(f'<dt>What changed</dt><dd>{copy_spans(item["whatChanged"])}</dd>')
    if item.get("why"):
        rows.append(f'<dt>Why</dt><dd>{copy_spans(item["why"])}</dd>')
    steps = "".join(f"<li>{copy_spans(s)}</li>" for s in item.get("steps") or [])
    rows.append(f"<dt>Steps</dt><dd><ol>{steps}</ol></dd>")
    rows.append(f'<dt>Expected</dt><dd>{copy_spans(item.get("expected", ""))}</dd>')
    if click:
        shot = click.get("screenshot", "")
        shot_link = f' <a href="{esc(shot)}">screenshot</a>' if shot else ""
        rows.append(f'<dt>Click pass</dt><dd>{esc(status)} - {esc(click.get("note", ""))}{shot_link}</dd>')
    rows.append(f'<dt>Evidence</dt><dd>{copy_spans(item.get("evidence", ""))}</dd>')
    return (
        f'<details class="qa-item" data-id="{esc(item.get("id", str(idx)))}" data-pr="{esc(item.get("pr", ""))}" '
        f'data-group="{esc(group)}" data-status="{esc(status)}">'
        f'<summary><span class="qa-num">{idx}.</span> <span class="qa-title">{esc(item.get("title", ""))}</span>'
        f'<span class="qa-badges"><span class="pill pr">{esc(item.get("pr", ""))}</span>'
        f'<span class="pill group">{esc(group)}</span>'
        f'<span class="pill status status-{esc(status.lower())}">{esc(label)}</span></span>'
        f'<label class="verify"><input type="checkbox" class="verify-toggle"> verified</label></summary>'
        f'<dl>{"".join(rows)}</dl></details>'
    )


def qa_status(items: list[dict]) -> str:
    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0, "PENDING": 0, "none": 0}
    for item in items:
        click = item.get("clickPass")
        key = str(click.get("status", "PENDING")).upper() if click else "none"
        counts[key] = counts.get(key, 0) + 1
    parts = [
        f'<span class="status-pass">PASS {counts["PASS"]}</span>',
        f'<span class="status-fail">FAIL {counts["FAIL"]}</span>',
        f"pending {counts['PENDING']}",
    ]
    if counts["SKIP"]:
        parts.append(f"SKIP {counts['SKIP']}")
    if counts["none"]:
        parts.append(f"not run {counts['none']}")
    return f"{len(items)} items: " + " &middot; ".join(parts)


def qa_slots(data: dict, _markdown: str) -> tuple[dict[str, str], dict[str, bool]]:
    items = data.get("qaItems") or []
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
        "STATUS": qa_status(items),
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
        "CONTEXT_ITEMS_HTML": "".join(f"<li>{copy_spans(c)}</li>" for c in context),
        "QA_ITEMS_HTML": "".join(qa_item_html(i, item) for i, item in enumerate(items, start=1)),
    }
    keep = {"USERS_SECTION": bool(users), "JIRA_SECTION": bool(jira), "CONTEXT_SECTION": bool(context)}
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


def render(kind: str, data: dict, markdown: str) -> tuple[str, list[str]]:
    template = (REFERENCES / f"{kind}-artifact.html").read_text()
    page = re.sub(r"\A\s*<!--.*?-->\s*", "", template, count=1, flags=re.S)
    builder = {"plan": plan_slots, "qa": qa_slots, "generic": generic_slots}[kind]
    slots, keep = builder(data, markdown)
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
        page, missing = render(args.kind, data, markdown)
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
