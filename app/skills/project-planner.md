---
name: project-planner
description: Create project plans, Gantt charts, task trackers, and milestone timelines as Excel files. Use when a user asks to plan a project, create a project timeline, build a Gantt chart, or organise tasks with deadlines.
---

# Project Planner & Gantt Chart

Use `execute_code` with `language: "python"`. Save to `/output/project_plan.xlsx`.

## Core pattern — Gantt chart in Excel

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import date, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
wb = Workbook()
ws = wb.active
ws.title = 'Gantt Chart'

HEADER_FILL  = PatternFill(fill_type='solid', fgColor='1F4E79')
HEADER_FONT  = Font(bold=True, color='FFFFFF', size=11)
BAR_FILL     = PatternFill(fill_type='solid', fgColor='2E75B6')
DONE_FILL    = PatternFill(fill_type='solid', fgColor='70AD47')
WEEKEND_FILL = PatternFill(fill_type='solid', fgColor='F2F2F2')
TODAY_FILL   = PatternFill(fill_type='solid', fgColor='FFD700')
THIN = Border(
    left=Side(style='thin'), right=Side(style='thin'),
    top=Side(style='thin'),  bottom=Side(style='thin'),
)
```

## Task list columns

```python
# Fixed columns: Task | Owner | Start | End | % Done | Status
ws.column_dimensions['A'].width = 28  # Task
ws.column_dimensions['B'].width = 14  # Owner
ws.column_dimensions['C'].width = 12  # Start
ws.column_dimensions['D'].width = 12  # End
ws.column_dimensions['E'].width = 10  # % Done
ws.column_dimensions['F'].width = 12  # Status

headers = ['Task', 'Owner', 'Start', 'End', '% Done', 'Status']
for col_i, h in enumerate(headers, start=1):
    cell = ws.cell(row=1, column=col_i, value=h)
    cell.font = HEADER_FONT
    cell.fill = HEADER_FILL
    cell.alignment = Alignment(horizontal='center')
    cell.border = THIN
