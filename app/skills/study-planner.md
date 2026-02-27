---
name: study-planner
description: Create personalised study plans, exam revision schedules, weekly timetables, and subject trackers as Excel files. Use when a student asks to plan studies, prepare for exams, organise a revision schedule, or create a learning timetable.
---

# Study Planner Creation

Always produce an Excel file (`.xlsx`) using the `execute_code` tool with Python.
Save to `/output/study_plan.xlsx` (or a descriptive name the user provides).

## What to gather from the user (if not provided)

Before generating, ideally know:
- Subjects / modules to cover
- Exam / deadline dates
- Available study hours per day
- Start date for the plan
- Preferred language for labels (default to the user's language)

If details are missing, generate a realistic template the user can fill in.

---

## Core pattern — weekly schedule grid

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import date, timedelta

wb = Workbook()
ws = wb.active
ws.title = 'Weekly Schedule'

TIME_SLOTS = ['08:00', '09:00', '10:00', '11:00', '12:00',
              '13:00', '14:00', '15:00', '16:00', '17:00',
              '18:00', '19:00', '20:00']
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

# Header row (days)
ws['A1'] = 'Time'
for col, day in enumerate(DAYS, start=2):
    cell = ws.cell(row=1, column=col, value=day)
    cell.font = Font(bold=True, color='FFFFFF')
    cell.fill = PatternFill(fill_type='solid', fgColor='1F4E79')
    cell.alignment = Alignment(horizontal='center')

# Time column
for row, slot in enumerate(TIME_SLOTS, start=2):
    cell = ws.cell(row=row, column=1, value=slot)
    cell.font = Font(bold=True)
    cell.fill = PatternFill(fill_type='solid', fgColor='D6E4F0')
    cell.alignment = Alignment(horizontal='center')

# Column widths
ws.column_dimensions['A'].width = 10
for col in range(2, len(DAYS) + 2):
    ws.column_dimensions[get_column_letter(col)].width = 16

ws.freeze_panes = 'B2'
```

## Subject colour coding

```python
SUBJECT_COLOURS = {
    'Mathematics':   'FF6B6B',   # red
    'Physics':       '4ECDC4',   # teal
    'Chemistry':     'FFE66D',   # yellow
    'Biology':       '95E1D3',   # mint
    'History':       'F38181',   # salmon
    'English':       'A8D8EA',   # light blue
    'Programming':   'B8B8FF',   # lavender
    'Economics':     'FCEADE',   # peach
    'Break':         'EEEEEE',   # light gray
}

def fill_cell(ws, row, col, subject, text=None):
    cell = ws.cell(row=row, column=col)
    cell.value = text or subject
    hex_color = SUBJECT_COLOURS.get(subject, 'F5F5F5')
    cell.fill = PatternFill(fill_type='solid', fgColor=hex_color)
    cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    cell.font = Font(size=10)
    THIN = Border(left=Side(style='thin'), right=Side(style='thin'),
                  top=Side(style='thin'),  bottom=Side(style='thin'))
    cell.border = THIN
```

---

## Full example — 2-week exam revision plan

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import date, timedelta

SUBJECTS = ['Mathematics', 'Physics', 'Chemistry', 'English', 'Break']
COLOURS  = {
    'Mathematics': '4472C4', 'Physics': '70AD47',
    'Chemistry':   'ED7D31', 'English': 'FF0000',
    'Break':       'D9D9D9',
}

def style(cell, bg=None, bold=False, center=False, font_color='000000', size=11):
    if bg:
        cell.fill = PatternFill(fill_type='solid', fgColor=bg)
    cell.font = Font(bold=bold, color=font_color, size=size)
    if center:
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    cell.border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'),  bottom=Side(style='thin'),
    )

wb = Workbook()
ws = wb.active
ws.title = 'Revision Plan'

# ── Build a 2-week grid ───────────────────────────────────────────────────────
start_date = date(2026, 3, 2)   # first Monday
time_slots = ['08:00-09:30', '09:30-11:00', '11:15-12:45',
              'Lunch', '14:00-15:30', '15:30-17:00', '17:15-18:45', 'Evening Review']

# Generate 14 days
all_days = [start_date + timedelta(days=i) for i in range(14)]

# Column 0: time labels
ws['A1'] = 'Time Slot'
style(ws['A1'], bg='1F4E79', bold=True, center=True, font_color='FFFFFF', size=12)
ws.column_dimensions['A'].width = 16

for row_i, slot in enumerate(time_slots, start=2):
    c = ws.cell(row=row_i, column=1, value=slot)
    style(c, bg='D6E4F0', bold=True, center=True)
ws.row_dimensions[1].height = 28

# Day columns
# Assign subjects in a realistic rotation
schedule = {
    ('Mathematics',): [0, 3],     # Mon + Thu
    ('Physics',):     [1, 4],     # Tue + Fri
    ('Chemistry',):   [2, 5],     # Wed + Sat
    ('English',):     [6],        # Sun light session
}

for col_i, day in enumerate(all_days, start=2):
    day_label = f"{day.strftime('%A')}\n{day.strftime('%d %b')}"
    header_cell = ws.cell(row=1, column=col_i, value=day_label)
    style(header_cell, bg='1F4E79', bold=True, center=True, font_color='FFFFFF', size=11)
    ws.column_dimensions[get_column_letter(col_i)].width = 15

    day_of_week = day.weekday()
    # Determine subject for this day
    day_subject = 'Break'
    for subjects, days in schedule.items():
        if day_of_week in days:
            day_subject = subjects[0]
            break

    for row_i, slot in enumerate(time_slots, start=2):
        if slot == 'Lunch':
            subj = 'Break'
        elif slot == 'Evening Review':
            subj = day_subject if day_subject != 'Break' else 'Break'
        else:
            subj = day_subject
        text = subj if subj != 'Break' else '—'
        c = ws.cell(row=row_i, column=col_i, value=text)
        style(c, bg=COLOURS.get(subj, 'F5F5F5'), center=True)

ws.freeze_panes = 'B2'

# ── Legend sheet ──────────────────────────────────────────────────────────────
ws2 = wb.create_sheet('Legend & Tips')
ws2['A1'] = 'Subject'
ws2['B1'] = 'Exam Date'
ws2['C1'] = 'Topics to Cover'
for cell in ws2[1]:
    style(cell, bg='1F4E79', bold=True, center=True, font_color='FFFFFF')

exam_info = [
    ('Mathematics', '15 Mar 2026', 'Calculus, Linear Algebra, Statistics'),
    ('Physics',     '17 Mar 2026', 'Mechanics, Thermodynamics, Electromagnetism'),
    ('Chemistry',   '19 Mar 2026', 'Organic Chemistry, Reactions, Periodic Table'),
    ('English',     '22 Mar 2026', 'Essay writing, Literature analysis, Grammar'),
]
for row_data in exam_info:
    ws2.append(row_data)
    for cell in ws2[ws2.max_row]:
        style(cell, bg=COLOURS.get(row_data[0], 'FFFFFF'), center=True)

ws2.column_dimensions['A'].width = 16
ws2.column_dimensions['B'].width = 14
ws2.column_dimensions['C'].width = 45

# ── Study tips ────────────────────────────────────────────────────────────────
ws2['A' + str(ws2.max_row + 2)] = '📚 Study Tips'
ws2['A' + str(ws2.max_row)].font = Font(bold=True, size=13)
tips = [
    '• Use Pomodoro: 25 min focus → 5 min break → repeat × 4 → 15 min break',
    '• Active recall: close notes, write everything you remember, then check',
    '• Spaced repetition: review topics after 1 day, 3 days, 1 week, 2 weeks',
    '• Past papers are your best friend — do at least 2 per subject under timed conditions',
    '• Sleep ≥ 7 hours: memory consolidation happens during sleep',
]
for tip in tips:
    ws2.append([tip])

wb.save('/output/study_plan.xlsx')
print("Study plan saved to /output/study_plan.xlsx")
```

---

## Pomodoro tracker sheet

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

wb = Workbook()
ws = wb.active
ws.title = 'Pomodoro Tracker'

ws.append(['Date', 'Subject', 'Session #', 'Duration', 'Topic Covered', 'Notes'])
for cell in ws[1]:
    cell.font = Font(bold=True, color='FFFFFF')
    cell.fill = PatternFill(fill_type='solid', fgColor='E74C3C')
    cell.alignment = Alignment(horizontal='center')

# Pre-fill a week of example entries
from datetime import date, timedelta
today = date.today()
subjects = ['Mathematics', 'Physics', 'Chemistry', 'English']
for day_offset in range(5):
    d = today + timedelta(days=day_offset)
    subj = subjects[day_offset % len(subjects)]
    for session in range(1, 5):
        ws.append([d.strftime('%d/%m/%Y'), subj, session, '25 min', '', ''])

for col, width in zip('ABCDEF', [14, 16, 12, 12, 30, 30]):
    ws.column_dimensions[col].width = width

wb.save('/output/pomodoro_tracker.xlsx')
print("Tracker saved to /output/pomodoro_tracker.xlsx")
```
