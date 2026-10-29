"""Static word lists. All entries are ASCII-folded + lowercase (see text_utils.fold)."""

# Terms we always treat as "real" skills when they appear in a job description.
SKILLS = {
    # languages
    "python", "java", "javascript", "typescript", "c++", "c#", "golang", "rust", "kotlin", "swift",
    "php", "ruby", "scala", "matlab", "bash", "powershell", "sql", "nosql", "html", "css", "sass",
    "dart", "perl", "r studio", "vba",
    # web / frameworks
    "react", "angular", "vue", "next.js", "node.js", "express", "django", "flask", "fastapi",
    "spring", "spring boot", ".net", "asp.net", "laravel", "rails", "graphql", "rest api",
    "microservices", "websocket", "tailwind", "bootstrap", "flutter", "react native", "android", "ios",
    # data / ml
    "machine learning", "deep learning", "data science", "data analysis", "data engineering",
    "data visualization", "nlp", "computer vision", "pytorch", "tensorflow", "keras", "scikit-learn",
    "pandas", "numpy", "spark", "hadoop", "kafka", "airflow", "etl", "power bi", "tableau", "excel",
    "looker", "statistics", "a/b testing", "big data", "llm", "generative ai",
    # databases
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "oracle", "sql server", "sqlite",
    "dynamodb", "snowflake", "bigquery",
    # cloud / devops
    "aws", "azure", "gcp", "google cloud", "docker", "kubernetes", "terraform", "ansible", "jenkins",
    "ci/cd", "github actions", "gitlab", "git", "github", "linux", "devops", "nginx", "prometheus",
    "grafana", "serverless", "cloud computing",
    # security / network
    "cybersecurity", "penetration testing", "owasp", "siem", "networking", "tcp/ip", "firewall",
    "iso 27001", "soc", "encryption",
    # engineering practices
    "unit testing", "test automation", "selenium", "pytest", "junit", "tdd", "agile", "scrum", "kanban",
    "jira", "confluence", "code review", "system design", "design patterns", "oop", "algorithms",
    "data structures", "api", "sdk", "debugging", "performance optimization", "scalability",
    # business / general
    "project management", "product management", "stakeholder management", "budgeting", "forecasting",
    "risk management", "business analysis", "requirements gathering", "customer success",
    "customer service", "sales", "b2b", "crm", "salesforce", "hubspot", "sap", "erp", "seo", "sem",
    "google analytics", "content marketing", "social media", "copywriting", "market research",
    "negotiation", "recruiting", "onboarding", "payroll", "accounting", "financial analysis",
    "auditing", "compliance", "supply chain", "logistics", "procurement", "quality assurance",
    "lean", "six sigma", "figma", "photoshop", "illustrator", "ux", "ui", "user research",
    "wireframing", "prototyping", "autocad", "solidworks", "plc",
    # soft skills
    "leadership", "teamwork", "communication", "problem solving", "critical thinking", "mentoring",
    "collaboration", "time management", "presentation", "cross-functional", "analytical",
    # turkish common
    "proje yonetimi", "veri analizi", "musteri iliskileri", "satis", "pazarlama", "muhasebe",
    "takim calismasi", "iletisim", "liderlik", "raporlama", "butcelendirme", "ik", "insan kaynaklari",
    "yazilim gelistirme", "veritabani", "yapay zeka", "makine ogrenmesi", "siber guvenlik",
}

