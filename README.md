# ATS Scout

**A free, offline desktop app that tells you how an Applicant Tracking System (ATS) will read your CV, and fixes it.**

No account. No API key. No `.env` file. No internet connection needed. Your CV never leaves your computer.

## What it does

| Feature | Details |
|---|---|
| **ATS score (0-100)** | One overall number for how safely your CV can be parsed. |
| **Section-by-section scores** | Formatting, Contact, Summary, Experience, Education and Skills each get their own score and a checklist of what passed and what failed. |
| **ATS-blocker warnings** | Detects photos and images, tables, multi-column layouts, text boxes, icon fonts, star ratings, skill bars (`Python 80%`), decorative symbols, contact info hidden in Word headers, too many pages, mixed date formats and more. |
| **Job match** | Paste the job description. You get a keyword match score, a list of found and missing keywords, a keyword-stuffing warning and an estimate of your overall fit. |
| **Fixed CV as PDF** | Re-builds your CV as a clean PDF **in your own layout**: same fonts, bold text, centred header, spacing, lines under headings and bullets. It only removes ATS blockers (icons, stars, skill bars). |
| **Write my CV for this job** | A switch that tailors the fixed PDF to one job posting: uses the posting's wording (`JS` becomes `JavaScript`), moves relevant skills first, varies overused keywords, and adds the missing skills **you tick as "I really have this"**. Shows your scores before and after. |
| **Score report as PDF** | A printable report of all scores and fixes. |
| **English + Turkish** | Understands Turkish section titles (`İş Deneyimi`, `Eğitim`, `Yetenekler`...) and Turkish characters. |

## Before you start (one time)

You need **Python 3.10 or newer**.

1. Check whether you already have it. Open a terminal:
   - **Windows:** press the Windows key, type `cmd`, press Enter.
   - **macOS:** press Cmd+Space, type `Terminal`, press Enter.
   - **Linux:** open your terminal app.
2. Type this and press Enter:
   ```
   python --version
   ```
   (On macOS/Linux, if that fails, try `python3 --version`.)
3. If you see `Python 3.10` or higher, continue to the next section.
4. If not, install Python from <https://www.python.org/downloads/>.
   - **Windows:** on the first installer screen, tick **"Add python.exe to PATH"** before clicking Install.
   - **Linux only:** also run `sudo apt install python3-tk` (Debian/Ubuntu) or `sudo dnf install python3-tkinter` (Fedora). Windows and macOS already include it.

## Install

### Step 1. Get the code

**Option A: with Git**
```
git clone https://github.com/ckayacann/ats-scout.git
cd ats-scout
```

**Option B: without Git**
1. Open the repository page on GitHub.
2. Click the green **Code** button, then **Download ZIP**.
3. Unzip it, then open a terminal inside the unzipped `ats-scout` folder.
   (Windows: open the folder in Explorer, click the address bar, type `cmd`, press Enter.)

### Step 2. Create a virtual environment (keeps things tidy)

**Windows**
```
python -m venv venv
venv\Scripts\activate
```

**macOS / Linux**
```
python3 -m venv venv
source venv/bin/activate
```

You should now see `(venv)` at the start of your terminal line.

### Step 3. Install the libraries

```
pip install -r requirements.txt
```

This downloads four small libraries (customtkinter, pdfplumber, python-docx, reportlab). It is the only time the internet is used.

## Run the app

Make sure `(venv)` is showing, then:

```
python main.py
```

(On macOS/Linux use `python3 main.py` if `python` is not found.)

The window opens. Next time you want to use it, open a terminal in the folder, activate the environment again (Step 2, second command only) and run `python main.py`.

### Double-click launcher (easiest way after you have Python)

Inside the project folder there are two launcher files. The first time they set everything up for you (Steps 2 and 3 above); after that they just open the app.

- **Windows:** double-click `Start-Windows.bat`.
- **macOS:** double-click `Start-Mac.command`. If macOS says it cannot be opened because it is from an unidentified developer, right-click the file, choose **Open**, then **Open** again (only needed once). If nothing happens at all, run `chmod +x Start-Mac.command` once in Terminal inside the folder.

## How to use it

1. Click **Choose CV** and pick your resume (`.pdf`, `.docx` or `.txt`).
2. *(Optional but recommended)* Copy the job posting text and paste it into the box. This unlocks the job-match score.
3. Click **Analyze**.
4. Look through the four tabs:
   - **Overview**: your scores and the top things to fix.
   - **Sections**: score and checklist for every section.
   - **Warnings**: everything that can hurt you in an ATS, with how to fix it.
   - **Keywords**: which job keywords you have (green) and which are missing (red).
5. Click **Export fixed CV (PDF)** to save a cleaned, ATS-friendly version that keeps your own layout.
   Click **Export score report (PDF)** if you want the full report on paper.
