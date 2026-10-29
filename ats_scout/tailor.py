"""Tailor a CV to one job posting, offline and honestly.

What it does (all rule-based, nothing is invented):
  1. Wording: if your CV says "JS" and the job says "JavaScript" (or K8s / Kubernetes, Postgres /
     PostgreSQL, Front-End / Frontend ...), it uses the job's wording, because many ATS match exact text.
  2. Skills lists: job-relevant skills move to the front, duplicates are removed.
  3. Overused keywords: if a term appears far too often, extra mentions are varied (when a safe
     alternative exists) and you are told about the rest.
  4. Keywords YOU confirm: skills from the posting that you tick as "I really have this" are added to
     your Skills section and to one short sentence at the end of your Summary.
It never adds a skill you did not confirm.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .analyzer import MatchResult
from .layout import Block, Run
from .text_utils import fold

# --------------------------------------------------------------------------- alias groups
# Pure spelling / abbreviation variants of the SAME thing (never "MySQL = SQL" style relations).
ALIAS_GROUPS: list[list[str]] = [
    ["JavaScript", "JS"],
    ["TypeScript", "TS"],
    ["Kubernetes", "K8s"],
    ["Machine Learning", "ML"],
    ["Artificial Intelligence", "AI"],
    ["PostgreSQL", "Postgres"],
    ["Node.js", "NodeJS", "Node JS"],
    ["React.js", "ReactJS", "React"],
    ["Vue.js", "VueJS", "Vue"],
    ["Next.js", "NextJS"],
    ["CI/CD", "CICD"],
    ["Amazon Web Services", "AWS"],
    ["Google Cloud Platform", "GCP"],
    ["C#", "CSharp"],
    ["REST API", "RESTful API", "REST APIs", "RESTful APIs"],
    ["Natural Language Processing", "NLP"],
    ["Object-Oriented Programming", "OOP"],
    ["Search Engine Optimization", "SEO"],
    ["Front-End", "Frontend", "Front End"],
    ["Back-End", "Backend", "Back End"],
    ["Full-Stack", "Fullstack", "Full Stack"],
    ["E-commerce", "Ecommerce"],
    ["MongoDB", "Mongo DB"],
    ["Tailwind CSS", "Tailwind"],
    ["Power BI", "PowerBI"],
]
# extra exclusions so that a short form never matches inside a longer, different name
_PATTERNS = {
    "React": r"React(?!\.js|JS|\.JS|\s+Native|-Native)",
    "Vue": r"Vue(?!\.js|JS|\.JS)",
    "Node JS": r"Node\s+JS",
    "Tailwind": r"Tailwind(?!\s*CSS)",
    "React.js": r"React\.js",
}
_ACRONYMS = {"aws", "gcp", "sql", "html", "css", "api", "ci/cd", "etl", "nlp", "seo", "crm", "erp", "ux", "ui", "oop",
             "tdd", "llm", "ios", "b2b", "sap", "plc", "ml", "ai", "php", "soc", "ide", "sdk", "siem", "owasp", "nosql",
             "ui/ux", "vba", "xml", "json", "jwt", "oauth", "ssl", "tcp/ip", "vpn", "ocr"}
_SENT_END = ".!?"


def _form_re(form: str) -> re.Pattern:
    core = _PATTERNS.get(form) or re.escape(form).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![A-Za-z0-9]){core}(?![A-Za-z0-9])", 0 if len(form) <= 3 else re.I)


_FORM_RES = {f: _form_re(f) for g in ALIAS_GROUPS for f in g}


def display_form(term: str, jd: str) -> str:
    """Nice spelling of a (folded, lower-case) keyword: use the job posting's own spelling when found."""
    m = re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", jd, re.I)
    snippet = m.group(0) if m else term
    if term in _ACRONYMS:
        return term.upper()
    if snippet == snippet.lower():
        return " ".join(w[:1].upper() + w[1:] for w in snippet.split(" "))
    return snippet


