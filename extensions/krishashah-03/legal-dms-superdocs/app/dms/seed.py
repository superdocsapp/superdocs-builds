"""
Fictional seed data only. No real client, firm, or matter data - per the task
brief's rule that fabricated test data is expected and real third-party data
is not welcome.
"""
from app.dms.store import DMSStore

SAMPLE_NDA_HTML = """
<h1>Mutual Non-Disclosure Agreement</h1>
<p>This Agreement is entered into between Acme Robotics Inc. ("Acme") and
Umbrella Logistics LLC ("Umbrella").</p>
<h2>1. Definitions</h2>
<p>"Confidential Information" means any non-public information disclosed by
either party.</p>
<h2>2. Confidentiality Obligations</h2>
<p>Each party shall protect the other's Confidential Information using
reasonable care.</p>
<h2>3. Term</h2>
<p>This Agreement remains in effect for two (2) years from the Effective Date.</p>
""".strip()

SAMPLE_MSA_HTML = """
<h1>Master Services Agreement</h1>
<p>Between Stratus Analytics Inc. ("Client") and Umbrella Logistics LLC
("Vendor").</p>
<h2>1. Scope of Services</h2>
<p>Vendor shall provide logistics consulting services as described in each
Statement of Work.</p>
<h2>2. Confidentiality</h2>
<p>Each party shall protect the other's Confidential Information using
reasonable care for the duration of this Agreement and three (3) years
thereafter.</p>
<h2>3. Limitation of Liability</h2>
<p>Neither party's liability shall exceed the fees paid in the preceding
twelve (12) months.</p>
""".strip()

SAMPLE_WALLED_HTML = """
<h1>Confidential Settlement Agreement</h1>
<p>Between Northwind Retail Corp. and a former employee, subject to a strict
ethical wall.</p>
<h2>1. Settlement Terms</h2>
<p>Confidential settlement terms apply.</p>
""".strip()


def build_seeded_store() -> DMSStore:
    store = DMSStore()

    # Users
    store.add_user("attorney-priya", "Priya Nair", role="attorney")
    store.add_user("attorney-sam", "Sam Okafor", role="attorney")
    store.add_user("paralegal-rina", "Rina Fernandes", role="paralegal")

    # Matters
    store.add_matter(
        "matter-acme-nda",
        name="Acme Robotics - Umbrella Logistics NDA",
        client_name="Acme Robotics Inc.",
        ethical_wall=None,  # open to the whole firm
    )
    store.add_matter(
        "matter-stratus-msa",
        name="Stratus Analytics - Umbrella Logistics MSA",
        client_name="Stratus Analytics Inc.",
        ethical_wall=None,
    )
    store.add_matter(
        "matter-northwind-walled",
        name="Northwind Retail - Confidential Settlement",
        client_name="Northwind Retail Corp.",
        # Ethical wall: only Sam and the paralegal are on this matter.
        # attorney-priya is deliberately excluded, for the wall test.
        ethical_wall={"attorney-sam", "paralegal-rina"},
    )

    # Documents
    store.add_document(
        "doc-nda-v1",
        matter_id="matter-acme-nda",
        title="Acme-Umbrella Mutual NDA",
        initial_html=SAMPLE_NDA_HTML,
        created_by="attorney-priya",
    )
    store.add_document(
        "doc-msa-v1",
        matter_id="matter-stratus-msa",
        title="Stratus-Umbrella MSA",
        initial_html=SAMPLE_MSA_HTML,
        created_by="attorney-sam",
    )
    store.add_document(
        "doc-settlement-v1",
        matter_id="matter-northwind-walled",
        title="Northwind Settlement Agreement",
        initial_html=SAMPLE_WALLED_HTML,
        created_by="attorney-sam",
    )

    return store