# Two-way synonyms (all folded). Each group is treated as the same keyword when matching.
SYNONYM_GROUPS = [
    {"javascript", "js", "ecmascript"},
    {"typescript", "ts"},
    {"kubernetes", "k8s"},
    {"machine learning", "ml", "makine ogrenmesi"},
    {"artificial intelligence", "ai", "yapay zeka"},
    {"postgresql", "postgres"},
    {"node.js", "nodejs", "node js", "node"},
    {"react", "react.js", "reactjs"},
    {"vue", "vue.js", "vuejs"},
    {"next.js", "nextjs"},
    {"ci/cd", "cicd", "ci cd", "continuous integration", "continuous delivery"},
    {"aws", "amazon web services"},
    {"gcp", "google cloud", "google cloud platform"},
    {"golang", "go lang"},
    {"c#", "csharp", "c sharp"},
    {"rest api", "restful", "rest apis", "restful api"},
    {"nlp", "natural language processing"},
    {"llm", "large language model", "large language models"},
    {"oop", "object oriented", "object-oriented"},
    {"ux", "user experience"},
    {"ui", "user interface"},
    {"seo", "search engine optimization"},
    {"crm", "customer relationship management"},
    {"erp", "enterprise resource planning"},
    {"etl", "data pipeline", "data pipelines"},
    {"tdd", "test driven development", "test-driven development"},
    {"sql", "t-sql", "pl/sql", "mysql", "postgresql", "sql server"},
    {"project management", "proje yonetimi"},
    {"data analysis", "veri analizi", "data analytics"},
    {"teamwork", "team player", "takim calismasi", "collaboration"},
    {"communication", "iletisim"},
    {"leadership", "liderlik"},
    {"sales", "satis"},
    {"marketing", "pazarlama"},
]

STOPWORDS_EN = set("""
a about above after again all also am an and any are as at be because been before being below between both
but by can could did do does doing down during each few for from further had has have having he her here
hers him his how i if in into is it its just me more most my no nor not now of off on once only or other
our out over own same she should so some such than that the their them then there these they this those
through to too under until up us very was we were what when where which while who whom why will with would
you your yours able across within including etc per via new work working role team join looking seeking
ideal candidate position responsibilities requirements qualifications preferred required experience years
year plus strong good great excellent ability skills skill knowledge understanding proven demonstrated
related relevant using use used build building help helping make making across end must nice bonus
rest company business opportunity opportunities apply benefits salary equal employer
""".split())

STOPWORDS_TR = set("""
ve veya ile icin bir bu su o da de ki mi mu gibi daha en cok az olan olarak ise ama fakat ancak her tum
bazi ayni diger kadar sonra once uzerinde altinda arasinda hakkinda ilgili gereken gerekli aranan
tercihen avantaj olarak sahip bilgi bilgisi tecrube deneyim yil yillik pozisyon is firma sirket ekip
ekibimize katilacak adayi aday arayis arayisindayiz yetenek yetenekler beceri beceriler sorumluluklar
nitelikler artilari
""".split())

REQUIRED_MARKERS = ("required", "requirements", "must have", "must-have", "minimum qualifications",
                    "qualifications", "what you need", "what we need", "you have", "gerekli", "aranan",
                    "nitelikler", "sartlar", "aranan nitelikler", "zorunlu")
PREFERRED_MARKERS = ("nice to have", "nice-to-have", "preferred", "bonus", "a plus", "good to have",
                     "tercihen", "avantaj", "artisi", "tercih sebebi")