6. *(Optional)* Turn on **Write my CV for this job** before exporting. A window asks which of the missing keywords you
   *really* have. Tick only those: they are added to your Skills section and mentioned once in your Summary. Unticked
   skills are never added. The result shows `ATS score` and `Job match` before and after, and lists every change.

> **Important:** ATS Scout never invents experience. It cleans your own text and, in "Write my CV for this job" mode,
> only adds skills you explicitly tick. Always read the new PDF once before you send it.
>
> Your layout is kept for single-column PDF and DOCX files. A two-column design (sidebar + main column, photo, coloured
> headings) is read column by column and rebuilt as ONE clean column in reading order: name, contact, profile, experience,
> projects, education, skills, languages. That is what an ATS needs. Photos and decorative shapes are left out.
> CVs with tables or text boxes fall back to a simple single-column layout, and the app tells you when that happens.

## Run without opening the window (optional)

```
python -m ats_scout.analyzer path/to/cv.pdf path/to/job_description.txt
```

Prints the scores in the terminal. The job description file is optional.

## Make a standalone app (optional)

If you want a double-click app for friends who do not have Python:

```
pip install pyinstaller
pyinstaller --noconfirm --windowed --name ATSScout --collect-all customtkinter main.py
```

The app appears in the `dist/ATSScout` folder. Build on the operating system you want to target (a Windows build only runs on Windows, and so on).

## How the score works

All checks are plain, open rules you can read in [`ats_scout/analyzer.py`](ats_scout/analyzer.py). There is no AI model and no network call.

| Part | Weight | What is checked |
|---|---|---|
| Formatting & Parseability | 30% | Readable text layer, images, tables, columns, text boxes, icon fonts, symbols, skill bars, length, fonts, date formats |
| Experience | 25% | Dates, number of bullets, action verbs, measurable results, bullet length |
| Skills | 17% | Section exists, enough skills, grouped, no ratings/bars |
| Contact | 10% | Name, email, phone, LinkedIn/GitHub link, not hidden in header/footer |
| Education | 10% | Section, degree, school name, year |
| Summary | 8% | Exists, 25-110 words, years of experience, no first-person phrasing |

**Job match** takes the keywords from the job description (known skills, repeated terms, capitalised tool names), weights the ones under "Requirements" higher and the ones under "Nice to have" lower, understands common synonyms (`JS` = `JavaScript`, `K8s` = `Kubernetes`) and checks how many are in your CV.
**Overall fit** = 35% ATS score + 65% job match.

### Honest limits

- Every ATS (Workday, Greenhouse, Lever, Taleo...) behaves differently. The score is an **estimate**, not a guarantee.
- Scanned CVs (pictures of text) cannot be read, because there is no OCR. Export a real text PDF from Word or Google Docs.
- Section detection relies on standard titles. Creative titles like "My Journey" will not be recognised, which is exactly what a real ATS also struggles with.
- Two-column PDFs are separated into their columns. Layouts with three or more columns, or text drawn as images, may still fall back to the simple layout.

## Troubleshooting

| Problem | Fix |
|---|---|
| `python` is not recognised (Windows) | Re-install Python and tick **Add python.exe to PATH**, or use `py main.py`. |
| `No module named tkinter` (Linux) | `sudo apt install python3-tk` |
| `No module named _tkinter` (macOS, Homebrew Python) | `brew install python-tk@3.14` (match your Python version, e.g. `python-tk@3.12`), then delete and re-create the `venv`. |
| `No module named customtkinter` | The virtual environment is not active. Run the activate command again, then `pip install -r requirements.txt`. |
| "No readable text layer" | Your CV is a scan or image. Export it again as a text-based PDF. |
| Turkish letters look wrong in the fixed PDF | The app uses Arial/Calibri (Windows, macOS) or DejaVu (Linux). Install one of them. |
| Window looks blurry on a high-DPI screen (Windows) | Right-click Python, Properties, Compatibility, Change high DPI settings, override scaling. |

## Project layout

```
ats-scout/
├── main.py                 # start the app
├── requirements.txt
├── ats_scout/
│   ├── app.py              # desktop UI
│   ├── analyzer.py         # scoring + job matching
│   ├── extract.py          # reads PDF / DOCX / TXT
│   ├── layout.py           # reads fonts, bold, alignment, spacing from your PDF / DOCX
│   ├── tailor.py           # "write my CV for this job" rules
│   ├── pdf_builder.py      # fixed CV + report PDFs
│   ├── lexicon.py          # skills, synonyms, section titles (easy to extend)
│   └── text_utils.py
└── tests/
```

## Contributing

Run the tests with:

```
pip install pytest
python -m pytest
```

Ideas welcome: more languages, more skill keywords in `lexicon.py`, OCR for scanned CVs, more ATS checks.

## License

MIT. Free to use, change and share.
