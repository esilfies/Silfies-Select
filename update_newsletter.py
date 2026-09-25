#!/usr/bin/env python3
"""
Daily maintenance script for The Silfies Select newsletter.

This script makes SURGICAL text edits -- it never parses and rewrites
the whole document (that approach strips your hand-written indentation).
Instead it finds exactly the text that needs to change and edits only
that, leaving every other byte of the file untouched.

What it does, every time it's run:
1. Finds each event card (needs data-start="YYYY-MM-DD" and, for
   multi-day events, data-end="YYYY-MM-DD" on its opening <div class="event">
   tag).
2. Any event whose last day is before today is cut out of its month
   section and added as a new line at the TOP of the "Just Missed Out!"
   list at the bottom (most recently completed event first).
3. Any archive entry more than 2 weeks old is removed entirely.
4. Any month header left with zero events under it is removed.
5. The footer's "Last updated" line is stamped with today's date,
   keeping whatever capitalization/punctuation you're already using.

Run against your published HTML file (see the GitHub Actions workflow
for how this runs automatically every day).
"""

import re
import sys
from datetime import date, datetime, timedelta

HTML_PATH = "index.html"  # change if your file has a different name

# Matches one full event block: from its opening <div class="event" ...>
# tag through everything up to (but not including) whatever comes next --
# another event, a month divider, the past-section, or a comment. This
# works regardless of how many closing </div> tags or optional
# <p class="note"> lines are inside, because it never tries to count
# nesting depth -- it just looks for where the NEXT sibling begins.
EVENT_BLOCK_RE = re.compile(
    r'<div class="event"'
    r'(?P<attrs>[^>]*)>'
    r'(?P<inner>.*?)'
    r'(?=<div class="event"|<div class="month-divider"|<div class="past-section"|<!--)',
    re.DOTALL,
)

MONTH_DIVIDER_RE = re.compile(
    r'(?:<!--.*?-->\s*)?'  # optional preceding comment banner, e.g. <!-- === SEPTEMBER === -->
    r'<div class="month-divider"><h2>(\w+)</h2><div class="rule"></div></div>\s*'
)

NAME_RE = re.compile(r"<h3>(.*?)</h3>")
VENUE_RE = re.compile(r'<p class="venue">(.*?)</p>')
DATA_START_RE = re.compile(r'data-start="(\d{4}-\d{2}-\d{2})"')
DATA_END_RE = re.compile(r'data-end="(\d{4}-\d{2}-\d{2})"')


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def strip_tags(s):
    return re.sub(r"<.*?>", "", s).strip()


def format_range(start, end):
    """(date, date) -> 'Sep 5' / 'Sep 5-7' / 'Sep 29-Oct 2'"""
    if end is None or end == start:
        return start.strftime("%b %-d")
    if start.month == end.month:
        return f"{start.strftime('%b %-d')}\u2013{end.day}"
    return f"{start.strftime('%b %-d')}\u2013{end.strftime('%b %-d')}"


def main():
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    today = date.today()
    new_archive_lines = []  # (start_date, formatted <li> line), oldest first

    # --- Pass 1: find and remove past events -------------------------
    def maybe_strip(m):
        attrs = m.group("attrs")
        start_match = DATA_START_RE.search(attrs)
        if not start_match:
            return m.group(0)  # no date info -- leave it alone

        start = parse_date(start_match.group(1))
        end_match = DATA_END_RE.search(attrs)
        end = parse_date(end_match.group(1)) if end_match else start

        if end >= today:
            return m.group(0)  # still upcoming

        inner = m.group("inner")
        name_match = NAME_RE.search(inner)
        venue_match = VENUE_RE.search(inner)
        name = strip_tags(name_match.group(1)) if name_match else "Unknown event"
        venue = strip_tags(venue_match.group(1)) if venue_match else ""
        date_str = format_range(start, end)

        line = f'      <li data-date="{end.isoformat()}">{name} \u2014 {venue} <span>\u00b7 {date_str}</span></li>'
        new_archive_lines.append((end, line))
        return ""  # delete the whole block

    html = EVENT_BLOCK_RE.sub(maybe_strip, html)

    # --- Pass 2: drop any month-divider with nothing left under it ---
    def maybe_strip_divider(m):
        after = html[m.end():]
        next_event = after.find('<div class="event"')
        next_divider = after.find('<div class="month-divider"')
        next_past = after.find('<div class="past-section"')
        boundary = min(x for x in (next_event, next_divider, next_past) if x != -1)
        if next_event != -1 and next_event == boundary:
            return m.group(0)  # has at least one event -- keep it
        return ""  # nothing follows before the next divider/section -- drop it

    html = MONTH_DIVIDER_RE.sub(maybe_strip_divider, html)

    # --- Pass 3: insert newly-past events at the TOP of the archive --
    if new_archive_lines:
        new_archive_lines.sort(key=lambda pair: pair[0], reverse=True)  # newest first
        insertion = "\n".join(line for _, line in new_archive_lines)
        html = re.sub(
            r'(<div class="past-section">\s*<h2>[^<]*</h2>\s*<ul>\s*\n)',
            r"\1" + insertion.replace("\\", "\\\\") + "\n",
            html,
            count=1,
        )

    # --- Pass 4: drop archive entries older than 2 weeks --------------
    ARCHIVE_ITEM_RE = re.compile(
        r'\s*<li data-date="(\d{4}-\d{2}-\d{2})">.*?</li>\n?'
    )
    cutoff = today - timedelta(days=14)

    def maybe_strip_old_archive_item(m):
        item_date = parse_date(m.group(1))
        if item_date < cutoff:
            return ""  # older than 2 weeks -- drop it
        return m.group(0)

    html = ARCHIVE_ITEM_RE.sub(maybe_strip_old_archive_item, html)

    # --- Pass 5: stamp today's date in the footer ---------------------
    html = re.sub(
        r"(Last [Uu]pdated:?\s*)[A-Za-z]+ \d{1,2}, \d{4}",
        lambda m: m.group(1) + today.strftime("%B %-d, %Y"),
        html,
        count=1,
    )

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Pruned {len(new_archive_lines)} past event(s). "
          f"Footer stamped {today.isoformat()}. (Old archive entries "
          f"beyond 2 weeks were also cleared if any existed.)")


if __name__ == "__main__":
    main()