# Section headings -> canonical key. Folded, lowercase.
SECTION_ALIASES = {
    "summary": {"summary", "professional summary", "profile", "professional profile", "about me", "about",
                "objective", "career objective", "personal statement", "ozet", "profil", "hakkimda",
                "kariyer hedefi", "ozgecmis ozeti", "profesyonel ozet"},
    "experience": {"experience", "work experience", "professional experience", "employment",
                   "employment history", "work history", "career history", "relevant experience",
                   "is deneyimi", "deneyim", "is tecrubesi", "tecrube", "profesyonel deneyim",
                   "calisma gecmisi", "is hayati", "deneyimler"},
    "education": {"education", "academic background", "academic qualifications", "education and training",
                  "egitim", "egitim bilgileri", "akademik gecmis", "egitim durumu"},
    "skills": {"skills", "technical skills", "core competencies", "key skills", "competencies",
               "skills and tools", "technologies", "tech stack", "yetenekler", "beceriler",
               "teknik beceriler", "yetkinlikler", "teknik yetenekler", "teknolojiler"},
    "projects": {"projects", "personal projects", "selected projects", "side projects", "projeler",
                 "personal products and ventures", "ventures", "selected freelance and design works",
                 "freelance work", "freelance projects", "freelance", "selected works", "portfolio",
                 "kisisel projeler", "akademik projeler"},
    "certifications": {"certifications", "certificates", "licenses", "licenses and certifications",
                       "courses", "sertifikalar", "sertifikalar ve kurslar", "kurslar", "sertifika"},
    "languages": {"languages", "language", "language skills", "diller", "yabanci dil", "yabanci diller", "dil bilgisi"},
    "awards": {"awards", "honors", "achievements", "awards and honors", "oduller", "basarilar"},
    "publications": {"publications", "research", "yayinlar", "arastirmalar"},
    "volunteer": {"volunteer", "volunteering", "volunteer experience", "gonulluluk", "gonullu calismalar"},
    "interests": {"interests", "hobbies", "hobbies and interests", "ilgi alanlari", "hobiler"},
    "references": {"references", "reference", "referanslar", "referans"},
    "tools": {"tools", "tools and technologies", "software", "software skills", "araclar", "yazilimlar"},
    "contact": {"contact", "contact info", "contact information", "contact details", "iletisim",
                "iletisim bilgileri"},
    "internships": {"internships", "internship", "internships and courses", "internships and training",
                    "staj", "stajlar", "staj ve kurslar", "stajlar ve kurslar"},
}

SECTION_TITLES = {
    "summary": "Summary", "experience": "Experience", "education": "Education", "skills": "Skills",
    "projects": "Projects", "certifications": "Certifications", "languages": "Languages",
    "awards": "Awards", "publications": "Publications", "volunteer": "Volunteer Experience",
    "interests": "Interests", "references": "References",
    "contact": "Contact", "internships": "Internships", "tools": "Tools",
}

ACTION_VERBS_EN = set("""
led built ran drove grew cut won wrote taught managed developed designed created launched delivered
improved increased reduced achieved implemented established optimized streamlined automated analyzed
coordinated directed mentored trained negotiated generated spearheaded architected engineered deployed
migrated refactored maintained owned initiated planned executed resolved secured scaled shipped
integrated collaborated supervised oversaw produced presented researched tested validated
""".split())

ACTION_VERB_STEMS_TR = (
    "gelistir", "yonet", "tasarla", "olustur", "artir", "azalt", "uygula", "planla", "kur", "sagla",
    "analiz", "yurut", "entegre", "otomat", "liderlik", "egit", "gelis", "optimiz", "optimize", "hazirla",
    "raporla", "koordin", "denetle", "gelist", "basari", "tamamla", "cozum", "uret", "test", "yayinla",
    "dagit", "arastir", "sun", "iyilestir", "yeniden", "dusur", "katki", "calis", "gorev", "sorumlu",
)

DEGREE_WORDS = ("bachelor", "master", "phd", "doctorate", "b.sc", "bsc", "m.sc", "msc", "b.a", "m.a",
                "mba", "associate", "diploma", "lisans", "yuksek lisans", "doktora", "onlisans",
                "engineering", "mühendis", "muhendis", "degree", "bs ", "ms ")
INSTITUTION_WORDS = ("university", "college", "institute", "school", "academy", "universite", "universitesi",
                     "fakulte", "lise", "enstitu", "yuksekokul", "meslek")

# Glyphs that commonly break parsers or look like decoration
SYMBOL_CHARS = "★☆✪✯✰●○◐◑◒◓◔◕■□▪▫◆◇❖✦✧►▶➤➢➔➜➨✓✔✗✘☎☏✆✉✈☑☐⚫⚪▲△▼▽♦♥♠♣•‣◦∙·"
BULLET_CHARS = "-•●▪■◦‣∙*–—➤►▶➢✓✔▫□○◆❖✦·"
