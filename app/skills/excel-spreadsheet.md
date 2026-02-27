---
name: excel-spreadsheet
description: Create Excel (.xlsx) spreadsheets — budgets, expense trackers, grade sheets, schedules, invoices, data tables, KPI dashboards. Use when user asks to create any Excel file, spreadsheet, or .xlsx file.
---

# Excel Spreadsheet Creation

Use `execute_code` with `language: "python"`. Always save to `/output/filename.xlsx`.

## Core imports and setup

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.styles.numbers import FORMAT_NUMBER_COMMA_SEP1

wb = Workbook()
ws = wb.active
ws.title = 'Sheet1'
```

## Writing data

```python
# Direct cell assignment
ws['A1'] = 'Product'
ws['B1'] = 'Quantity'
ws['C1'] = 'Price'
ws['D1'] = 'Total'

# Append rows (fastest for bulk data)
rows = [
    ('Widget A', 10, 25.00),
    ('Widget B', 5, 49.99),
    ('Widget C', 20, 12.50),
]
for product, qty, price in rows:
    ws.append([product, qty, price, f'=B{ws.max_row}*C{ws.max_row}'])
```

## Column widths and row heights

```python
ws.column_dimensions['A'].width = 20
ws.column_dimensions['B'].width = 12
ws.column_dimensions['C'].width = 12
ws.column_dimensions['D'].width = 14
ws.row_dimensions[1].height = 22   # header row height
```

## Styling: fonts, fills, borders, alignment

```python
# Reusable style objects
HEADER_FONT = Font(name='Calibri', bold=True, color='FFFFFF', size=12)
HEADER_FILL = PatternFill(fill_type='solid', fgColor='2F75B6')
HEADER_ALIGN = Alignment(horizontal='center', vertical='center', wrap_text=True)

BODY_FONT = Font(name='Calibri', size=11)
BODY_ALIGN_CENTER = Alignment(horizontal='center')
BODY_ALIGN_RIGHT = Alignment(horizontal='right')

THIN_BORDER = Border(
    left=Side(style='thin'),
    right=Side(style='thin'),
    top=Side(style='thin'),
    bottom=Side(style='thin'),
)

# Apply styles to header row
for cell in ws[1]:
    cell.font = HEADER_FONT
    cell.fill = HEADER_FILL
    cell.alignment = HEADER_ALIGN
    cell.border = THIN_BORDER

# Alternating row colours for readability
EVEN_FILL = PatternFill(fill_type='solid', fgColor='DCE6F1')
for row_idx in range(2, ws.max_row + 1):
    for cell in ws[row_idx]:
        cell.font = BODY_FONT
        cell.border = THIN_BORDER
        if row_idx % 2 == 0:
            cell.fill = EVEN_FILL
```

## Number formats

```python
from openpyxl.styles.numbers import FORMAT_NUMBER_COMMA_SEP1
for row in ws.iter_rows(min_row=2, min_col=3, max_col=4):
    for cell in row:
        cell.number_format = '#,##0.00'   # e.g. 1,250.00
# Percentage
ws['E2'].number_format = '0.0%'
# Date
ws['F2'].number_format = 'DD/MM/YYYY'
```

## Formulas

```python
last_row = ws.max_row
ws.append(['', '', 'TOTAL', f'=SUM(D2:D{last_row})'])  # sum total row
# Average
ws['E2'] = f'=AVERAGE(C2:C{last_row})'
# Conditional (IF)
ws['F2'] = '=IF(D2>100,"High","Low")'
# VLOOKUP
ws['G2'] = '=VLOOKUP(A2,Sheet2!A:B,2,0)'
```

## Freeze panes and auto-filter

```python
ws.freeze_panes = 'A2'          # freeze header row
ws.auto_filter.ref = ws.dimensions  # add dropdown filters on all columns
```

## Multiple sheets

```python
ws_summary = wb.active
ws_summary.title = 'Summary'

ws_details = wb.create_sheet('Details')
ws_charts = wb.create_sheet('Charts')

# Reference data across sheets
ws_summary['B2'] = '=SUM(Details!C2:C100)'
```

## Bar / Line chart

```python
from openpyxl.chart import BarChart, LineChart, Reference

# Bar chart
chart = BarChart()
chart.type = 'col'         # vertical bars; use 'bar' for horizontal
chart.title = 'Monthly Sales'
chart.y_axis.title = 'Revenue (£)'
chart.x_axis.title = 'Month'
chart.width = 18
chart.height = 12

