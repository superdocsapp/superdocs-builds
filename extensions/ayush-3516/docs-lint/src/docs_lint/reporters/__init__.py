"""Output formats.

Three, for three audiences: a person reading a terminal, another program, and GitHub's code
scanning view. All three derive their claims from the same `RunSummary`, so none of them can say
something the others would not.
"""

from .json_report import render_json
from .sarif import render_sarif
from .terminal import render_terminal

__all__ = ["render_json", "render_sarif", "render_terminal"]
