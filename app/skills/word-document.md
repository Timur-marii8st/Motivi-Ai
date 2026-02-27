---
name: word-document
description: Create Word (.docx) documents — reports, essays, business letters, contracts, CVs, meeting notes, templates. Use when user asks to write, generate, or create any Word document or .docx file.
---

# Word Document Creation

Use `execute_code` with `language: "python"`. Always save to `/output/filename.docx`.

## Core imports and setup

```python
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

doc = Document()
```

## Headings and paragraphs

```python
doc.add_heading('Document Title', level=0)   # Large title style
doc.add_heading('Chapter 1', level=1)         # Heading 1
doc.add_heading('Section 1.1', level=2)       # Heading 2
doc.add_heading('Subsection', level=3)        # Heading 3

doc.add_paragraph('Normal paragraph text.')
doc.add_paragraph()                           # Empty line / spacer
```

## Rich text formatting (bold, italic, color, size)

```python
p = doc.add_paragraph()
run = p.add_run('Bold text. ')
run.bold = True

run = p.add_run('Italic. ')
run.italic = True

run = p.add_run('Bold italic. ')
run.bold = True
run.italic = True

run = p.add_run('Colored. ')
run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)  # red

run = p.add_run('Large font.')
run.font.size = Pt(16)
```

## Paragraph alignment

```python
p = doc.add_paragraph('Centered text')
p.alignment = WD_ALIGN_PARAGRAPH.CENTER

p = doc.add_paragraph('Right-aligned text')
p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

p = doc.add_paragraph('Justified text. ' * 10)
p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
```

## Bullet and numbered lists

```python
# Bullet list
for item in ['First item', 'Second item', 'Third item']:
    doc.add_paragraph(item, style='List Bullet')

# Numbered list
for step in ['Open the file', 'Edit the content', 'Save and close']:
    doc.add_paragraph(step, style='List Number')
```

## Tables

```python
# Create table with header row
table = doc.add_table(rows=1, cols=3)
table.style = 'Table Grid'

# Header row
hdr = table.rows[0].cells
hdr[0].text = 'Name'
hdr[1].text = 'Department'
hdr[2].text = 'Score'

# Bold header text
for cell in table.rows[0].cells:
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.bold = True

# Data rows
data = [('Alice', 'Engineering', '95'), ('Bob', 'Marketing', '88'), ('Carol', 'Design', '91')]
for name, dept, score in data:
    row = table.add_row().cells
    row[0].text = name
    row[1].text = dept
    row[2].text = score

# Column widths
table.columns[0].width = Cm(5)
table.columns[1].width = Cm(5)
table.columns[2].width = Cm(3)
```

## Page break and section spacing

```python
doc.add_page_break()

# Paragraph with spacing
p = doc.add_paragraph('Section with spacing')
p.paragraph_format.space_before = Pt(18)
p.paragraph_format.space_after = Pt(6)
p.paragraph_format.line_spacing = Pt(20)
```

## Page margins

```python
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

section = doc.sections[0]
section.top_margin = Cm(2.5)
section.bottom_margin = Cm(2.5)
section.left_margin = Cm(3)
section.right_margin = Cm(1.5)
```

## Save

```python
doc.save('/output/document.docx')
```

---

## Full example — Business report

