---
name: cv-resume
description: Create professional CVs, resumes, and cover letters as Word (.docx) files. Use when user asks to write, create, or update a CV, resume, curriculum vitae, or cover letter.
---

# CV / Resume Creation

Use `execute_code` with `language: "python"`. Save to `/output/cv.docx`.

Always create a polished, ATS-friendly Word document. Personalise with the user's actual details.

## Canonical CV structure

1. Name + Contact (header)
2. Professional Summary (2–3 sentences)
3. Work Experience (reverse chronological)
4. Education
5. Skills
6. Optional: Projects, Certifications, Languages, Interests

---

## Core helper — build header

```python
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

doc = Document()

# Tight margins for a CV
section = doc.sections[0]
section.top_margin    = Cm(1.8)
section.bottom_margin = Cm(1.8)
section.left_margin   = Cm(2.2)
section.right_margin  = Cm(2.2)

# Name (centred, large)
name_para = doc.add_paragraph()
name_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
name_run = name_para.add_run('FIRSTNAME LASTNAME')
name_run.bold = True
name_run.font.size = Pt(22)
name_run.font.color.rgb = RGBColor(0x1F, 0x49, 0x7D)

# Contact line
contact_para = doc.add_paragraph()
contact_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
contact_run = contact_para.add_run(
    'email@example.com  •  +44 7700 900 123  •  linkedin.com/in/yourname  •  London, UK'
)
contact_run.font.size = Pt(10)
contact_run.font.color.rgb = RGBColor(0x40, 0x40, 0x40)
```

## Section heading helper

```python
def add_section_heading(doc, title: str):
    """Adds a visually distinct section heading with a coloured bottom border."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after  = Pt(2)
    run = p.add_run(title.upper())
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = RGBColor(0x1F, 0x49, 0x7D)
    # Add bottom border via XML
    from docx.oxml import OxmlElement
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '6')
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), '1F497D')
    pBdr.append(bottom)
    pPr.append(pBdr)
    return p
```

## Experience entry helper

```python
def add_experience(doc, title, company, dates, location, bullets):
    """Adds one job entry with role, company, dates, and bullet points."""
    # Role + company line
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after  = Pt(0)
    r_title = p.add_run(f'{title}  —  ')
    r_title.bold = True
    r_title.font.size = Pt(11)
    r_company = p.add_run(company)
    r_company.bold = False
    r_company.font.size = Pt(11)
    # Dates line (right-aligned using tab)
    p2 = doc.add_paragraph()
    p2.paragraph_format.space_before = Pt(0)
    p2.paragraph_format.space_after  = Pt(2)
    r_dates = p2.add_run(f'{dates}  |  {location}')
    r_dates.italic = True
    r_dates.font.size = Pt(10)
    r_dates.font.color.rgb = RGBColor(0x60, 0x60, 0x60)
    # Bullet points
    for bullet in bullets:
        bp = doc.add_paragraph(bullet, style='List Bullet')
        bp.paragraph_format.space_before = Pt(1)
        bp.paragraph_format.space_after  = Pt(1)
        for run in bp.runs:
            run.font.size = Pt(10.5)
```

---

## Full example — Software Developer CV