ws.row_dimensions[1].height = 22
```

---

## Full example — Software project Gantt (8 weeks)

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import date, timedelta

# ── Tasks ─────────────────────────────────────────────────────────────────────
tasks = [
    # (Phase, Task, Owner, start_offset_days, duration_days, pct_done, status)
    ('📋 Planning',  'Requirements gathering',  'Alice',  0,  5,  100, 'Done'),
    ('📋 Planning',  'Technical specification', 'Alice',  3,  4,  100, 'Done'),
    ('📋 Planning',  'Architecture design',     'Bob',    5,  5,   80, 'In Progress'),
    ('🔨 Dev',       'Database schema',         'Bob',   10,  3,   60, 'In Progress'),
    ('🔨 Dev',       'Backend API',             'Carol', 12, 10,   20, 'In Progress'),
    ('🔨 Dev',       'Frontend UI',             'David', 15, 12,    0, 'Not Started'),
    ('🔨 Dev',       'Auth & permissions',      'Carol', 14,  5,    0, 'Not Started'),
    ('🧪 Testing',   'Unit tests',              'Emma',  22,  4,    0, 'Not Started'),
    ('🧪 Testing',   'Integration tests',       'Emma',  24,  5,    0, 'Not Started'),
    ('🧪 Testing',   'UAT with client',         'Alice', 28,  4,    0, 'Not Started'),
    ('🚀 Launch',    'Production deployment',   'Bob',   32,  2,    0, 'Not Started'),
    ('🚀 Launch',    'Monitoring & handover',   'Bob',   33,  3,    0, 'Not Started'),
]

STATUS_COLOURS = {
    'Done':        '70AD47',
    'In Progress': '2E75B6',
    'Not Started': 'BFBFBF',
    'Blocked':     'FF0000',
}

PROJECT_START = date(2026, 3, 2)
TIMELINE_DAYS = 40

wb = Workbook()
ws = wb.active
ws.title = 'Gantt'

THIN = Border(left=Side(style='thin'), right=Side(style='thin'),
              top=Side(style='thin'),  bottom=Side(style='thin'))

# ── Fixed columns ─────────────────────────────────────────────────────────────
FIXED_COLS = 6
col_widths = [32, 14, 12, 12, 10, 14]
fixed_hdrs = ['Task', 'Owner', 'Start', 'End', '% Done', 'Status']
for ci, (hdr, w) in enumerate(zip(fixed_hdrs, col_widths), start=1):
    cell = ws.cell(row=1, column=ci, value=hdr)
    cell.font = Font(bold=True, color='FFFFFF', size=11)
    cell.fill = PatternFill(fill_type='solid', fgColor='1F4E79')
    cell.alignment = Alignment(horizontal='center', vertical='center')
    cell.border = THIN
    ws.column_dimensions[get_column_letter(ci)].width = w
ws.row_dimensions[1].height = 24

# ── Date header row ───────────────────────────────────────────────────────────
today = date.today()
for day_i in range(TIMELINE_DAYS):
    d = PROJECT_START + timedelta(days=day_i)
    col = FIXED_COLS + 1 + day_i
    cell = ws.cell(row=1, column=col, value=d.strftime('%d\n%b'))
    cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    cell.border = THIN
    ws.column_dimensions[get_column_letter(col)].width = 4.2
    if d == today:
        cell.fill = PatternFill(fill_type='solid', fgColor='FFD700')
        cell.font = Font(bold=True, size=8)
    elif d.weekday() >= 5:  # weekend
        cell.fill = PatternFill(fill_type='solid', fgColor='E8E8E8')
        cell.font = Font(size=8, color='999999')
    else:
        cell.fill = PatternFill(fill_type='solid', fgColor='2E75B6')
        cell.font = Font(bold=True, size=8, color='FFFFFF')

# ── Task rows ─────────────────────────────────────────────────────────────────
current_phase = None
row = 2
for phase, task_name, owner, start_off, dur, pct, status in tasks:
    # Phase separator row
    if phase != current_phase:
        current_phase = phase
        phase_cell = ws.cell(row=row, column=1, value=phase)
        phase_cell.font = Font(bold=True, size=11, color='FFFFFF')
        phase_cell.fill = PatternFill(fill_type='solid', fgColor='404040')
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=FIXED_COLS + TIMELINE_DAYS)
        ws.row_dimensions[row].height = 18
        row += 1

    task_start = PROJECT_START + timedelta(days=start_off)
    task_end   = task_start + timedelta(days=dur - 1)
    bar_colour = STATUS_COLOURS.get(status, 'BFBFBF')

    # Fixed info cells
    info = [task_name, owner, task_start.strftime('%d %b'), task_end.strftime('%d %b'), f'{pct}%', status]
    for ci, val in enumerate(info, start=1):
        cell = ws.cell(row=row, column=ci, value=val)
        cell.font = Font(size=10)
        cell.border = THIN
        cell.alignment = Alignment(horizontal='center' if ci > 1 else 'left', vertical='center')

    # Gantt bar cells
    for day_i in range(TIMELINE_DAYS):
        d = PROJECT_START + timedelta(days=day_i)
        col = FIXED_COLS + 1 + day_i
        cell = ws.cell(row=row, column=col, value='')
        cell.border = THIN
        if task_start <= d <= task_end:
            cell.fill = PatternFill(fill_type='solid', fgColor=bar_colour)
        elif d.weekday() >= 5:
            cell.fill = PatternFill(fill_type='solid', fgColor='F2F2F2')

    ws.row_dimensions[row].height = 18
    row += 1

ws.freeze_panes = f'{get_column_letter(FIXED_COLS + 1)}2'

# ── Summary sheet ─────────────────────────────────────────────────────────────
ws2 = wb.create_sheet('Summary')
ws2.append(['Project', 'AI Platform v2.0'])
ws2.append(['Start Date', PROJECT_START.strftime('%d %B %Y')])
ws2.append(['Target End', (PROJECT_START + timedelta(days=TIMELINE_DAYS)).strftime('%d %B %Y')])
ws2.append(['Total Tasks', len(tasks)])
ws2.append(['Completed', sum(1 for t in tasks if t[6] == 'Done')])
ws2.append(['In Progress', sum(1 for t in tasks if t[6] == 'In Progress')])
ws2.append(['Not Started', sum(1 for t in tasks if t[6] == 'Not Started')])
overall_pct = sum(t[5] for t in tasks) / len(tasks)
ws2.append(['Overall Progress', f'{overall_pct:.0f}%'])
for cell in ws2['A']:
    cell.font = Font(bold=True)
ws2.column_dimensions['A'].width = 18
ws2.column_dimensions['B'].width = 24

wb.save('/output/project_plan.xlsx')
print(f"Gantt chart saved — {len(tasks)} tasks across {TIMELINE_DAYS} days")
```

---

## Simple task tracker (no Gantt)

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from datetime import date

wb = Workbook()
ws = wb.active
ws.title = 'Task Tracker'

headers = ['#', 'Task', 'Assigned To', 'Priority', 'Due Date', 'Status', 'Notes']
ws.append(headers)
for cell in ws[1]:
    cell.font = Font(bold=True, color='FFFFFF')
    cell.fill = PatternFill(fill_type='solid', fgColor='2F75B6')
    cell.alignment = Alignment(horizontal='center')

tasks = [
    (1, 'Set up project repository', 'Alex', 'High',   '2026-03-05', 'Done',        ''),
    (2, 'Design database schema',    'Sam',  'High',   '2026-03-08', 'In Progress', 'Needs review'),
    (3, 'Write API documentation',   'Alex', 'Medium', '2026-03-12', 'Not Started', ''),
    (4, 'Create test plan',          'Jamie','Medium', '2026-03-10', 'Not Started', ''),
    (5, 'Stakeholder presentation',  'Sam',  'High',   '2026-03-15', 'Not Started', 'Prepare slides'),
]
STATUS_BG = {'Done': 'E2EFDA', 'In Progress': 'DDEBF7', 'Not Started': 'FFF2CC', 'Blocked': 'FCE4D6'}
for task in tasks:
    ws.append(list(task))
    bg = STATUS_BG.get(task[5], 'FFFFFF')
    for cell in ws[ws.max_row]:
        cell.fill = PatternFill(fill_type='solid', fgColor=bg)
        cell.alignment = Alignment(horizontal='center' if cell.column > 1 else 'left')

ws.column_dimensions['A'].width = 5
ws.column_dimensions['B'].width = 32
for col in 'CDEFG':
    ws.column_dimensions[col].width = 16
ws.auto_filter.ref = ws.dimensions
ws.freeze_panes = 'A2'

wb.save('/output/task_tracker.xlsx')
print("Task tracker saved to /output/task_tracker.xlsx")
```
