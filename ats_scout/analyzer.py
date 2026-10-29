"""ATS analysis engine: section detection, rule-based scoring and job-description matching.

100% offline and deterministic. No API keys, no network, no AI model calls.
The score is an *estimate* based on common ATS parsing behaviour; real systems differ.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from . import lexicon as L
from .extract import Extracted, extract
from .text_utils import count_words, fold, phrase_regex, stem, words

# --------------------------------------------------------------------------- data classes


@dataclass
class Check:
    ok: bool
    points: int
    label: str          # what is checked
    advice: str = ""    # shown when the check fails


@dataclass
class SectionScore:
    key: str
    name: str
    weight: float
    score: int
    found: bool
    checks: list = field(default_factory=list)


@dataclass
class Issue:
    severity: str       # "critical" | "warning" | "info"
    title: str
    detail: str
    fix: str
    penalty: int = 0


@dataclass
class KeywordHit:
    keyword: str
    weight: float
    count: int = 0


@dataclass
class MatchResult:
    score: int
    matched: list
    missing: list
    stuffed: list
    title_line: str
    title_overlap: bool
    verdict: str


@dataclass
class Analysis:
    extracted: Extracted
    ats_score: int
    sections: list
    issues: list
    detected_sections: list
    header_lines: list
    section_lines: list           # [(key|None, original_title, [lines])]
    match: MatchResult | None
    combined_score: int | None
    word_count: int
    verdict: str


# --------------------------------------------------------------------------- section splitting

_BULLET_RE = re.compile(rf"^\s*[{re.escape(L.BULLET_CHARS)}]\s*")
_ALIAS_TO_KEY = {alias: key for key, aliases in L.SECTION_ALIASES.items() for alias in aliases}


def heading_key(line: str) -> str | None:
    f = re.sub(r"[^a-z0-9& ]", " ", fold(line))
    f = re.sub(r"\s+", " ", f).strip().replace("&", "and")
    if not f or len(f.split()) > 5:
        return None
    return _ALIAS_TO_KEY.get(f)


def split_sections(text: str):
    """Return (header_lines, [(key|None, title, lines)])."""
    header: list[str] = []
    sections: list[list] = []
    current = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        key = heading_key(line)
        if key:
            current = [key, line.strip(), []]
            sections.append(current)
        elif current is None:
            header.append(line.strip())
        else:
            current[2].append(line.strip())
    header, sections = _promote_implicit_summary(header, sections)
    return header, [tuple(s) for s in sections]


IMPLICIT_SUMMARY_TITLE = "(no heading)"


def _promote_implicit_summary(header: list[str], sections: list):
    """Many designer CVs put a short self-introduction right under the name, with no 'Summary' heading.
    A real ATS still reads it as the summary, so treat the closing prose paragraph of the header as one."""
    if not header or any(s[0] == "summary" for s in sections):
        return header, sections
    take = 0
    for line in reversed(header):
        words = len(line.split())
        prose = words >= 5 or (words >= 3 and line.rstrip().endswith((".", "!", "?")) and not line.isupper())
        if not prose or EMAIL_RE.search(line) or URL_RE.search(line) or PHONE_RE.search(line):
            break
        take += 1
    if take < 2:
        return header, sections
    body = header[-take:]
    if sum(len(x.split()) for x in body) < 20:
        return header, sections
    return header[:-take], [["summary", IMPLICIT_SUMMARY_TITLE, body]] + [list(x) for x in sections]


# --------------------------------------------------------------------------- regexes

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)")
URL_RE = re.compile(r"(?:https?://|www\.)\S+|(?:linkedin\.com|github\.com|gitlab\.com|behance\.net)/\S+", re.I)
MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik)[a-z]*\.?"
DATE_RANGE_RE = re.compile(
    rf"((?:{MONTHS}\s*)?(?:19|20)\d{{2}}|\d{{1,2}}[/.]\d{{4}})\s*(?:-|–|—|to|/|ile)\s*"
    rf"((?:{MONTHS}\s*)?(?:19|20)\d{{2}}|\d{{1,2}}[/.]\d{{4}}|present|current|now|halen|devam|gunumuz|bugun)",
    re.I,
)
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|x|k|m|\+)?|\$|€|₺|%")
FIRST_PERSON_RE = re.compile(r"\b(i am|i'm|i have|my|ben|benim)\b", re.I)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿]")
DECOR_SYMBOLS = "★☆✪✯✰◐◑◒◓◔◕❖✦✧➤➢➔➜➨✗✘☎☏✆✉✈☑☐⚫⚪"


BAR_GLYPHS_RE = re.compile(rf"[{re.escape('★☆●○◐◑■□▪▫◆◇')}]{{3,}}|\*{{3,}}")
SHORT_LEVEL_RE = re.compile(r"\b\d{2,3}\s*%|\b[1-5]\s*/\s*5\b|\b[1-9]\s*/\s*10\b")


RESULT_RE = re.compile(r"\b(?:by|from|to|of|than|over|up|ile|kadar)\s+\d", re.I)   # "cut costs by 40%" is a result, not a skill bar


def has_skill_bars(text: str) -> bool:
    """Skill level graphics: glyph bars anywhere, or short 'Python 80%' style lines."""
    for line in text.splitlines():
        if BAR_GLYPHS_RE.search(line):
            return True
        if count_words(line) <= 5 and SHORT_LEVEL_RE.search(line) and not _is_bullet(line) and not RESULT_RE.search(line):
            return True
    return False


def _is_bullet(line: str) -> bool:
    return bool(_BULLET_RE.match(line)) and len(line.strip()) > 2


def _strip_bullet(line: str) -> str:
    return _BULLET_RE.sub("", line).strip()


def _first_word(line: str) -> str:
    w = words(_strip_bullet(line))
    return w[0] if w else ""


def _is_action_verb(word: str) -> bool:
    if not word:
        return False
    if word in L.ACTION_VERBS_EN or (word.endswith("ed") and len(word) > 4):
        return True
    return any(word.startswith(s) for s in L.ACTION_VERB_STEMS_TR)


# --------------------------------------------------------------------------- section scorers


def _score(checks: list[Check]) -> int:
    total = sum(c.points for c in checks)
    got = sum(c.points for c in checks if c.ok)
    return round(100 * got / total) if total else 0


def _score_contact(header: list[str], full_text: str, ex: Extracted) -> SectionScore:
    head_text = "\n".join(header[:12])
    scan = head_text + "\n" + ex.header_footer_text
    first = header[0] if header else ""
    name_ok = bool(first) and 1 < len(first.split()) <= 5 and not re.search(r"[\d@:/]", first)
    has_email = bool(EMAIL_RE.search(scan)) or bool(EMAIL_RE.search(full_text[:800]))
    has_phone = bool(PHONE_RE.search(scan)) or bool(PHONE_RE.search(full_text[:800]))
    has_link = bool(URL_RE.search(scan)) or bool(URL_RE.search(full_text[:1200])) or ex.link_count > 0
    in_header_only = bool(EMAIL_RE.search(ex.header_footer_text)) and not EMAIL_RE.search(head_text)
    checks = [
        Check(name_ok, 15, "Your name is the first line", "Put your full name alone on the very first line."),
        Check(has_email, 25, "Email address found", "Add a plain-text email address near the top."),
        Check(has_phone, 25, "Phone number found", "Add a phone number with country code, e.g. +90 5XX XXX XX XX."),
        Check(has_link, 20, "LinkedIn / GitHub / portfolio link found",
              "Add your LinkedIn or GitHub URL as visible text (not only a clickable icon)."),
        Check(not in_header_only, 15, "Contact info is in the page body, not Word header/footer",
              "Move contact details out of the Word header/footer; many ATS skip those areas."),
    ]
    return SectionScore("contact", "Contact", 0.10, _score(checks), bool(header), checks)


def _score_summary(lines: list[str], found: bool) -> SectionScore:
    text = " ".join(lines)
    n = count_words(text)
    checks = [
        Check(found, 40, "Summary / Profile section exists", "Add a 2-4 sentence 'Summary' with your role, years of experience and top skills."),
        Check(found and 25 <= n <= 110, 30, "Length is 25-110 words",
              "Keep the summary between 25 and 110 words."),
        Check(found and bool(re.search(r"\d+\+?\s*(years?|yrs?|yil)\b|yillara dayanan|yillik|uzun yillar|ogrenci|yeni mezun|student|graduate", fold(text))), 15,
              "Mentions years of experience", "Mention how many years of experience you have (or 'student'/'new graduate')."),
        Check(found and len(FIRST_PERSON_RE.findall(text)) <= 1, 15, "Avoids first-person phrasing",
              "Drop 'I am' / 'My' and start with your title: 'Backend developer with ...'."),
    ]
    return SectionScore("summary", "Summary", 0.08, _score(checks) if found else 0, found, checks)


def _score_experience(lines: list[str], found: bool) -> SectionScore:
    bullets = [_strip_bullet(l) for l in lines if _is_bullet(l)]
    if not bullets:  # PDFs often lose bullet glyphs; fall back to sentence-like lines
        bullets = [l for l in lines if count_words(l) >= 6 and not DATE_RANGE_RE.search(l)]
    nb = len(bullets)
    action = sum(1 for b in bullets if _is_action_verb(_first_word(b)))
    quant = sum(1 for b in bullets if NUMBER_RE.search(b))
    avg = sum(count_words(b) for b in bullets) / nb if nb else 0
    dates = sum(1 for l in lines if DATE_RANGE_RE.search(l))
    checks = [
        Check(found, 20, "Experience section exists", "Add a section titled exactly 'Experience' or 'Work Experience'."),
        Check(dates >= 1, 20, "Employment dates are readable (e.g. Jan 2022 - Present)",
              "Write dates like 'Jan 2022 - Present' next to every role."),
        Check(nb >= 3, 15, "At least 3 achievement bullets", "Describe each role with 3-5 short bullets."),
        Check(nb > 0 and action / nb >= 0.6, 15, "Most bullets start with an action verb",
              "Start bullets with verbs: Built, Led, Reduced, Geliştirdim, Yönettim..."),
        Check(nb > 0 and quant / nb >= 0.3, 20, "Achievements include numbers",
              "Add measurable results to at least a third of bullets: '%', time saved, users, revenue."),
        Check(8 <= avg <= 28, 10, "Bullets are 8-28 words on average",
              "Keep each bullet to one or two lines (8-28 words)."),
    ]
    return SectionScore("experience", "Experience", 0.25, _score(checks) if found else 0, found, checks)


def _score_education(lines: list[str], found: bool) -> SectionScore:
    t = fold(" ".join(lines))
    checks = [
        Check(found, 30, "Education section exists", "Add an 'Education' section."),
        Check(any(w in t for w in L.DEGREE_WORDS), 30, "Degree is named", "Name your degree (e.g. 'B.Sc. Computer Engineering' / 'Lisans')."),
        Check(bool(re.search(r"(19|20)\d{2}", t)), 20, "Graduation year or dates present", "Add the graduation year (or expected year)."),
        Check(any(w in t for w in L.INSTITUTION_WORDS), 20, "Institution is named", "Write the full school name (e.g. 'Selçuk University')."),
    ]
    return SectionScore("education", "Education", 0.10, _score(checks) if found else 0, found, checks)


def _score_skills(lines: list[str], found: bool) -> SectionScore:
    text = "\n".join(lines)
    items = [x for x in re.split(r"[,;|•·\n]+", text) if x.strip() and len(x.strip()) <= 40]
    bars = has_skill_bars(text)
    grouped = sum(1 for l in lines if re.match(r"^[^:]{2,30}:\s*\S", l)) >= 2
    checks = [
        Check(found, 30, "Skills section exists", "Add a 'Skills' section with plain-text keywords."),
        Check(len(items) >= 6, 30, "At least 6 skills listed", "List at least 6-10 relevant tools/skills."),
        Check(len(items) >= 10, 10, "10+ skills listed", "Aim for 10-20 role-relevant skills."),
        Check(not bars, 20, "No skill bars / star ratings / percentages",
              "Replace '★★★★☆' or 'Python 80%' with plain text: just 'Python'."),
        Check(grouped, 10, "Skills are grouped (e.g. 'Languages: Python, Go')",
              "Group skills by category: 'Languages: ...', 'Tools: ...'."),
    ]
    return SectionScore("skills", "Skills", 0.17, _score(checks) if found else 0, found, checks)


# --------------------------------------------------------------------------- format issues


def _format_issues(ex: Extracted, header: list[str], found_keys: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    wc = count_words(ex.text)
    plain = ex.text

    if wc < 60:
        issues.append(Issue("critical", "No readable text layer",
                            "Almost no text could be extracted. The CV may be a scanned image or exported as pictures. "
                            "An ATS would see an empty document.",
                            "Re-export from Word/Google Docs as a text-based PDF (select-able text), not a scan or screenshot.", 60))
    if ex.images:
        sev = "warning"
        issues.append(Issue(sev, f"{ex.images} image(s) detected",
                            "ATS parsers ignore images. Text placed inside images is invisible, and photos can add bias risk "
                            "(many US/UK/EU employers prefer no photo).",
                            "Remove the photo, logos and decorative graphics. Keep every important word as real text.",
                            15 if ex.images > 3 else 10))
    if ex.tables:
        issues.append(Issue("warning", f"{ex.tables} table(s) detected",
                            "Tables are often read cell by cell in the wrong order, mixing dates, titles and companies.",
                            "Use plain paragraphs and line breaks instead of tables.", 12))
    if ex.multi_column:
        issues.append(Issue("critical", "Multi-column layout detected",
                            "Text from side-by-side columns can be merged line by line, so your skills may end up in the middle of a job description.",
                            "Switch to a single-column layout (the fixed PDF from this app does this for you).", 15))
    if ex.textboxes:
        issues.append(Issue("warning", f"{ex.textboxes} text box(es) detected",
                            "Text boxes are skipped or read last by many ATS.",
                            "Move the content into normal paragraphs.", 10))
    if EMAIL_RE.search(ex.header_footer_text) or PHONE_RE.search(ex.header_footer_text):
        issues.append(Issue("warning", "Contact info is inside the Word header/footer",
                            "Several ATS ignore headers and footers entirely.",
                            "Put name, email and phone at the top of the page body.", 8))
    if ex.private_use_chars >= 2:
        issues.append(Issue("warning", f"Icon-font symbols found ({ex.private_use_chars})",
                            "Icons (phone, mail, LinkedIn) come from special fonts and turn into empty boxes or garbage in an ATS.",
                            "Delete the icons and write 'Email:', 'Phone:' etc. as text.", 6))

    deco = sum(plain.count(c) for c in L.SYMBOL_CHARS if c in DECOR_SYMBOLS or c in "★☆")
    emoji = len(EMOJI_RE.findall(plain))
    if has_skill_bars(plain):
        issues.append(Issue("warning", "Skill rating bars / stars / percentages",
                            "Visual skill levels (★★★★☆, dots, 'Python 80%') mean nothing to an ATS, can pollute keyword matching, "
                            "and recruiters distrust self-rated percentages.",
                            "List skills as plain words. Show level through experience bullets instead.", 8))
    elif deco + emoji >= 3:
        issues.append(Issue("warning", f"Decorative symbols / emoji found ({deco + emoji})",
                            "Non-standard glyphs may be dropped or turned into '?' by parsers.",
                            "Use only standard bullets (•) and plain punctuation.", 5))

    nonstd = [l for l in ex.text.splitlines() if l.strip().isupper() and 2 <= len(l.split()) <= 4
              and heading_key(l) is None and not re.search(r"\d|@", l)]
    if len(nonstd) >= 2 and len(found_keys) < 4:
        issues.append(Issue("info", "Creative section titles",
                            f"Headings like '{nonstd[0].title()}' are not standard, so the ATS may fail to classify them.",
                            "Use standard titles: Summary, Experience, Education, Skills, Projects, Certifications.", 4))

    if len(ex.font_families) > 3:
        issues.append(Issue("info", f"{len(ex.font_families)} different fonts",
                            "Many fonts hint at a design-heavy file and can cause encoding trouble.",
                            "Use one font family (Arial, Calibri, Times New Roman).", 3))

    if ex.pages > 2:
        issues.append(Issue("warning", f"{ex.pages} pages long",
                            "Long resumes get skimmed (or truncated). 1 page for <10 years of experience, 2 pages maximum otherwise.",
                            "Cut older or less relevant roles and shorten bullets.", 8 if ex.pages > 3 else 5))
    if 60 <= wc < 150:
        issues.append(Issue("warning", "Very little content", f"Only about {wc} words found.",
                            "Add detail: responsibilities, tools and measurable results.", 10))
    if wc > 1100:
        issues.append(Issue("info", "Very wordy", f"About {wc} words.", "Aim for 400-800 words.", 3))

    fmts = set()
    t = plain
    if re.search(rf"\b{MONTHS}\s*(19|20)\d{{2}}", t, re.I):
        fmts.add("Mon YYYY")
    if re.search(r"\b\d{1,2}[/.]\d{4}\b", t):
        fmts.add("MM/YYYY")
    if re.search(r"\b\d{1,2}[/.]\d{1,2}[/.]\d{4}\b", t):
        fmts.add("DD/MM/YYYY")
    if len(fmts) >= 2:
        issues.append(Issue("info", "Mixed date formats", f"Found: {', '.join(sorted(fmts))}.",
                            "Use one date format everywhere, e.g. 'Jan 2022 - Mar 2024'.", 3))
    return issues


# --------------------------------------------------------------------------- job matching

_SYN: dict[str, set[str]] = {}
for _g in L.SYNONYM_GROUPS:
    for _t in _g:
        _SYN.setdefault(_t, set()).update(_g)


def _split_candidate_terms(jd: str) -> dict[str, float]:
    f = fold(jd)
    toks = words(jd)
    freq = Counter(t for t in toks if t not in L.STOPWORDS_EN and t not in L.STOPWORDS_TR and len(t) >= 3 and not t.isdigit())
    weights: dict[str, float] = {}

    for term in L.SKILLS:
        n = len(phrase_regex(term).findall(f))
        if n:
            weights[term] = 3.0 + min(n - 1, 3) * 0.3

    # capitalised / tech-looking single words that are not at a sentence start
    for m in re.finditer(r"(?<![.!?\n]\s)(?<!^)\b([A-Z][A-Za-z0-9+#.]{2,}|[a-z]+[A-Z][A-Za-z0-9]+)\b", jd):
        w = fold(m.group(1)).strip(".")
        if w and w not in L.STOPWORDS_EN and w not in L.STOPWORDS_TR and w not in weights and len(w) >= 3:
            weights[w] = max(weights.get(w, 0), 1.6)

    for w, n in freq.items():
        if w in weights:
            continue
        if n >= 2:
            weights[w] = min(1.5 + 0.25 * (n - 2), 3.0)

    # required / preferred zones
    zone = "normal"
    mult: dict[str, float] = {}
    for line in f.splitlines():
        s = line.strip()
        if not s:
            continue
        if any(m in s for m in L.PREFERRED_MARKERS) and len(s) < 80:
            zone = "preferred"
        elif any(m in s for m in L.REQUIRED_MARKERS) and len(s) < 80:
            zone = "required"
        for term in weights:
            if term in s and phrase_regex(term).search(s):
                factor = 1.3 if zone == "required" else 0.7 if zone == "preferred" else 1.0
                mult[term] = max(mult.get(term, 0), factor)
    for term, fac in mult.items():
        weights[term] *= fac
    return weights


def _term_variants(term: str) -> list[str]:
    v = {term} | _SYN.get(term, set())
    return sorted(v)


def _count_in(cv_folded: str, term: str, lexical: bool) -> int:
    total = 0
    for variant in _term_variants(term):
        if " " in variant or any(ch in variant for ch in "+#./") or lexical or len(variant) <= 4:
            total += len(phrase_regex(variant).findall(cv_folded))
        else:
            st = stem(variant)
            total += len(re.findall(rf"(?<![a-z0-9]){re.escape(st)}[a-z]*", cv_folded))
    return total


def match_job(cv_text: str, jd: str) -> MatchResult:
    cv_f = fold(cv_text)
    weights = _split_candidate_terms(jd)
    top = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))[:35]

    matched: list[KeywordHit] = []
    missing: list[KeywordHit] = []
    stuffed: list[KeywordHit] = []
    got = tot = 0.0
    for term, w in top:
        c = _count_in(cv_f, term, term in L.SKILLS)
        hit = KeywordHit(term, round(w, 2), c)
        tot += w
        if c:
            got += w
            matched.append(hit)
            if c >= 9:
                stuffed.append(hit)
        else:
            missing.append(hit)

    score = round(100 * got / tot) if tot else 0

    title_line = next((l.strip() for l in jd.splitlines() if l.strip()), "")
    if len(title_line.split()) > 10:
        title_line = ""
    tw = [w for w in words(title_line) if w not in L.STOPWORDS_EN and w not in L.STOPWORDS_TR and len(w) > 2]
    head_f = fold("\n".join(cv_text.splitlines()[:10]))
    title_overlap = bool(tw) and sum(1 for w in tw if stem(w)[:5] in head_f) >= max(1, len(tw) // 2)

    if not top:
        verdict = "Not enough text in the job description to extract keywords."
    elif score >= 75:
        verdict = "Strong match: your CV covers most of what this job asks for."
    elif score >= 55:
        verdict = "Moderate match: you pass the basics but are missing several keywords."
    else:
        verdict = "Weak match: many of the job's keywords are not in your CV. An ATS would likely rank you low."
    return MatchResult(score, matched, missing, stuffed, title_line, title_overlap, verdict)


# --------------------------------------------------------------------------- orchestration

WEIGHTS = {"format": 0.30, "contact": 0.10, "summary": 0.08, "experience": 0.25, "education": 0.10, "skills": 0.17}


def analyze_text_file(path: str, job_description: str = "") -> Analysis:
    return analyze(extract(path), job_description)


def analyze(ex: Extracted, job_description: str = "") -> Analysis:
    header, sections = split_sections(ex.text)
    by_key: dict[str, list[str]] = {}
    for key, _title, lines in sections:
        by_key.setdefault(key, []).extend(lines)
    found = set(by_key)

    issues = _format_issues(ex, header, found)
    fmt_penalty = sum(i.penalty for i in issues)
    fmt_score = max(0, 100 - fmt_penalty)
    fmt_section = SectionScore("format", "Formatting & Parseability", WEIGHTS["format"], fmt_score, True, [])
    for i in sorted(issues, key=lambda x: -x.penalty):
        fmt_section.checks.append(Check(False, i.penalty, i.title, i.fix))
    if not issues:
        fmt_section.checks.append(Check(True, 1, "Clean single-column text layout, no ATS blockers found", ""))

    contact = _score_contact(header, ex.text, ex)
    summary = _score_summary(by_key.get("summary", []), "summary" in found)
    if any(k == "summary" and t == IMPLICIT_SUMMARY_TITLE for k, t, _ in sections):
        summary.checks.append(Check(False, 1, "Summary has its own heading",
                                    "Put a heading such as 'Summary' or 'Profile' above this paragraph so every ATS recognises it."))
        summary.score = _score(summary.checks)
    experience = _score_experience(by_key.get("experience", []), "experience" in found)
    education = _score_education(by_key.get("education", []), "education" in found)
    skills = _score_skills(by_key.get("skills", []), "skills" in found)
    for s in (contact, summary, experience, education, skills):
        s.weight = WEIGHTS[s.key]
    sections_scored = [fmt_section, contact, summary, experience, education, skills]

    ats = round(sum(s.score * s.weight for s in sections_scored))
    if "experience" not in found:
        ats = min(ats, 60)
    if fmt_score <= 40:
        ats = min(ats, 55)

    match = match_job(ex.text, job_description) if job_description.strip() else None
    combined = round(0.35 * ats + 0.65 * match.score) if match and match.matched + match.missing else None

    if ats >= 80:
        verdict = "ATS-friendly: this CV should parse cleanly."
    elif ats >= 60:
        verdict = "Mostly readable, but some issues can hurt parsing. Fix the warnings below."
    else:
        verdict = "Risky: an ATS will likely misread or lose parts of this CV."

    sev_order = {"critical": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: (sev_order[i.severity], -i.penalty))

    return Analysis(
        extracted=ex, ats_score=ats, sections=sections_scored, issues=issues,
        detected_sections=[(k, t) for k, t, _ in sections], header_lines=header,
        section_lines=sections, match=match, combined_score=combined,
        word_count=count_words(ex.text), verdict=verdict,
    )


def suggestions(a: Analysis, limit: int = 8) -> list[str]:
    """Top prioritised fixes: format issues first, then failed section checks by points."""
    out = [f"{i.title}: {i.fix}" for i in a.issues if i.severity != "info"]
    pool = []
    for s in a.sections:
        if s.key == "format":
            continue
        for c in s.checks:
            if not c.ok and c.advice:
                pool.append((c.points * s.weight, f"[{s.name}] {c.advice}"))
    out += [t for _, t in sorted(pool, reverse=True)]
    out += [f"{i.title}: {i.fix}" for i in a.issues if i.severity == "info"]
    if a.match and a.match.missing:
        kws = ", ".join(k.keyword for k in a.match.missing[:6])
        out.append(f"[Job match] If you genuinely have them, add: {kws}")
    return out[:limit]


if __name__ == "__main__":  # quick CLI: python -m ats_scout.analyzer cv.pdf [jd.txt]
    import sys

    cv = sys.argv[1]
    jd = open(sys.argv[2], encoding="utf-8").read() if len(sys.argv) > 2 else ""
    res = analyze_text_file(cv, jd)
    print(f"ATS score: {res.ats_score}  ({res.verdict})")
    for s in res.sections:
        print(f"  {s.name:28s} {s.score:3d}")
    for i in res.issues:
        print(f"  [{i.severity}] {i.title}")
    if res.match:
        print(f"Match: {res.match.score}  missing: {[k.keyword for k in res.match.missing]}")
