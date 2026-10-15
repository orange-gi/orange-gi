"""Dependency-free annual SVG activity cards; dates are used as supplied."""

import calendar
from datetime import date, timedelta
from html import escape


def compact(number):
    for unit, divisor in (("B", 10**9), ("M", 10**6), ("K", 10**3)):
        if number >= divisor:
            return f"{number / divisor:.2f}".rstrip("0").rstrip(".") + unit
    return str(number)


def render_activity_card(*, title, year, days, coverage_end, subtitle, footer,
                         unit="tokens", color="#388bfd", dark_color="#58a6ff"):
    """Return an 860x260 SVG; days maps ISO dates to nonnegative integer counts.

    Missing dates through coverage_end mean 'no reported activity'. Later dates
    are unreported coverage, visually distinct from reported zero values.
    Callers validate inputs and supply their own summary and source wording.
    """
    start, end = date(year, 1, 1), date(year + 1, 1, 1)
    grid_start = start - timedelta(days=(start.weekday() + 1) % 7)
    coverage_end = date.fromisoformat(coverage_end)
    peak = max((v for k, v in days.items() if date.fromisoformat(k).year == year), default=0)
    esc = escape
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="860" height="260" viewBox="0 0 860 260" role="img" aria-labelledby="title desc">',
        f'<title id="title">{esc(title)} · {year}</title>',
        f'<desc id="desc">{esc(subtitle)}. Latest reported date: {coverage_end}. Missing dates mean no reported activity; dates after that are not covered.</desc>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;fill:#1f2328}.muted{fill:#656d76}.frame{fill:#fff;stroke:#d1d9e0}.missing{fill:#ebedf0}.uncovered{fill:#fff;stroke:#d1d9e0;stroke-dasharray:2 2}.zero{fill:#ebedf0;stroke:#8c959f}',
        f'.active{{fill:{esc(color, quote=True)}}}',
        '@media(prefers-color-scheme:dark){text{fill:#e6edf3}.muted{fill:#9198a1}.frame{fill:#0d1117;stroke:#30363d}.missing{fill:#21262d}.uncovered{fill:#0d1117;stroke:#30363d}.zero{fill:#21262d;stroke:#9198a1}',
        f'.active{{fill:{esc(dark_color, quote=True)}}}' + '}</style>',
        '<rect class="frame" x="0.5" y="0.5" width="859" height="259" rx="12"/>',
        f'<text x="24" y="38" font-size="20" font-weight="600">{esc(title)}</text>',
        f'<text class="muted" x="832" y="37" text-anchor="end" font-size="13">{year}</text>',
        f'<text x="24" y="67" font-size="14">{esc(subtitle)}</text>',
    ]
    for month in range(1, 13):
        week = (date(year, month, 1) - grid_start).days // 7
        parts.append(f'<text class="muted" x="{67 + week * 14}" y="100" font-size="11">{calendar.month_abbr[month]}</text>')
    for row, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        parts.append(f'<text class="muted" x="24" y="{121 + row * 14}" font-size="10">{label}</text>')
    for offset in range((end - start).days):
        day = start + timedelta(days=offset)
        key = day.isoformat()
        value = days.get(key)
        opacity = 1
        if day > coverage_end:
            css, label = "uncovered", f"{key}: not covered"
        elif value is None:
            css, label = "missing", f"{key}: no reported activity"
        elif value == 0:
            css, label = "zero", f"{key}: 0 {unit} reported"
        else:
            css, label = "active", f"{key}: {value:,} {unit}"
            # Discrete levels keep low-usage days visible next to very large days.
            opacity = (0.3, 0.5, 0.75, 1)[min(3, int(value / peak * 4))]
        delta = (day - grid_start).days
        parts.append(f'<rect class="{css}" x="{67 + delta // 7 * 14}" y="{112 + delta % 7 * 14}" width="10" height="10" rx="2" fill-opacity="{opacity}"><title>{esc(label)}</title></rect>')
    parts.append(f'<text class="muted" x="24" y="238" font-size="12">{esc(footer)}</text>')
    parts.append('<text class="muted" x="688" y="238" font-size="11">Less</text>')
    for i, opacity in enumerate((0.3, 0.5, 0.75, 1)):
        parts.append(f'<rect class="active" x="{724 + i * 14}" y="229" width="10" height="10" rx="2" fill-opacity="{opacity}"/>')
    parts.extend(['<text class="muted" x="786" y="238" font-size="11">More</text>', '</svg>'])
    return "\n".join(parts) + "\n"
