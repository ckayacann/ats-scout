"""Generate two sample CVs (one clean, one ATS-hostile) for tests and demos."""
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

GOOD = """Jane Doe
Konya, Turkey | jane.doe@example.com | +90 555 123 45 67 | github.com/janedoe | linkedin.com/in/janedoe
SUMMARY
Backend developer with 4 years of experience building REST APIs in Python and Django. Focused on clean code, testing and cloud deployment on AWS.
EXPERIENCE
Backend Developer - Acme Software, Istanbul
Jan 2022 - Present
- Built 12 REST API endpoints with Django and PostgreSQL serving 50,000 daily users
- Reduced API response time by 40% by adding Redis caching
- Automated CI/CD with GitHub Actions and Docker, cutting release time from 2 hours to 15 minutes
- Mentored 3 junior developers during code review sessions
Junior Developer - Beta Labs, Ankara
Jun 2020 - Dec 2021
- Developed internal dashboards in Python and Flask used by 30 employees
- Wrote unit testing suites with pytest reaching 85% coverage
- Migrated 5 legacy services to Docker containers
EDUCATION
B.Sc. Computer Engineering, Selcuk University, 2016 - 2020
SKILLS
Languages: Python, JavaScript, SQL
Tools: Docker, Git, GitHub Actions, Linux, AWS
Frameworks: Django, Flask, FastAPI, React
PROJECTS
ATS Scout - offline resume analyzer built with Python
"""

BAD_LEFT = ["Contact", "jane.doe@example.com", "+90 555 123 45 67", "Skills",
            "Python  *****", "Django  ****", "SQL  ***", "Docker  **", "Teamwork  80%", "Excel  70%",
            "Languages", "English  ****", "Turkish  *****"]
BAD_RIGHT = ["JANE DOE", "My Journey", "I am a passionate developer who loves coding and learning new things every day.",
             "What I Did", "Developer at Acme (2022 - now). Worked on many things.",
             "Helped the team. Did tasks. Was responsible for stuff.",
             "Learning", "Computer Engineering degree."] * 3


def make(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    good = out_dir / "good_cv.pdf"
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    st = getSampleStyleSheet()
    story = []
    for line in GOOD.strip().splitlines():
        if line.isupper():
            story.append(Spacer(1, 6))
        story.append(Paragraph(line.replace("&", "&amp;"), st["Normal"]))
    SimpleDocTemplate(str(good), pagesize=A4).build(story)

    bad = out_dir / "bad_cv.pdf"
    c = canvas.Canvas(str(bad), pagesize=A4)
    w, h = A4
    c.setFillGray(0.9)
    c.rect(0, 0, 190, h, fill=1, stroke=0)
    c.setFillGray(0.3)
    c.rect(40, h - 160, 100, 100, fill=1, stroke=0)  # fake photo block (vector, not an image)
    c.setFillGray(0)
    y = h - 200
    for line in BAD_LEFT:
        c.drawString(20, y, line)
        y -= 18
    y = h - 80
    for line in BAD_RIGHT:
        c.drawString(230, y, line)
        y -= 18
    c.save()
    return good, bad


if __name__ == "__main__":
    import sys
    print(make(Path(sys.argv[1] if len(sys.argv) > 1 else "tests/samples")))


def make_styled(out_dir: Path) -> Path:
    """A nicely formatted single-column CV: centred header, bold headings with rules, bullets, bold labels."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "styled_cv.pdf"
    base = ParagraphStyle("b", fontName="Helvetica", fontSize=10.5, leading=14)
    name = ParagraphStyle("n", parent=base, fontName="Helvetica-Bold", fontSize=22, leading=26, alignment=TA_CENTER)
    contact = ParagraphStyle("c", parent=base, fontSize=10, leading=13.5, alignment=TA_CENTER, textColor=colors.HexColor("#444444"))
    head = ParagraphStyle("h", parent=base, fontName="Helvetica-Bold", fontSize=12, leading=15, spaceBefore=12, spaceAfter=1)
    bullet = ParagraphStyle("bl", parent=base, leftIndent=14, bulletIndent=3, spaceBefore=1.5)
    role = ParagraphStyle("r", parent=base, fontName="Helvetica-Bold", spaceBefore=6)
    story = [
        Paragraph("Can Kayacan", name),
        Paragraph("Front-End Developer | Full-Stack Web &amp; Mobile (Laravel, Flutter) | Finike, Antalya, Turkey (open to remote) | "
                  "+90 507 413 6639 | ckayacann@gmail.com | Portfolio: appseus.com", contact),
        Paragraph("SUMMARY", head), HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#444444"), spaceAfter=3),
        Paragraph("Front-End Developer with 3.5+ years of experience building web and mobile applications for public-sector and "
                  "private-sector clients. Experienced in full-stack delivery with Laravel/PHP back ends, JS/TypeScript front ends, "
                  "and Flutter mobile apps. Skilled in responsive UI, RESTful API integration, SEO and accessible, user-friendly interfaces.", base),
        Paragraph("EXPERIENCE", head), HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#444444"), spaceAfter=3),
        Paragraph("Front-End Developer - Appseus, Antalya  |  Jan 2022 - Present", role),
        Paragraph("Built responsive dashboards for government agencies using Laravel and Vue", bullet, bulletText="•"),
        Paragraph("Integrated RESTful APIs and reduced page load time by 40%", bullet, bulletText="•"),
        Paragraph("Shipped Flutter mobile apps used by 20,000 citizens, improving satisfaction by 25%", bullet, bulletText="•"),
        Paragraph("Junior Developer - Studio X, Istanbul  |  Jun 2020 - Dec 2021", role),
        Paragraph("Developed marketing sites in HTML, CSS and JS, increasing conversions by 30%", bullet, bulletText="•"),
        Paragraph("EDUCATION", head), HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#444444"), spaceAfter=3),
        Paragraph("B.Sc. Computer Programming, Akdeniz University, 2018 - 2020", base),
        Paragraph("SKILLS", head), HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#444444"), spaceAfter=3),
        Paragraph("<b>Languages:</b> PHP, JS, TypeScript, Dart, SQL", base),
        Paragraph("<b>Frameworks:</b> Laravel, Vue, Flutter, Tailwind", base),
        Paragraph("<b>Tools:</b> Git, Docker, Figma", base),
    ]
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=45, rightMargin=45, topMargin=40, bottomMargin=40).build(story)
    return path
