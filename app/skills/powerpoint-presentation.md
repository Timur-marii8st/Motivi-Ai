---
name: powerpoint-presentation
description: Create PowerPoint (.pptx) presentations — pitch decks, lecture slides, project proposals, business presentations, training materials. Use when user asks to create any presentation, slide deck, or .pptx file.
---

# PowerPoint Presentation Creation

Use `execute_code` with `language: "python"`. Always save to `/output/filename.pptx`.

## Core imports and setup

```python
from pptx import Presentation
from pptx.util import Inches, Pt, Cm, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

prs = Presentation()
# Standard 16:9 widescreen (default)
# prs.slide_width  = Inches(13.33)
# prs.slide_height = Inches(7.5)
```

## Slide layouts (built-in)

```
0 - Title Slide          (title + subtitle)
1 - Title and Content    (title + large content box)
2 - Title and Two Content (title + two side-by-side boxes)
5 - Title Only           (just a title bar)
6 - Blank                (completely empty)
```

```python
slide_layout = prs.slide_layouts[0]   # pick layout
slide = prs.slides.add_slide(slide_layout)
```

## Title slide (layout 0)

```python
slide = prs.slides.add_slide(prs.slide_layouts[0])
slide.shapes.title.text = 'Presentation Title'
slide.placeholders[1].text = 'Subtitle or author / date'
```

## Content slide (layout 1) — title + bullet points

```python
slide = prs.slides.add_slide(prs.slide_layouts[1])
slide.shapes.title.text = 'Slide Title'

tf = slide.placeholders[1].text_frame
tf.text = 'First bullet point'          # sets the first paragraph

p = tf.add_paragraph()
p.text = 'Second bullet point'
p.level = 0                             # top level

p = tf.add_paragraph()
p.text = 'Sub-point under second'
p.level = 1                             # indented

p = tf.add_paragraph()
p.text = 'Another sub-point'
p.level = 1
```

## Custom text box (any position/size)

```python
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor

slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank slide

txBox = slide.shapes.add_textbox(
    Inches(1), Inches(1),   # left, top
    Inches(8), Inches(2),   # width, height
)
tf = txBox.text_frame
tf.word_wrap = True

p = tf.paragraphs[0]
p.text = 'Custom positioned text'
p.alignment = PP_ALIGN.CENTER

run = p.runs[0]
run.font.size = Pt(28)
run.font.bold = True
run.font.color.rgb = RGBColor(0x1F, 0x49, 0x7D)
```

## Background colour for a slide

```python
from pptx.oxml.ns import qn
from lxml import etree

def set_slide_background(slide, hex_color: str):
    """Set solid background colour. hex_color e.g. '1F497D'"""
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = RGBColor.from_string(hex_color)

set_slide_background(slide, '1F497D')   # dark blue background
```

## Table on a slide

```python
from pptx.util import Inches

slide = prs.slides.add_slide(prs.slide_layouts[5])
slide.shapes.title.text = 'Comparison Table'

rows, cols = 4, 3
left, top, width, height = Inches(1.5), Inches(1.8), Inches(10), Inches(3.5)
table = slide.shapes.add_table(rows, cols, left, top, width, height).table

# Headers
headers = ['Feature', 'Basic Plan', 'Pro Plan']
for col_idx, header in enumerate(headers):
    cell = table.cell(0, col_idx)
    cell.text = header
    cell.text_frame.paragraphs[0].runs[0].font.bold = True
    cell.text_frame.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    cell.fill.solid()
    cell.fill.fore_color.rgb = RGBColor(0x1F, 0x49, 0x7D)

# Data rows
data = [
    ('Storage', '10 GB', '100 GB'),
    ('Users', '1', 'Unlimited'),
    ('Support', 'Email', '24/7 Phone'),
]
for row_idx, row_data in enumerate(data, start=1):
    for col_idx, value in enumerate(row_data):
        table.cell(row_idx, col_idx).text = value
```

## Add image

```python
# Image must exist in the sandbox — generate it first or use a placeholder
# pic = slide.shapes.add_picture('/output/logo.png', Inches(0.5), Inches(0.5), Inches(2))
```

## Save

```python
prs.save('/output/presentation.pptx')
print("Saved to /output/presentation.pptx")
```

---

## Full example — Business pitch deck (6 slides)