```python
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

doc = Document()
section = doc.sections[0]
for attr in ('top_margin','bottom_margin','left_margin','right_margin'):
    setattr(section, attr, Cm(2.0))

# ── Header ────────────────────────────────────────────────────────────────────
def centre_bold(doc, text, size, color_hex='1F497D'):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(text)
    r.bold = True; r.font.size = Pt(size)
    r.font.color.rgb = RGBColor(*bytes.fromhex(color_hex))
    return p

def centre_normal(doc, text, size=10, color_hex='404040'):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.font.color.rgb = RGBColor(*bytes.fromhex(color_hex))
    return p

def section_head(doc, title):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after  = Pt(2)
    r = p.add_run(title.upper())
    r.bold = True; r.font.size = Pt(11)
    r.font.color.rgb = RGBColor(0x1F, 0x49, 0x7D)
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    btm  = OxmlElement('w:bottom')
    btm.set(qn('w:val'), 'single'); btm.set(qn('w:sz'), '6')
    btm.set(qn('w:space'), '1');    btm.set(qn('w:color'), '1F497D')
    pBdr.append(btm); pPr.append(pBdr)

def job(doc, title, company, dates, loc, bullets):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    r = p.add_run(title); r.bold = True; r.font.size = Pt(11)
    p.add_run(f'  —  {company}').font.size = Pt(11)
    p2 = doc.add_paragraph()
    r2 = p2.add_run(f'{dates}  |  {loc}')
    r2.italic = True; r2.font.size = Pt(10)
    r2.font.color.rgb = RGBColor(0x60, 0x60, 0x60)
    for b in bullets:
        bp = doc.add_paragraph(b, style='List Bullet')
        bp.paragraph_format.space_before = Pt(1)
        for run in bp.runs: run.font.size = Pt(10.5)

centre_bold(doc, 'ALEX JOHNSON', 22)
centre_normal(doc, 'alex.johnson@email.com  •  +44 7700 900 123  •  github.com/alexj  •  London, UK')

# ── Summary ───────────────────────────────────────────────────────────────────
section_head(doc, 'Professional Summary')
summary = doc.add_paragraph(
    'Full-stack software developer with 5 years of experience building scalable web applications '
    'using Python, React, and PostgreSQL. Passionate about clean code, test-driven development, '
    'and mentoring junior developers. Delivered 12+ production systems serving 200K+ users.'
)
summary.paragraph_format.space_after = Pt(2)

# ── Experience ────────────────────────────────────────────────────────────────
section_head(doc, 'Work Experience')
job(doc, 'Senior Software Developer', 'TechCorp Ltd', 'Mar 2022 – Present', 'London, UK', [
    'Led re-architecture of monolithic system to microservices, reducing p99 latency by 65%',
    'Mentored 4 junior developers; introduced code review standards adopted company-wide',
    'Delivered real-time analytics dashboard serving 50K daily active users (React + FastAPI)',
    'Reduced cloud costs by £18K/month by optimising PostgreSQL queries and caching strategy',
])
job(doc, 'Software Developer', 'StartupXYZ', 'Jun 2020 – Feb 2022', 'Remote', [
    'Built customer-facing API integrating 8 third-party payment and logistics providers',
    'Increased test coverage from 34% to 91%; reduced production bugs by 70%',
    'Implemented CI/CD pipeline (GitHub Actions + Docker) cutting deployment time from 2h to 8min',
])
job(doc, 'Junior Developer', 'Webagency Co.', 'Sep 2019 – May 2020', 'Manchester, UK', [
    'Developed and maintained 15 client websites (WordPress, PHP, JavaScript)',
    'Automated weekly reporting tasks saving 4 hours of manual work per week',
])

# ── Education ─────────────────────────────────────────────────────────────────
section_head(doc, 'Education')
p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(6)
r = p.add_run('BSc Computer Science (First Class Honours)'); r.bold = True; r.font.size = Pt(11)
p.add_run('  —  University of Manchester').font.size = Pt(11)
doc.add_paragraph('Sep 2016 – Jun 2019  |  Dissertation: "Scalable real-time data pipelines with Apache Kafka"').paragraph_format.space_before = Pt(0)

# ── Skills ────────────────────────────────────────────────────────────────────
section_head(doc, 'Technical Skills')
skills_table = doc.add_table(rows=4, cols=2)
skills_table.style = 'Table Grid'
rows_data = [
    ('Languages',  'Python, JavaScript (ES2023), TypeScript, SQL, Bash'),
    ('Frameworks', 'FastAPI, Django, React, Next.js, Celery'),
    ('Tools',      'Docker, Kubernetes, PostgreSQL, Redis, GitHub Actions, Terraform'),
    ('Cloud',      'AWS (EC2, RDS, S3, Lambda), GCP (Cloud Run, BigQuery)'),
]
for row, (label, value) in zip(skills_table.rows, rows_data):
    row.cells[0].text = label
    row.cells[1].text = value
    row.cells[0].paragraphs[0].runs[0].bold = True

# ── Certifications ────────────────────────────────────────────────────────────
section_head(doc, 'Certifications & Courses')
for cert in [
    'AWS Certified Solutions Architect – Associate (2024)',
    'Google Professional Data Engineer (2023)',
    'Kubernetes Administrator (CKA) (2022)',
]:
    doc.add_paragraph(cert, style='List Bullet')

doc.save('/output/cv.docx')
print("CV saved to /output/cv.docx")
```

---

## Full example — Cover letter

```python
from docx import Document
from docx.shared import Pt, Cm
from datetime import date

doc = Document()
section = doc.sections[0]
for attr in ('top_margin','bottom_margin','left_margin','right_margin'):
    setattr(section, attr, Cm(2.5))

def p(doc, text='', size=11, bold=False, space_after=6):
    para = doc.add_paragraph(text)
    para.paragraph_format.space_after = Pt(space_after)
    for run in para.runs:
        run.font.size = Pt(size)
        run.bold = bold
    return para

p(doc, 'Alex Johnson')
p(doc, 'alex.johnson@email.com  |  +44 7700 900 123')
p(doc, date.today().strftime('%d %B %Y'))
p(doc, '')
p(doc, 'Hiring Manager')
p(doc, 'TechStartup Ltd')
p(doc, '123 Innovation Street, London EC2A 1AB')
p(doc, '')
p(doc, 'Dear Hiring Manager,', bold=True, space_after=10)
p(doc,
    'I am writing to apply for the Senior Backend Engineer position advertised on LinkedIn. '
    'With five years of experience building high-throughput Python APIs and a track record of '
    'improving system performance and developer productivity, I am confident I would make a '
    'strong contribution to your engineering team.')
p(doc,
    'In my current role at TechCorp Ltd, I led the migration of a legacy monolith to '
    'microservices, reducing API latency by 65% and enabling the team to deploy independently. '
    'I also introduced a test-driven development culture that brought coverage from 34% to 91%, '
    'significantly reducing production incidents.')
p(doc,
    'I am particularly drawn to TechStartup because of your focus on developer tooling and your '
    'commitment to open-source. I believe my background in distributed systems and my experience '
    'with Kubernetes and AWS aligns well with the challenges described in the job posting.')
p(doc, 'I have attached my CV and would welcome the opportunity to discuss my application. Thank you for your time and consideration.')
p(doc, '')
p(doc, 'Yours sincerely,')
p(doc, 'Alex Johnson')

doc.save('/output/cover_letter.docx')
print("Cover letter saved to /output/cover_letter.docx")
```
