"""HTML rendering layer for weekly audit reports."""

from __future__ import annotations

from typing import Any, Mapping


def render_html_report(calendar_data: Mapping[str, Any], title: str = "XNAT Audit Report") -> str:
    """Render a calendar-style HTML report."""
    # TODO: use Jinja2 templates from reporting/templates/.
    return f"""<!DOCTYPE html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <title>{title}</title>
  </head>
  <body>
    <h1>{title}</h1>
    <p>Report rendering will be implemented here.</p>
  </body>
</html>
"""