```python
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

# ── Colour palette ────────────────────────────────────────────────────────────
DARK_BLUE  = RGBColor(0x1F, 0x49, 0x7D)
MID_BLUE   = RGBColor(0x2E, 0x75, 0xB6)
LIGHT_GRAY = RGBColor(0xF2, 0xF2, 0xF2)
WHITE      = RGBColor(0xFF, 0xFF, 0xFF)
ORANGE     = RGBColor(0xED, 0x7D, 0x31)

prs = Presentation()
W = prs.slide_width
H = prs.slide_height

def add_text(slide, text, left, top, width, height,
             size=18, bold=False, color=None, align=PP_ALIGN.LEFT, wrap=True):
    txb = slide.shapes.add_textbox(left, top, width, height)
    tf = txb.text_frame
    tf.word_wrap = wrap
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = color
    return txb

def solid_bg(slide, color: RGBColor):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = color

# ── Slide 1: Title ────────────────────────────────────────────────────────────
s1 = prs.slides.add_slide(prs.slide_layouts[6])
solid_bg(s1, DARK_BLUE)
add_text(s1, 'NovaTech Solutions', Inches(1), Inches(2),   Inches(11), Inches(1.5),
         size=44, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
add_text(s1, 'Series A Pitch Deck  •  February 2026', Inches(1), Inches(3.7),
         Inches(11), Inches(0.8), size=20, color=RGBColor(0xBD, 0xD7, 0xEE), align=PP_ALIGN.CENTER)

# ── Slide 2: Problem ──────────────────────────────────────────────────────────
s2 = prs.slides.add_slide(prs.slide_layouts[6])
solid_bg(s2, LIGHT_GRAY)
add_text(s2, 'The Problem', Inches(0.8), Inches(0.3), Inches(11), Inches(0.9),
         size=32, bold=True, color=DARK_BLUE)
bullets = [
    '📌  Teams waste 4+ hours/week searching for internal information',
    '📌  Knowledge silos cause duplicated work and missed deadlines',
    '📌  Existing tools lack intelligent context — they return files, not answers',
]
for i, b in enumerate(bullets):
    add_text(s2, b, Inches(0.8), Inches(1.3 + i * 1.5), Inches(11.5), Inches(1.2), size=18)

# ── Slide 3: Solution ─────────────────────────────────────────────────────────
s3 = prs.slides.add_slide(prs.slide_layouts[6])
solid_bg(s3, DARK_BLUE)
add_text(s3, 'Our Solution', Inches(0.8), Inches(0.3), Inches(11), Inches(0.9),
         size=32, bold=True, color=WHITE)
add_text(s3,
    'NovaTech is an AI-powered enterprise knowledge hub that surfaces the right '
    'information to the right person at the right time — reducing search time by 80%.',
    Inches(0.8), Inches(1.3), Inches(11.5), Inches(2),
    size=20, color=WHITE, wrap=True)

# ── Slide 4: Traction ─────────────────────────────────────────────────────────
s4 = prs.slides.add_slide(prs.slide_layouts[6])
solid_bg(s4, LIGHT_GRAY)
add_text(s4, 'Traction', Inches(0.8), Inches(0.3), Inches(11), Inches(0.9),
         size=32, bold=True, color=DARK_BLUE)
metrics = [('120+', 'Enterprise\nCustomers'), ('$1.8M', 'ARR'), ('94%', 'Retention\nRate')]
for i, (num, label) in enumerate(metrics):
    x = Inches(0.8 + i * 4.2)
    add_text(s4, num,   x, Inches(1.4), Inches(3.8), Inches(1.2), size=48, bold=True, color=MID_BLUE, align=PP_ALIGN.CENTER)
    add_text(s4, label, x, Inches(2.6), Inches(3.8), Inches(0.9), size=16, color=DARK_BLUE, align=PP_ALIGN.CENTER)

# ── Slide 5: Financials table ─────────────────────────────────────────────────
s5 = prs.slides.add_slide(prs.slide_layouts[6])
solid_bg(s5, LIGHT_GRAY)
add_text(s5, 'Financial Projections', Inches(0.8), Inches(0.3), Inches(11), Inches(0.8),
         size=32, bold=True, color=DARK_BLUE)
tbl = s5.shapes.add_table(4, 4, Inches(0.8), Inches(1.3), Inches(11.6), Inches(2.8)).table
for ci, h in enumerate(['', '2025', '2026E', '2027E']):
    c = tbl.cell(0, ci)
    c.text = h
    c.text_frame.paragraphs[0].runs[0].font.bold = True
    c.text_frame.paragraphs[0].runs[0].font.color.rgb = WHITE
    c.fill.solid(); c.fill.fore_color.rgb = DARK_BLUE
fin_data = [('ARR', '$1.8M', '$4.2M', '$9.5M'), ('Gross Margin', '68%', '72%', '76%'),
            ('Headcount', '24', '38', '60')]
for ri, row in enumerate(fin_data, start=1):
    for ci, val in enumerate(row):
        tbl.cell(ri, ci).text = val

# ── Slide 6: Ask ──────────────────────────────────────────────────────────────
s6 = prs.slides.add_slide(prs.slide_layouts[6])
solid_bg(s6, DARK_BLUE)
add_text(s6, 'The Ask', Inches(0.8), Inches(0.5), Inches(11), Inches(0.9),
         size=32, bold=True, color=WHITE)
add_text(s6, 'Raising $4M Series A', Inches(0.8), Inches(1.5), Inches(11), Inches(1),
         size=36, bold=True, color=ORANGE, align=PP_ALIGN.CENTER)
uses = ['40%  —  Engineering & Product', '30%  —  Sales & Marketing', '20%  —  Customer Success', '10%  —  Operations']
for i, u in enumerate(uses):
    add_text(s6, u, Inches(0.8), Inches(2.7 + i * 0.9), Inches(11), Inches(0.8), size=18, color=WHITE)

prs.save('/output/pitch_deck.pptx')
print("Pitch deck saved to /output/pitch_deck.pptx")
```

