import pytest

SAMPLE_TRANSCRIPT = """\
Call with Acme Robotics Inc. -- Sales Debrief Interview

Rep: Thanks for taking the time. Why did you ultimately choose our platform over Comp Corp?
Customer (Jane, VP Eng): Comp Corp's pricing was actually cheaper, about 15% less,
but their API rate limits were a dealbreaker for our real-time pipeline.
Rep: Got it. Any objections along the way?
Customer: We were worried about onboarding time, but your team's live demo settled that.
Rep: What ultimately sealed the deal?
Customer: Honestly, the real-time streaming support was the deciding factor. Comp Corp
just couldn't do it at the throughput we needed.
"""

# A debrief that fully satisfies the schema, with evidence quotes that DO appear
# (verbatim, modulo whitespace) in SAMPLE_TRANSCRIPT above.
VALID_DEBRIEF_HTML = """
<h1>Win/Loss Debrief -- DEAL-2025Q4-001</h1>
<table><tr><td>Deal Code</td><td>Quarter</td><td>Segment</td><td>Outcome</td></tr>
<tr><td>DEAL-2025Q4-001</td><td>2025Q4</td><td>Mid-Market</td><td>WIN</td></tr></table>

<h2>Why We Won or Lost</h2>
<p>The customer chose us primarily for real-time streaming throughput.</p>
<blockquote data-evidence="true">the real-time streaming support was the deciding factor</blockquote>

<h2>Competitors Present</h2>
<table>
<tr><th>Competitor</th><th>Role/Context</th><th>Evidence</th></tr>
<tr><td>Comp Corp</td><td>Incumbent evaluated on price</td>
<td><blockquote data-evidence="true">Comp Corp's pricing was actually cheaper, about 15% less, but their API rate limits were a dealbreaker for our real-time pipeline.</blockquote></td></tr>
</table>

<h2>Pricing Dynamics</h2>
<p>Comp Corp undercut on price but lost on capability.</p>
<blockquote data-evidence="true">Comp Corp's pricing was actually cheaper, about 15% less</blockquote>

<h2>Objections Raised</h2>
<table>
<tr><th>Objection</th><th>Response</th><th>Resolved?</th><th>Evidence</th></tr>
<tr><td>Onboarding time</td><td>Live demo</td><td>Yes</td>
<td><blockquote data-evidence="true">your team's live demo settled that</blockquote></td></tr>
</table>

<h2>Deciding Factor</h2>
<p>Real-time streaming throughput.</p>
<blockquote data-evidence="true">the real-time streaming support was the deciding factor</blockquote>
"""

# Same shape, but one evidence quote is fabricated (not present in the transcript).
DEBRIEF_HTML_WITH_FABRICATED_QUOTE = VALID_DEBRIEF_HTML.replace(
    "Comp Corp's pricing was actually cheaper, about 15% less</blockquote>\n\n<h2>Objections",
    "The CEO personally guaranteed a 50% discount for life</blockquote>\n\n<h2>Objections",
)

DEBRIEF_HTML_MISSING_SECTION = VALID_DEBRIEF_HTML.replace("<h2>Deciding Factor</h2>", "<h2>Renamed Section</h2>")

VALID_BRIEF_HTML = """
<h1>Quarterly Competitive Brief -- 2025Q4</h1>
<h2>Overview &amp; Methodology</h2>
<p>2 debriefs this quarter. Customer identities have been removed from this shared version.</p>

<h2>Patterns by Competitor</h2>
<table>
<tr><th>Competitor</th><th>Wins Against</th><th>Losses To</th><th>Sample Size</th><th>Small Sample?</th></tr>
<tr><td>Comp Corp</td><td>1</td><td>1</td><td>2</td><td>Yes</td></tr>
</table>
<p>Comp Corp split 1-1 this quarter (DEAL-2025Q4-001, DEAL-2025Q4-002); small sample.</p>

<h2>Patterns by Segment</h2>
<table>
<tr><th>Segment</th><th>Wins</th><th>Losses</th></tr>
<tr><td>Mid-Market</td><td>1</td><td>1</td></tr>
</table>

<h2>Wording That Worked</h2>
<p>Emphasizing real-time throughput correlated with wins (DEAL-2025Q4-001).</p>

<h2>Losses Attributable to a Capability Gap</h2>
<p>DEAL-2025Q4-002 lost on missing SSO support.</p>
"""


@pytest.fixture
def sample_transcript() -> str:
    return SAMPLE_TRANSCRIPT


@pytest.fixture
def valid_debrief_html() -> str:
    return VALID_DEBRIEF_HTML


@pytest.fixture
def debrief_html_with_fabricated_quote() -> str:
    return DEBRIEF_HTML_WITH_FABRICATED_QUOTE


@pytest.fixture
def debrief_html_missing_section() -> str:
    return DEBRIEF_HTML_MISSING_SECTION


@pytest.fixture
def valid_brief_html() -> str:
    return VALID_BRIEF_HTML