def suggestable_keywords(match: MatchResult | None, jd: str, limit: int = 30) -> list[tuple[str, str]]:
    """[(display, term)] of missing keywords, strongest first."""
    if not match:
        return []
    out = []
    for hit in sorted(match.missing, key=lambda h: -h.weight)[:limit]:
        out.append((display_form(hit.keyword, jd), hit.keyword))
    return out


@dataclass
class TailorRequest:
    jd: str
    match: MatchResult
    confirmed: list = field(default_factory=list)    # display strings the user says they really have


# --------------------------------------------------------------------------- steps


def _all_runs(blocks, skip_headings=True):
    for b in blocks:
        if skip_headings and b.heading:
            continue
        yield from b.runs


def _align_wording(blocks: list[Block], jd: str, notes: list[str]) -> None:
    for group in ALIAS_GROUPS:
        in_jd = {f: len(_FORM_RES[f].findall(jd)) for f in group}
        wanted = [f for f in group if in_jd[f]]
        if not wanted:
            continue
        cv_text = "\n".join(r.text for r in _all_runs(blocks))
        if any(_FORM_RES[f].search(cv_text) for f in wanted):
            continue                                   # your CV already uses the job's wording
        target = max(wanted, key=lambda f: (in_jd[f], -group.index(f)))
        changed = 0
        used = []
        for f in group:
            if f == target:
                continue
            rx = _FORM_RES[f]
            for r in _all_runs(blocks):
                r.text, n = rx.subn(target, r.text)
                if n:
                    changed += n
                    used.append(f)
        if changed:
            notes.append(f"Wrote “{target}” (the job's wording) instead of “{', '.join(sorted(set(used)))}” "
                         f"in {changed} place{'s' if changed > 1 else ''}.")


_SEP_RE = re.compile(r"\s*([,;|•·])\s*")


def _relevant_checker(req: TailorRequest):
    terms = {h.keyword for h in req.match.matched} | {h.keyword for h in req.match.missing}
    forms = [f for g in ALIAS_GROUPS if any(_FORM_RES[f].search(req.jd) for f in g) for f in g]

    def relevant(item: str) -> bool:
        f = fold(item).strip()
        if not f:
            return False
        if f in terms:
            return True
        if any(len(t) >= 3 and re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", f) for t in terms):
            return True
        return any(_FORM_RES[x].search(item) for x in forms)

    return relevant


def _tidy_skill_lists(blocks: list[Block], req: TailorRequest, notes: list[str]) -> None:
    relevant = _relevant_checker(req)
    moved: list[str] = []
    dupes: list[str] = []
    for b in blocks:
        if b.heading or b.section != "skills":
            continue
        # the run that holds the list (the longest run with 2+ separators)
        cands = [r for r in b.runs if len(_SEP_RE.findall(r.text)) >= 2]
        if not cands:
            continue
        run = max(cands, key=lambda r: len(r.text))
        text = run.text
        trail = text[len(text.rstrip()):]
        body = text.rstrip()
        label = ""
        m = re.match(r"^(\s*[^:,;|•·]{1,32}:\s*)(.*)$", body, re.S)
        if m:
            label, body = m.group(1), m.group(2)
        seps = _SEP_RE.findall(body)
        sep = seps[0]
        items = [i.strip() for i in _SEP_RE.split(body)[::2] if i.strip()]
        seen, uniq = set(), []
        for it in items:
            k = it.lower()
            if k in seen:
                dupes.append(it)
                continue
            seen.add(k)
            uniq.append(it)
        front = [i for i in uniq if relevant(i)]
        rest = [i for i in uniq if not relevant(i)]
        new_items = front + rest
        if front and rest and new_items != uniq:
            moved.extend(front)
        joiner = " | " if sep == "|" else f"{sep} " if sep in ",;" else f" {sep} "
        new_text = label + joiner.join(new_items) + trail
        if new_text != text:
            run.text = new_text
    if moved:
        notes.append("Moved job-relevant skills to the front of your skills lists: "
                     + ", ".join(dict.fromkeys(moved[:8])) + ("…" if len(moved) > 8 else "") + ".")
    if dupes:
        notes.append("Removed duplicate skills: " + ", ".join(dict.fromkeys(dupes)) + ".")


def _reduce_overuse(blocks: list[Block], req: TailorRequest, notes: list[str], keep: int = 6) -> None:
    for hit in req.match.stuffed:
        term = hit.keyword
        rx = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.I)
        total = sum(len(rx.findall(r.text)) for r in _all_runs(blocks))
        if total <= keep:
            continue
        group = next((g for g in ALIAS_GROUPS if any(fold(f) == term for f in g)), None)
        if not group:
            notes.append(f"“{term}” appears {total} times. That can look like keyword stuffing; "
                         f"consider trimming a few mentions by hand.")
            continue
        alts = [f for f in group if fold(f) != term]
        seen = [0]
        replaced = [0]

        def sub(m):
            seen[0] += 1
            if seen[0] <= keep:
                return m.group(0)
            replaced[0] += 1
            return alts[replaced[0] % len(alts)]

        for r in _all_runs(blocks):
            r.text = rx.sub(sub, r.text)
        if replaced[0]:
            notes.append(f"“{term}” was used {total} times; varied the wording in {replaced[0]} places "
                         f"(e.g. “{alts[0]}”).")


