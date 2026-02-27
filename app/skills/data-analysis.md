---
name: data-analysis
description: Analyse data and create charts, graphs, visualisations. Use for statistical analysis, plotting with matplotlib or seaborn, data exploration with pandas, or when user provides numbers/data and asks for visual output or statistics.
---

# Data Analysis and Visualisation

Use `execute_code` with `language: "python"`. Save charts to `/output/filename.png`.
For tabular output save to `/output/filename.xlsx` (see excel-spreadsheet skill).

## Core imports

```python
import matplotlib
matplotlib.use('Agg')            # must be before pyplot import
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

sns.set_theme(style='whitegrid', palette='muted')   # nicer defaults
```

## Always save — never call plt.show()

```python
plt.savefig('/output/chart.png', dpi=150, bbox_inches='tight')
plt.close()
```

## Line chart

```python
fig, ax = plt.subplots(figsize=(10, 5))
months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun']
revenue = [12000, 15000, 13500, 18000, 22000, 20500]
costs   = [ 8000,  9000,  8500, 10000, 12000, 11500]

ax.plot(months, revenue, marker='o', linewidth=2, label='Revenue', color='#2196F3')
ax.plot(months, costs,   marker='s', linewidth=2, label='Costs',   color='#FF5722')
ax.fill_between(months, costs, revenue, alpha=0.12, color='#4CAF50', label='Profit margin')

ax.set_title('Revenue vs Costs — H1 2026', fontsize=14, fontweight='bold', pad=15)
ax.set_xlabel('Month')
ax.set_ylabel('Amount (£)')
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'£{x:,.0f}'))
ax.legend()
ax.grid(True, alpha=0.4)
fig.tight_layout()
plt.savefig('/output/revenue_chart.png', dpi=150, bbox_inches='tight')
plt.close()
```

## Bar chart

```python
categories = ['Marketing', 'Engineering', 'Sales', 'Support', 'HR']
values     = [42000, 118000, 76000, 33000, 21000]
colors     = ['#3498DB', '#2ECC71', '#E74C3C', '#F39C12', '#9B59B6']

fig, ax = plt.subplots(figsize=(9, 5))
bars = ax.bar(categories, values, color=colors, edgecolor='white', linewidth=0.8)

# Value labels on bars
for bar in bars:
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 500,
            f'£{bar.get_height():,.0f}', ha='center', va='bottom', fontsize=10)

ax.set_title('Department Budget Allocation', fontsize=14, fontweight='bold')
ax.set_ylabel('Budget (£)')
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'£{x/1000:.0f}K'))
fig.tight_layout()
plt.savefig('/output/bar_chart.png', dpi=150, bbox_inches='tight')
plt.close()
```

## Pie / donut chart

```python
labels = ['Rent', 'Salaries', 'Software', 'Marketing', 'Other']
sizes  = [30, 45, 10, 10, 5]
explode = (0.03,) * len(labels)

fig, ax = plt.subplots(figsize=(8, 6))
wedges, texts, autotexts = ax.pie(
    sizes, labels=labels, autopct='%1.1f%%', explode=explode,
    colors=sns.color_palette('Set2'), startangle=140,
    wedgeprops=dict(width=0.65),   # donut style
)
for at in autotexts:
    at.set_fontsize(10)
ax.set_title('Cost Breakdown', fontsize=14, fontweight='bold')
fig.tight_layout()
plt.savefig('/output/pie_chart.png', dpi=150, bbox_inches='tight')
plt.close()
```

## Histogram

```python
np.random.seed(42)
scores = np.random.normal(loc=72, scale=12, size=200).clip(0, 100)

fig, ax = plt.subplots(figsize=(9, 5))
ax.hist(scores, bins=20, color='#3498DB', edgecolor='white', alpha=0.85)
ax.axvline(scores.mean(), color='red', linestyle='--', linewidth=1.5, label=f'Mean: {scores.mean():.1f}')
ax.set_title('Exam Score Distribution (n=200)', fontsize=14, fontweight='bold')
ax.set_xlabel('Score')
ax.set_ylabel('Count')
ax.legend()
fig.tight_layout()
plt.savefig('/output/histogram.png', dpi=150, bbox_inches='tight')
plt.close()
```

## Scatter plot with regression line