---

## Full example — Lecture / class slides

```python
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

prs = Presentation()
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
TEAL   = RGBColor(0x00, 0x70, 0x70)
DARK   = RGBColor(0x1A, 0x1A, 0x2E)
YELLOW = RGBColor(0xFF, 0xD7, 0x00)

def bg(slide, color): slide.background.fill.solid(); slide.background.fill.fore_color.rgb = color
def txt(slide, text, l, t, w, h, size=18, bold=False, color=None, align=PP_ALIGN.LEFT):
    tf = slide.shapes.add_textbox(l, t, w, h).text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]; p.alignment = align
    run = p.add_run(); run.text = text
    run.font.size = Pt(size); run.font.bold = bold
    if color: run.font.color.rgb = color

slide_data = [
    ('Introduction to Machine Learning',    'CS-301  |  Week 4  |  Dr. Smith', True),
    ('What is Machine Learning?',
     'ML is a subset of AI that enables computers to learn patterns from data without being explicitly programmed.\n\n'
     'Three main types:\n• Supervised Learning\n• Unsupervised Learning\n• Reinforcement Learning', False),
    ('Supervised Learning',
     '• Model learns from labelled training data\n• Predicts output for new inputs\n\n'
     'Examples:\n  — Email spam detection\n  — House price prediction\n  — Medical diagnosis', False),
    ('Key Terminology',
     'Feature — an input variable (column in a dataset)\n'
     'Label — the target output we want to predict\n'
     'Training set — data used to fit the model\n'
     'Test set — data used to evaluate performance\n'
     'Overfitting — model memorises training data, fails on new data', False),
    ('Summary & Next Steps',
     '✅ ML enables pattern recognition from data\n'
     '✅ Supervised learning uses labelled examples\n'
     '✅ Features and labels are the core building blocks\n\n'
     '📖 Next week: Decision Trees and Random Forests', False),
]

for i, (title, content, is_title_slide) in enumerate(slide_data):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    if is_title_slide:
        bg(slide, TEAL)
        txt(slide, title, Inches(1), Inches(2.2), Inches(11), Inches(1.5),
            size=40, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        txt(slide, content, Inches(1), Inches(3.9), Inches(11), Inches(0.8),
            size=18, color=YELLOW, align=PP_ALIGN.CENTER)
    else:
        bg(slide, WHITE)
        # Title bar
        bar = slide.shapes.add_shape(1, Inches(0), Inches(0), prs.slide_width, Inches(1.1))
        bar.fill.solid(); bar.fill.fore_color.rgb = TEAL
        bar.line.fill.background()
        txt(slide, title, Inches(0.3), Inches(0.1), Inches(12.5), Inches(0.9),
            size=26, bold=True, color=WHITE)
        txt(slide, content, Inches(0.5), Inches(1.3), Inches(12.3), Inches(5.8),
            size=17, color=DARK)
        # Slide number
        txt(slide, str(i + 1), Inches(12.5), Inches(6.9), Inches(0.8), Inches(0.5),
            size=12, color=TEAL, align=PP_ALIGN.RIGHT)

prs.save('/output/lecture_slides.pptx')
print(f"Lecture slides ({len(slide_data)} slides) saved to /output/lecture_slides.pptx")
```