def _join_and(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _add_confirmed(blocks: list[Block], confirmed: list[str], notes: list[str]) -> None:
    kws = [k.strip() for k in confirmed if k and k.strip()]
    if not kws:
        return
    # ---- skills section
    skill_blocks = [b for b in blocks if b.section == "skills" and not b.heading]
    done = False
    for b in reversed(skill_blocks):
        if b.bullet:
            continue
        cands = [r for r in b.runs if len(_SEP_RE.findall(r.text)) >= 1 or ":" in r.text]
        if cands:
            run = b.runs[-1]
            body = run.text.rstrip()
            trail = run.text[len(body):]
            sep = ", "
            m = _SEP_RE.search(body)
            if m and m.group(1) in ";|":
                sep = " | " if m.group(1) == "|" else "; "
            run.text = body.rstrip(",;|") + sep + sep.join(kws) + trail
            done = True
            break
    if not done:
        if skill_blocks:
            base = skill_blocks[-1]
            blocks.insert(blocks.index(base) + 1, Block(
                [Run("Additional: ", bold=True), Run(", ".join(kws))], size=base.size, leading=base.leading,
                align="left", space_before=base.space_before, section="skills"))
            done = True
        else:
            head = next((b for b in blocks if b.heading), None)
            body = next((b for b in blocks if not b.heading and b.section), None)
            if head and body:
                blocks.append(Block([Run("Skills", bold=True)], size=head.size, leading=head.leading,
                                    space_before=head.space_before, rule_after=head.rule_after,
                                    rule_color=head.rule_color, heading=True, section="skills"))
                blocks.append(Block([Run(", ".join(kws))], size=body.size, leading=body.leading, section="skills"))
                done = True
    if done:
        notes.append("Added to your Skills section (you confirmed these): " + ", ".join(kws) + ".")
    # ---- one sentence in the summary
    summary = [b for b in blocks if b.section == "summary" and not b.heading and not b.bullet]
    if summary:
        b = summary[-1]
        last = b.runs[-1]
        body = last.text.rstrip()
        if body and body[-1] not in _SENT_END:
            body += "."
        last.text = f"{body} Also experienced with {_join_and(kws[:6])}."
        notes.append("Added one sentence to your Summary mentioning the same skills.")


def apply_tailoring(blocks: list[Block], req: TailorRequest) -> list[str]:
    """Edit ``blocks`` in place for the given job. Returns human-readable notes about what changed."""
    notes: list[str] = []
    if not req.match:
        return notes
    _align_wording(blocks, req.jd, notes)
    _tidy_skill_lists(blocks, req, notes)
    _reduce_overuse(blocks, req, notes)
    _add_confirmed(blocks, req.confirmed, notes)
    if req.match.title_line and not req.match.title_overlap:
        notes.append(f"Your header does not mention the job title “{req.match.title_line}”. If it is true for you, "
                     f"put a matching title under your name (not changed automatically).")
    if not notes:
        notes.append("Nothing needed changing for this job: your wording already matches and nothing is overused.")
    return notes