```python
np.random.seed(0)
hours_studied = np.random.uniform(1, 10, 60)
exam_score = 45 + 5 * hours_studied + np.random.normal(0, 5, 60)

fig, ax = plt.subplots(figsize=(8, 6))
ax.scatter(hours_studied, exam_score, alpha=0.7, color='#2196F3', edgecolors='white', s=70)

# Regression line
m, b = np.polyfit(hours_studied, exam_score, 1)
x_line = np.linspace(1, 10, 100)
ax.plot(x_line, m * x_line + b, 'r--', linewidth=2, label=f'y = {m:.1f}x + {b:.1f}')

ax.set_title('Hours Studied vs Exam Score', fontsize=14, fontweight='bold')
ax.set_xlabel('Hours Studied per Day')
ax.set_ylabel('Exam Score')
ax.legend()
fig.tight_layout()
plt.savefig('/output/scatter.png', dpi=150, bbox_inches='tight')
plt.close()
```

## Seaborn heatmap (correlation matrix)

```python
import seaborn as sns

df = pd.DataFrame({
    'Revenue': np.random.normal(100, 15, 50),
    'Ad Spend': np.random.normal(20, 5, 50),
    'Customers': np.random.normal(500, 80, 50),
    'Churn %': np.random.normal(3, 1, 50),
    'NPS': np.random.normal(40, 10, 50),
})

fig, ax = plt.subplots(figsize=(8, 6))
sns.heatmap(df.corr(), annot=True, fmt='.2f', cmap='RdYlGn',
            center=0, linewidths=0.5, ax=ax)
ax.set_title('Correlation Matrix', fontsize=14, fontweight='bold')
fig.tight_layout()
plt.savefig('/output/heatmap.png', dpi=150, bbox_inches='tight')
plt.close()
```

## Multi-panel figure (subplots)

```python
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('Sales Dashboard — Q1 2026', fontsize=16, fontweight='bold', y=1.01)

months = ['Jan', 'Feb', 'Mar']
# Top-left: bar chart
axes[0, 0].bar(months, [42, 55, 61], color='#2196F3')
axes[0, 0].set_title('Monthly Units Sold')

# Top-right: line chart
axes[0, 1].plot(months, [18000, 23000, 27000], marker='o', color='#4CAF50')
axes[0, 1].set_title('Monthly Revenue (£)')

# Bottom-left: pie chart
axes[1, 0].pie([35, 30, 20, 15], labels=['Online', 'Retail', 'Partner', 'Direct'],
               autopct='%1.0f%%', colors=sns.color_palette('Set2'))
axes[1, 0].set_title('Sales Channel Split')

# Bottom-right: text KPI box
axes[1, 1].axis('off')
kpis = [('Total Revenue', '£68,000'), ('Units Sold', '158'), ('Avg Order', '£430'), ('NPS', '61')]
for i, (label, value) in enumerate(kpis):
    axes[1, 1].text(0.05, 0.85 - i * 0.22, f'{label}:', fontsize=11, color='gray', transform=axes[1, 1].transAxes)
    axes[1, 1].text(0.55, 0.85 - i * 0.22, value,     fontsize=14, fontweight='bold', transform=axes[1, 1].transAxes)
axes[1, 1].set_title('Key Metrics')

plt.tight_layout()
plt.savefig('/output/dashboard.png', dpi=150, bbox_inches='tight')
plt.close()
print("Dashboard saved to /output/dashboard.png")
```

## Pandas quick stats

```python
df = pd.DataFrame({
    'Name':   ['Alice', 'Bob', 'Carol', 'David', 'Emma'],
    'Score':  [92, 74, 88, 55, 97],
    'Hours':  [8.5, 5.0, 7.2, 3.1, 9.8],
    'Passed': [True, True, True, False, True],
})

print(df.describe())          # count, mean, std, min, quartiles, max
print(df['Score'].mean())     # average score
print(df.groupby('Passed')['Score'].mean())  # mean by group
print(df[df['Score'] >= 80])  # filter rows
```

## Save stats + data to Excel

```python
# Combine analysis and chart in one call
with pd.ExcelWriter('/output/analysis.xlsx', engine='openpyxl') as writer:
    df.to_excel(writer, sheet_name='Raw Data', index=False)
    df.describe().to_excel(writer, sheet_name='Statistics')
print("Saved to /output/analysis.xlsx")
```