```python
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from datetime import date

doc = Document()

# Margins
section = doc.sections[0]
section.top_margin = Cm(2.5)
section.bottom_margin = Cm(2.5)
section.left_margin = Cm(3)
section.right_margin = Cm(2)

# Title block
title = doc.add_heading('Q1 2026 Performance Report', 0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER

sub = doc.add_paragraph(f'Prepared: {date.today().strftime("%d %B %Y")}')
sub.alignment = WD_ALIGN_PARAGRAPH.CENTER

doc.add_paragraph()

# Executive summary
doc.add_heading('1. Executive Summary', 1)
doc.add_paragraph(
    'Revenue grew 18% year-over-year driven by strong demand in the enterprise segment. '
    'Operating costs were held flat while headcount increased by 12 positions.'
)

# Key metrics table
doc.add_heading('2. Key Metrics', 1)
table = doc.add_table(rows=1, cols=3)
table.style = 'Table Grid'
for cell, header in zip(table.rows[0].cells, ['Metric', 'Q1 2025', 'Q1 2026']):
    cell.text = header
    cell.paragraphs[0].runs[0].bold = True

metrics = [
    ('Revenue', '$980K', '$1.16M'),
    ('Net Profit', '$120K', '$158K'),
    ('Active Users', '4,200', '5,800'),
    ('NPS Score', '42', '61'),
]
for row_data in metrics:
    row = table.add_row().cells
    for cell, value in zip(row, row_data):
        cell.text = value

doc.add_paragraph()

# Highlights
doc.add_heading('3. Highlights', 1)
for item in [
    'Launched new mobile app — 1,200 downloads in first week',
    'Closed 3 enterprise contracts worth $320K combined',
    'Customer churn reduced from 4.1% to 2.8%',
]:
    doc.add_paragraph(item, style='List Bullet')

# Next steps
doc.add_heading('4. Next Steps', 1)
for step in [
    'Expand sales team by 4 account executives (Q2)',
    'Release API v2 with improved rate limits',
    'Launch referral programme targeting SMB segment',
]:
    doc.add_paragraph(step, style='List Number')

doc.save('/output/q1_report.docx')
print("Report saved to /output/q1_report.docx")
```

---

## Full example — Academic essay

```python
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()
section = doc.sections[0]
section.top_margin = Cm(2.5)
section.bottom_margin = Cm(2.5)
section.left_margin = Cm(3)
section.right_margin = Cm(1.5)

# Title
title = doc.add_heading('The Impact of Artificial Intelligence on Modern Education', 0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER

author = doc.add_paragraph('Student Name | Course: CS-401 | Date: 27 February 2026')
author.alignment = WD_ALIGN_PARAGRAPH.CENTER
doc.add_paragraph()

# Abstract
doc.add_heading('Abstract', 1)
abstract = doc.add_paragraph(
    'This essay examines how artificial intelligence is reshaping educational institutions, '
    'focusing on personalised learning systems, administrative automation, and the ethical '
    'challenges that arise from widespread AI adoption in classrooms.'
)
abstract.paragraph_format.first_line_indent = Cm(1.25)

# Main body sections
sections_text = [
    ('Introduction', 'AI has transitioned from a niche research topic to a core component '
     'of educational technology. Tools such as intelligent tutoring systems, automated '
     'grading, and adaptive learning platforms are now used by millions of students worldwide.'),
    ('Personalised Learning', 'Adaptive systems analyse student performance in real time '
     'and adjust difficulty, pacing, and content accordingly. Research shows a 25% improvement '
     'in knowledge retention compared with traditional one-size-fits-all curricula.'),
    ('Challenges and Ethical Concerns', 'Data privacy, algorithmic bias, and the risk of '
     'over-reliance on automation remain significant concerns. Educators must balance '
     'technological efficiency with the irreplaceable value of human mentorship.'),
    ('Conclusion', 'AI offers compelling benefits for education but requires careful governance. '
     'Institutions should adopt AI tools incrementally, with ongoing evaluation of outcomes '
     'and robust ethical frameworks.'),
]

for heading, body in sections_text:
    doc.add_heading(heading, 1)
    p = doc.add_paragraph(body)
    p.paragraph_format.first_line_indent = Cm(1.25)
    for run in p.runs:
        run.font.size = Pt(12)

# References
doc.add_heading('References', 1)
refs = [
    'Luckin, R. (2018). Machine Learning and Human Intelligence. UCL IoE Press.',
    'Holmes, W. et al. (2019). Artificial Intelligence in Education. UNESCO.',
    'Seldon, A. & Abidoye, O. (2018). The Fourth Education Revolution. University of Buckingham Press.',
]
for ref in refs:
    doc.add_paragraph(ref, style='List Number')

doc.save('/output/essay.docx')
print("Essay saved to /output/essay.docx")
```
