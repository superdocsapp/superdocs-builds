"""
conftest.py — shared pytest fixtures
"""
import os
import sys
import pytest

# Ensure the project root is on the path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Set a dummy API key so superdocs_client imports without error
os.environ.setdefault("SUPERDOCS_API_KEY", "sk_test_dummy_key_for_tests")
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key")


@pytest.fixture
def sample_original_html():
    return """
    <div data-chunk-id="c1"><h1>Mitochondrial Dynamics Study</h1></div>
    <div data-chunk-id="c2"><h2>Abstract</h2>
    <p>We investigated DRP1 in SH-SY5Y cells. MPP+ at 1.0 mM reduced viability
    to 58% ± 8% (p &lt; 0.001, n=45). Mdivi-1 improved viability by 34% ± 6%
    (p = 0.002). F(3,176) = 47.3, p &lt; 0.001.</p></div>
    <div data-chunk-id="c3"><h2>Introduction</h2>
    <p>Parkinson's disease affects 1% of the population over 60 [1].
    In our previous work, we showed DRP1 phosphorylation is elevated (Smith et al., 2019) [8].</p></div>
    <div data-chunk-id="c4"><h2>Methods</h2>
    <p>Cells were treated with 0.5 mM, 1.0 mM, and 2.0 mM MPP+ for 24 hours.
    The equation for fragmentation index: $F = N_{individual} / N_{total}$.</p></div>
    <div data-chunk-id="c5"><h2>Results</h2>
    <p>Fragmentation increased 2.9-fold at 1.0 mM (p &lt; 0.001).
    r = 0.85 between concentration and fragmentation.</p></div>
    <div data-chunk-id="c6"><h2>Discussion</h2>
    <p>Our findings demonstrate DRP1-mediated fission contributes to cell death.</p></div>
    <div data-chunk-id="c7"><h2>Acknowledgements</h2>
    <p>Supported by Example Research Council grant ERC-2019-12345.
    J.A.S. is supported by the Example Academy of Sciences.</p></div>
    <div data-chunk-id="c8"><h2>References</h2>
    <p>1. de Lau LM, Breteler MM. Lancet Neurol. 2006;5(6):525-535.</p>
    <p>8. Smith JA, Jones RB, Garcia MC. J Neurochem. 2019;148(3):412-421.</p></div>
    """


@pytest.fixture
def nature_profile():
    from journal_loader import load_profile
    return load_profile("nature")


@pytest.fixture
def plos_profile():
    from journal_loader import load_profile
    return load_profile("plos-one")