data_ref = Reference(ws, min_col=4, min_row=1, max_row=ws.max_row)
cats_ref = Reference(ws, min_col=1, min_row=2, max_row=ws.max_row)
chart.add_data(data_ref, titles_from_data=True)
chart.set_categories(cats_ref)
ws.add_chart(chart, 'F2')
```

## Save

```python
wb.save('/output/spreadsheet.xlsx')
print("Saved to /output/spreadsheet.xlsx")
```

---

## Full example — Monthly budget tracker

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, Reference

wb = Workbook()
ws = wb.active
ws.title = 'Budget'

# ── Styles ────────────────────────────────────────────────────────────────────
H_FONT  = Font(bold=True, color='FFFFFF', size=12)
H_FILL  = PatternFill(fill_type='solid', fgColor='1F4E79')
H_ALIGN = Alignment(horizontal='center', vertical='center')
THIN    = Border(left=Side(style='thin'), right=Side(style='thin'),
                 top=Side(style='thin'), bottom=Side(style='thin'))
EVEN    = PatternFill(fill_type='solid', fgColor='D6E4F0')
TOTAL_FONT = Font(bold=True, size=12)
TOTAL_FILL = PatternFill(fill_type='solid', fgColor='FCE4D6')

# ── Headers ───────────────────────────────────────────────────────────────────
headers = ['Category', 'Planned (£)', 'Actual (£)', 'Difference (£)', 'Status']
ws.append(headers)
for cell in ws[1]:
    cell.font = H_FONT
    cell.fill = H_FILL
    cell.alignment = H_ALIGN
    cell.border = THIN
ws.row_dimensions[1].height = 22

# ── Data ──────────────────────────────────────────────────────────────────────
categories = [
    ('Rent',          1200, 1200),
    ('Groceries',      350,  410),
    ('Utilities',      120,   98),
    ('Transport',      150,  135),
    ('Dining Out',     100,  175),
    ('Entertainment',   80,   60),
    ('Gym',             40,   40),
    ('Clothing',        60,   85),
    ('Savings',        300,  300),
    ('Miscellaneous',   50,   72),
]

for i, (cat, planned, actual) in enumerate(categories, start=2):
    row_num = i
    ws.append([
        cat,
        planned,
        actual,
        f'=C{row_num}-B{row_num}',
        f'=IF(C{row_num}<=B{row_num},"✅ On track","⚠️ Over budget")',
    ])
    for cell in ws[row_num]:
        cell.border = THIN
        if row_num % 2 == 0:
            cell.fill = EVEN
    ws[f'B{row_num}'].number_format = '#,##0.00'
    ws[f'C{row_num}'].number_format = '#,##0.00'
    ws[f'D{row_num}'].number_format = '#,##0.00'

# ── Totals row ────────────────────────────────────────────────────────────────
total_row = ws.max_row + 1
ws.append([
    'TOTAL',
    f'=SUM(B2:B{total_row - 1})',
    f'=SUM(C2:C{total_row - 1})',
    f'=SUM(D2:D{total_row - 1})',
    f'=IF(D{total_row}<=0,"✅ Within budget","❌ Over budget")',
])
for cell in ws[total_row]:
    cell.font = TOTAL_FONT
    cell.fill = TOTAL_FILL
    cell.border = THIN
for col in ['B', 'C', 'D']:
    ws[f'{col}{total_row}'].number_format = '#,##0.00'

# ── Column widths ─────────────────────────────────────────────────────────────
widths = {'A': 20, 'B': 16, 'C': 16, 'D': 18, 'E': 18}
for col, w in widths.items():
    ws.column_dimensions[col].width = w

# ── Freeze header & auto-filter ───────────────────────────────────────────────
ws.freeze_panes = 'A2'
ws.auto_filter.ref = f'A1:E{total_row - 1}'

# ── Bar chart: Planned vs Actual ──────────────────────────────────────────────
chart = BarChart()
chart.type = 'col'
chart.title = 'Planned vs Actual Spending'
chart.y_axis.title = 'Amount (£)'
chart.width = 22
chart.height = 14

data = Reference(ws, min_col=2, max_col=3, min_row=1, max_row=total_row - 1)
cats = Reference(ws, min_col=1, min_row=2, max_row=total_row - 1)
chart.add_data(data, titles_from_data=True)
chart.set_categories(cats)
ws.add_chart(chart, 'G2')

wb.save('/output/budget_tracker.xlsx')
print("Budget tracker saved to /output/budget_tracker.xlsx")
```

---

## Full example — Student grade sheet

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

wb = Workbook()
ws = wb.active
ws.title = 'Grades'

# Header
headers = ['Student', 'Maths', 'English', 'Science', 'History', 'Average', 'Grade']
ws.append(headers)
for cell in ws[1]:
    cell.font = Font(bold=True, color='FFFFFF')
    cell.fill = PatternFill(fill_type='solid', fgColor='375623')
    cell.alignment = Alignment(horizontal='center')

# Student data
students = [
    ('Alice',  92, 88, 95, 79),
    ('Bob',    74, 81, 68, 85),
    ('Carol',  88, 91, 83, 90),
    ('David',  55, 62, 58, 60),
    ('Emma',   97, 94, 99, 96),
]

for i, (name, *scores) in enumerate(students, start=2):
    ws.append([name] + scores)
    row = i
    ws[f'F{row}'] = f'=AVERAGE(B{row}:E{row})'
    ws[f'F{row}'].number_format = '0.0'
    ws[f'G{row}'] = (
        f'=IF(F{row}>=90,"A",'
        f'IF(F{row}>=80,"B",'
        f'IF(F{row}>=70,"C",'
        f'IF(F{row}>=60,"D","F"))))'
    )

# Column widths
for col, w in zip('ABCDEFG', [18, 10, 10, 10, 10, 12, 10]):
    ws.column_dimensions[col].width = w

ws.freeze_panes = 'A2'
wb.save('/output/grade_sheet.xlsx')
print("Grade sheet saved to /output/grade_sheet.xlsx")
```
