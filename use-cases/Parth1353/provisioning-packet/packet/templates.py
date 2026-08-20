"""The six documents, and the renderer that knows what each one carries.

A template is HTML with three constructs and nothing else:

    {{service.bandwidth_mbps}}      a field, rendered through the registry
    {{#internal}} … {{/internal}}   a block only the internal pack sees
    {{@diagram}}                    the as-designed diagram for this order

The ``@`` on the diagram token is not decoration: without it the placeholder
parses as a field path called "diagram", and the audit reports a phantom
undeclared field. Sigils on non-field constructs keep the two namespaces apart.

The renderer is forty lines and hand-written on purpose. A general template
engine would render these perfectly well, but it would not tell me **which
fields a given document references**, and that question is the spine of this
build: it is how a bandwidth change knows it must touch five documents and not
six, and how the audience check can be proved exhaustive rather than asserted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from packet.diagram import as_designed_diagram
from packet.order import BY_PATH, INTERNAL_PATHS, Order, OrderError

# Digits belong in field names — `escalation_l1` is a perfectly ordinary key,
# and a pattern that excludes them silently leaves the placeholder in the
# rendered document rather than failing. LEFTOVER catches anything this misses.
FIELD = re.compile(r"\{\{([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*)\}\}")
LEFTOVER = re.compile(r"\{\{[^}]*\}\}")
BLOCK = re.compile(r"\{\{#internal\}\}(.*?)\{\{/internal\}\}", re.S)
DIAGRAM = "{{@diagram}}"


@dataclass(frozen=True)
class DocumentSpec:
    slug: str
    title: str
    audience: str  # 'both' | 'internal'
    purpose: str
    template: str
    # The heading the diagram sits under. Named because the agent playbook is
    # explicit that a *section rewrite* is atomic — "heading to next heading, as
    # one unit" — whereas "replace this diagram" is an ordinary edit the model
    # may satisfy by tweaking the block in place. Measured: an in-place tweak
    # updated the bandwidth labels and left the topology single-path.
    diagram_section: str = ""

    @property
    def fields(self) -> frozenset[str]:
        """Every registry field this document references, internal blocks
        included. Computed from the template, so it cannot drift from it."""
        return frozenset(FIELD.findall(self.template))

    @property
    def customer_fields(self) -> frozenset[str]:
        """What a customer-facing render of this document actually shows."""
        visible = BLOCK.sub("", self.template)
        return frozenset(FIELD.findall(visible)) - INTERNAL_PATHS

    @property
    def has_diagram(self) -> bool:
        return DIAGRAM in self.template


def render(spec: DocumentSpec, order: Order, *, audience: str) -> str:
    """Render one document for one audience.

    Internal blocks are removed for the customer pack rather than redacted:
    a page of "[withheld]" tells a customer exactly how much you are not telling
    them, which is worse than the section not existing. Individual internal
    *fields* that appear outside a block still redact, so a template author who
    forgets the block wrapper fails safe rather than leaking.
    """
    if audience not in {"internal", "customer"}:
        raise OrderError(f"unknown audience {audience!r}")

    body = spec.template
    body = BLOCK.sub(lambda m: m.group(1) if audience == "internal" else "", body)

    def substitute(match: re.Match[str]) -> str:
        path = match.group(1)
        if path not in BY_PATH:
            raise OrderError(
                f"template {spec.slug!r} references {path!r}, which is not a declared field"
            )
        return order.value(path, audience=audience)

    body = FIELD.sub(substitute, body)
    if spec.has_diagram:
        body = body.replace(DIAGRAM, as_designed_diagram(order))

    # Nothing that looks like a placeholder may survive into a document a
    # customer will read. This is a backstop for the whole class of "the
    # pattern did not match what the author wrote" — the failure it caught in
    # development was a field name containing a digit, which rendered as
    # literal {{internal.escalation_l1}} in a contract pack.
    stranded = LEFTOVER.findall(body)
    if stranded:
        raise OrderError(
            f"template {spec.slug!r} rendered with unsubstituted placeholders: "
            f"{', '.join(sorted(set(stranded)))}. Either the field is not declared in "
            f"packet/order.py, or the placeholder is malformed."
        )
    return _shell(spec, order, audience, body)


def _shell(spec: DocumentSpec, order: Order, audience: str, body: str) -> str:
    banner = (
        '<p class="pack-mark"><strong>INTERNAL — NOT FOR CUSTOMER RELEASE</strong></p>'
        if audience == "internal"
        else ""
    )
    return f"""<h1>{spec.title}</h1>
<p><em>{spec.purpose}</em></p>
{banner}
<p>Service order {order.value("order.reference")} &middot; circuit
{order.value("service.circuit_id")} &middot; {order.value("customer.legal_name")}</p>
<hr/>
{body}
<hr/>
<p><small>Generated from order record {order.value("order.reference")}
(fingerprint {order.fingerprint()}) for the {audience} pack. Every value in this
document comes from that one record; nothing here was typed twice.</small></p>
"""


# ===========================================================================
# The six documents
# ===========================================================================

SERVICE_ORDER_FORM = DocumentSpec(
    slug="01-service-order-form",
    title="Service Order Form",
    audience="both",
    purpose="The signed order, restated as the delivery team will work to it.",
    template="""
<h2>1. Parties</h2>
<table>
<tr><th>Customer</th><td>{{customer.legal_name}}</td></tr>
<tr><th>Trading as</th><td>{{customer.trading_name}}</td></tr>
<tr><th>Supplier</th><td>{{supplier.legal_name}}</td></tr>
<tr><th>Master agreement</th><td>{{order.msa_reference}}</td></tr>
<tr><th>Order signed</th><td>{{order.signed_date}}</td></tr>
<tr><th>Customer PO</th><td>{{customer.billing_reference}}</td></tr>
</table>

<h2>2. Ordered service</h2>
<table>
<tr><th>Product</th><td>{{service.product}}</td></tr>
<tr><th>Circuit ID</th><td>{{service.circuit_id}}</td></tr>
<tr><th>Bandwidth</th><td>{{service.bandwidth_mbps}}</td></tr>
<tr><th>Committed information rate</th><td>{{service.cir_mbps}}</td></tr>
<tr><th>Customer handoff</th><td>{{service.handoff}}</td></tr>
<tr><th>VLAN mode</th><td>{{service.vlan_mode}}</td></tr>
<tr><th>MTU</th><td>{{service.mtu}}</td></tr>
<tr><th>Route diversity</th><td>{{service.diversity}}</td></tr>
<tr><th>Protection</th><td>{{service.protection}}</td></tr>
</table>

<h2>3. Sites</h2>
<table>
<tr><th></th><th>A-end</th><th>B-end</th></tr>
<tr><th>Site</th><td>{{sites.a.label}}</td><td>{{sites.b.label}}</td></tr>
<tr><th>Address</th><td>{{sites.a.address}}</td><td>{{sites.b.address}}</td></tr>
<tr><th>Room</th><td>{{sites.a.room}}</td><td>{{sites.b.room}}</td></tr>
</table>

<h2>4. Delivery</h2>
<table>
<tr><th>Ready for service</th><td>{{delivery.rfs_date}}</td></tr>
<tr><th>Site survey</th><td>{{delivery.survey_date}}</td></tr>
<tr><th>Installation</th><td>{{delivery.install_date}}</td></tr>
<tr><th>Acceptance period</th><td>{{delivery.acceptance_days}}</td></tr>
<tr><th>Delay compensation</th><td>{{delivery.liquidated_damages}}</td></tr>
</table>

<h2>5. Charges</h2>
<table>
<tr><th>Monthly recurring charge</th><td>{{commercial.currency}} {{commercial.mrc}}</td></tr>
<tr><th>One-off charge</th><td>{{commercial.currency}} {{commercial.nrc}}</td></tr>
<tr><th>Committed term</th><td>{{commercial.term_months}}</td></tr>
<tr><th>Payment terms</th><td>{{commercial.payment_terms_days}}</td></tr>
</table>

{{#internal}}
<h2>6. Internal commercial position</h2>
<table>
<tr><th>Wholesale circuit</th><td>{{internal.wholesale_circuit_ref}}</td></tr>
<tr><th>Wholesale cost (MRC)</th><td>{{commercial.currency}} {{internal.wholesale_cost_mrc}}</td></tr>
<tr><th>Gross margin</th><td>{{internal.gross_margin_pct}}</td></tr>
<tr><th>Margin floor</th><td>{{internal.margin_floor_note}}</td></tr>
</table>
{{/internal}}
""",
)

SITE_SURVEY_REQUEST = DocumentSpec(
    slug="02-site-survey-request",
    title="Site Survey Request",
    audience="both",
    purpose="What the survey engineer needs to know before attending either site.",
    template="""
<h2>1. Survey scope</h2>
<p>A survey is requested at both ends of circuit {{service.circuit_id}} ahead of an
installation targeting {{delivery.install_date}} and a ready-for-service date of
{{delivery.rfs_date}}. The service is {{service.bandwidth_mbps}} with
{{service.diversity}}; the survey must confirm the building can support that
configuration.</p>

<h2>2. Requested survey date</h2>
<table>
<tr><th>Target survey date</th><td>{{delivery.survey_date}}</td></tr>
<tr><th>Site contact</th><td>{{customer.site_contact.name}}</td></tr>
<tr><th>Site contact phone</th><td>{{customer.site_contact.phone}}</td></tr>
</table>

<h2>3. A-end</h2>
<table>
<tr><th>Site</th><td>{{sites.a.label}}</td></tr>
<tr><th>Address</th><td>{{sites.a.address}}</td></tr>
<tr><th>Room</th><td>{{sites.a.room}}</td></tr>
<tr><th>Access hours</th><td>{{sites.a.access_hours}}</td></tr>
<tr><th>Escort required</th><td>{{sites.a.escort_required}}</td></tr>
<tr><th>Power provision</th><td>{{sites.a.power}}</td></tr>
</table>

<h2>4. B-end</h2>
<table>
<tr><th>Site</th><td>{{sites.b.label}}</td></tr>
<tr><th>Address</th><td>{{sites.b.address}}</td></tr>
<tr><th>Room</th><td>{{sites.b.room}}</td></tr>
<tr><th>Access hours</th><td>{{sites.b.access_hours}}</td></tr>
<tr><th>Escort required</th><td>{{sites.b.escort_required}}</td></tr>
<tr><th>Power provision</th><td>{{sites.b.power}}</td></tr>
</table>

<h2>5. Confirm on site</h2>
<ul>
<li>Fibre entry point and duct capacity for {{service.diversity}}.</li>
<li>Rack space and power for {{service.cpe.count}} × {{service.cpe.model}}.</li>
<li>Cable route from entry to rack, with measured length.</li>
<li>Presentation to the customer: {{service.handoff}}.</li>
<li>Any building works or permits that would put {{delivery.rfs_date}} at risk.</li>
</ul>

{{#internal}}
<h2>6. Internal notes for the surveyor</h2>
<p>{{internal.provisioning_notes}}</p>
<p><strong>Known build risk:</strong> {{internal.build_risk}}</p>
<p>Upstream circuit reference for the wholesale order: {{internal.wholesale_circuit_ref}}.</p>
{{/internal}}
""",
)

INSTALLATION_SOW = DocumentSpec(
    slug="03-installation-scope-of-work",
    title="Installation Scope of Work",
    audience="both",
    purpose="What will be built, how it is designed, and who does what.",
    diagram_section="1. As-designed configuration",
    template="""
<h2>1. As-designed configuration</h2>
<p>The diagram below is generated from the order record. It shows
{{service.bandwidth_mbps}} {{service.product}} between {{sites.a.label}} and
{{sites.b.label}} with {{service.diversity}}.</p>

{{@diagram}}

<h2>2. Design summary</h2>
<table>
<tr><th>Circuit ID</th><td>{{service.circuit_id}}</td></tr>
<tr><th>Bandwidth</th><td>{{service.bandwidth_mbps}}</td></tr>
<tr><th>Committed information rate</th><td>{{service.cir_mbps}}</td></tr>
<tr><th>Handoff</th><td>{{service.handoff}}</td></tr>
<tr><th>MTU</th><td>{{service.mtu}}</td></tr>
<tr><th>VLAN mode</th><td>{{service.vlan_mode}}</td></tr>
<tr><th>Route diversity</th><td>{{service.diversity}}</td></tr>
<tr><th>Protection</th><td>{{service.protection}}</td></tr>
<tr><th>CPE</th><td>{{service.cpe.count}} × {{service.cpe.model}}</td></tr>
<tr><th>CPE managed by supplier</th><td>{{service.cpe.managed}}</td></tr>
</table>

<h2>3. Supplier scope</h2>
<ul>
<li>Provide and install {{service.cpe.count}} × {{service.cpe.model}} at the
locations identified in the site survey.</li>
<li>Terminate the access fibre and present {{service.handoff}} at each end.</li>
<li>Configure the circuit to {{service.bandwidth_mbps}} with MTU {{service.mtu}}.</li>
<li>Implement {{service.diversity}} and {{service.protection}}.</li>
<li>Complete the acceptance test plan and produce the results pack.</li>
<li>Hand over to service on {{delivery.rfs_date}}.</li>
</ul>

<h2>4. Customer scope</h2>
<ul>
<li>Provide access to {{sites.a.label}} and {{sites.b.label}} within the agreed
access hours.</li>
<li>Provide rack space and power as recorded in the readiness checklist.</li>
<li>Nominate a technical contact for cutover: {{customer.primary_contact.name}}
({{customer.primary_contact.email}}).</li>
<li>Confirm acceptance within {{delivery.acceptance_days}} of the results pack.</li>
</ul>

<h2>5. Programme</h2>
<table>
<tr><th>Site survey</th><td>{{delivery.survey_date}}</td></tr>
<tr><th>Installation</th><td>{{delivery.install_date}}</td></tr>
<tr><th>Cutover window</th><td>{{delivery.cutover_window}}</td></tr>
<tr><th>Ready for service</th><td>{{delivery.rfs_date}}</td></tr>
</table>

{{#internal}}
<h2>6. Internal build notes</h2>
<p>{{internal.provisioning_notes}}</p>
<p><strong>Risk to the committed date:</strong> {{internal.build_risk}}</p>
<p>Wholesale circuit {{internal.wholesale_circuit_ref}} at
{{commercial.currency}} {{internal.wholesale_cost_mrc}} per month
({{internal.gross_margin_pct}} margin at the ordered price).</p>
<p>Escalation: {{internal.escalation_l1}} then {{internal.escalation_l2}}.</p>
{{/internal}}
""",
)

READINESS_CHECKLIST = DocumentSpec(
    slug="04-customer-readiness-checklist",
    title="Customer Readiness Checklist",
    audience="both",
    purpose="Everything the customer must have in place before the install team arrives.",
    template="""
<p>Installation is scheduled for {{delivery.install_date}}, with the service ready
on {{delivery.rfs_date}}. Each item below must be complete before the install team
attends. Anything outstanding on the day is the most common cause of a missed
ready-for-service date.</p>

<h2>Before the site survey ({{delivery.survey_date}})</h2>
<table>
<tr><th>#</th><th>Item</th><th>Owner</th><th>Done</th></tr>
<tr><td>1</td><td>Confirm site contact and out-of-hours number</td>
    <td>{{customer.site_contact.name}}</td><td>☐</td></tr>
<tr><td>2</td><td>Confirm access hours at {{sites.a.label}}: {{sites.a.access_hours}}</td>
    <td>Customer</td><td>☐</td></tr>
<tr><td>3</td><td>Confirm access hours at {{sites.b.label}}: {{sites.b.access_hours}}</td>
    <td>Customer</td><td>☐</td></tr>
<tr><td>4</td><td>Raise site passes if escort is required
    (A-end: {{sites.a.escort_required}}, B-end: {{sites.b.escort_required}})</td>
    <td>Customer</td><td>☐</td></tr>
</table>

<h2>Before installation ({{delivery.install_date}})</h2>
<table>
<tr><th>#</th><th>Item</th><th>Owner</th><th>Done</th></tr>
<tr><td>5</td><td>Rack space for {{service.cpe.count}} × {{service.cpe.model}} at both ends</td>
    <td>Customer</td><td>☐</td></tr>
<tr><td>6</td><td>Power available: {{sites.a.power}} (A-end), {{sites.b.power}} (B-end)</td>
    <td>Customer</td><td>☐</td></tr>
<tr><td>7</td><td>Customer-side equipment ready to accept {{service.handoff}}</td>
    <td>Customer</td><td>☐</td></tr>
<tr><td>8</td><td>Customer-side interface configured for MTU {{service.mtu}} and
    {{service.vlan_mode}}</td><td>Customer</td><td>☐</td></tr>
<tr><td>9</td><td>Cutover window agreed: {{delivery.cutover_window}}</td>
    <td>Both</td><td>☐</td></tr>
</table>

<h2>Before acceptance</h2>
<table>
<tr><th>#</th><th>Item</th><th>Owner</th><th>Done</th></tr>
<tr><td>10</td><td>Technical contact available during testing:
    {{customer.primary_contact.name}}, {{customer.primary_contact.phone}}</td>
    <td>Customer</td><td>☐</td></tr>
<tr><td>11</td><td>Acceptance decision returned within {{delivery.acceptance_days}}</td>
    <td>Customer</td><td>☐</td></tr>
<tr><td>12</td><td>Billing reference confirmed: {{customer.billing_reference}}</td>
    <td>Customer</td><td>☐</td></tr>
</table>

<p>Questions before the install: {{supplier.delivery_manager.name}},
{{supplier.delivery_manager.email}}. Faults after handover: {{supplier.noc_number}}.</p>
""",
)

ACCEPTANCE_TEST_PLAN = DocumentSpec(
    slug="05-acceptance-test-plan",
    title="Acceptance Test Plan",
    audience="both",
    purpose="The tests that decide whether the circuit is accepted, and the numbers they must meet.",
    template="""
<p>These tests are run on circuit {{service.circuit_id}} after installation and
before handover on {{delivery.rfs_date}}. Every threshold below is the committed
service level from the order; a test that does not meet its threshold blocks
acceptance.</p>

<h2>1. Thresholds under test</h2>
<table>
<tr><th>Measure</th><th>Committed</th></tr>
<tr><td>Throughput (bidirectional)</td><td>{{service.bandwidth_mbps}}</td></tr>
<tr><td>Committed information rate</td><td>{{service.cir_mbps}}</td></tr>
<tr><td>Round-trip latency</td><td>&le; {{sla.latency_ms}}</td></tr>
<tr><td>Jitter</td><td>&le; {{sla.jitter_ms}}</td></tr>
<tr><td>Frame loss</td><td>&le; {{sla.packet_loss_pct}}</td></tr>
<tr><td>Availability (measured from handover)</td><td>&ge; {{sla.availability_pct}}</td></tr>
<tr><td>MTTR on a chargeable fault</td><td>&le; {{sla.mttr_hours}}</td></tr>
</table>

<h2>2. Test procedure</h2>
<table>
<tr><th>#</th><th>Test</th><th>Method</th><th>Pass criterion</th><th>Result</th></tr>
<tr><td>T1</td><td>Physical presentation</td><td>Visual and optical power check at
    both ends</td><td>{{service.handoff}} presented, power within transceiver spec</td>
    <td>☐</td></tr>
<tr><td>T2</td><td>Throughput</td><td>RFC 2544 throughput, 60 seconds per frame size</td>
    <td>{{service.bandwidth_mbps}} achieved bidirectionally</td><td>☐</td></tr>
<tr><td>T3</td><td>Latency</td><td>RFC 2544 latency at 1518-byte frames</td>
    <td>&le; {{sla.latency_ms}}</td><td>☐</td></tr>
<tr><td>T4</td><td>Frame loss</td><td>RFC 2544 frame loss at 100% of CIR</td>
    <td>&le; {{sla.packet_loss_pct}}</td><td>☐</td></tr>
<tr><td>T5</td><td>Jitter</td><td>Y.1564 service configuration test</td>
    <td>&le; {{sla.jitter_ms}}</td><td>☐</td></tr>
<tr><td>T6</td><td>MTU</td><td>Unfragmented frame at configured MTU end to end</td>
    <td>{{service.mtu}} passes without fragmentation</td><td>☐</td></tr>
<tr><td>T7</td><td>VLAN handling</td><td>Tagged frame transparency</td>
    <td>{{service.vlan_mode}} behaves as ordered</td><td>☐</td></tr>
<tr><td>T8</td><td>Resilience</td><td>Break primary path, measure restoration</td>
    <td>{{service.protection}} restores within the protection window</td><td>☐</td></tr>
<tr><td>T9</td><td>Soak</td><td>24-hour soak at CIR</td>
    <td>No errored seconds beyond {{sla.packet_loss_pct}}</td><td>☐</td></tr>
</table>

<p>Test T8 applies only where the order includes route diversity. This order
specifies {{service.diversity}}.</p>

<h2>3. Acceptance</h2>
<p>Results are issued to {{customer.primary_contact.name}}
({{customer.primary_contact.email}}). The customer has
{{delivery.acceptance_days}} from issue to raise defects; absent a defect notice
the service is deemed accepted and billing at
{{commercial.currency}} {{commercial.mrc}} per month begins.</p>

{{#internal}}
<h2>4. Internal test notes</h2>
<p>Run T2 and T9 against the wholesale circuit {{internal.wholesale_circuit_ref}}
before presenting results, so a wholesale fault is not misreported as ours.</p>
<p>{{internal.build_risk}}</p>
{{/internal}}
""",
)

HANDOVER_CERTIFICATE = DocumentSpec(
    slug="06-handover-certificate",
    title="Service Handover Certificate",
    audience="both",
    purpose="The document both parties sign when the service passes into life.",
    template="""
<p>This certificate records the handover of circuit {{service.circuit_id}} from
delivery into service.</p>

<h2>1. Service handed over</h2>
<table>
<tr><th>Customer</th><td>{{customer.legal_name}}</td></tr>
<tr><th>Supplier</th><td>{{supplier.legal_name}}</td></tr>
<tr><th>Service order</th><td>{{order.reference}}</td></tr>
<tr><th>Master agreement</th><td>{{order.msa_reference}}</td></tr>
<tr><th>Circuit ID</th><td>{{service.circuit_id}}</td></tr>
<tr><th>Product</th><td>{{service.product}}</td></tr>
<tr><th>Bandwidth</th><td>{{service.bandwidth_mbps}}</td></tr>
<tr><th>Route diversity</th><td>{{service.diversity}}</td></tr>
<tr><th>A-end</th><td>{{sites.a.address}}</td></tr>
<tr><th>B-end</th><td>{{sites.b.address}}</td></tr>
<tr><th>Ready for service</th><td>{{delivery.rfs_date}}</td></tr>
</table>

<h2>2. Confirmations</h2>
<ul>
<li>The acceptance test plan has been executed in full and every test passed.</li>
<li>The service meets the committed availability of {{sla.availability_pct}}.</li>
<li>{{service.cpe.count}} × {{service.cpe.model}} installed and, where managed
({{service.cpe.managed}}), enrolled in supplier monitoring.</li>
<li>Fault reporting is via {{supplier.noc_number}}, 24×7, with an MTTR
commitment of {{sla.mttr_hours}}.</li>
<li>Billing commences on the ready-for-service date at
{{commercial.currency}} {{commercial.mrc}} per month for a term of
{{commercial.term_months}}.</li>
</ul>

<h2>3. Signatures</h2>
<table>
<tr><th></th><th>Customer</th><th>Supplier</th></tr>
<tr><th>Name</th><td>{{customer.primary_contact.name}}</td>
    <td>{{supplier.delivery_manager.name}}</td></tr>
<tr><th>Role</th><td>{{customer.primary_contact.role}}</td>
    <td>Service Delivery Manager</td></tr>
<tr><th>Date</th><td>&nbsp;</td><td>&nbsp;</td></tr>
<tr><th>Signature</th><td>&nbsp;</td><td>&nbsp;</td></tr>
</table>

<p>Signature blocks are left blank on purpose. This build does not implement
e-signature; the finished certificate is sent to whichever signing provider the
account already uses.</p>
""",
)

DOCUMENTS: tuple[DocumentSpec, ...] = (
    SERVICE_ORDER_FORM,
    SITE_SURVEY_REQUEST,
    INSTALLATION_SOW,
    READINESS_CHECKLIST,
    ACCEPTANCE_TEST_PLAN,
    HANDOVER_CERTIFICATE,
)

BY_SLUG: dict[str, DocumentSpec] = {d.slug: d for d in DOCUMENTS}


def documents_carrying(path: str, *, audience: str = "internal") -> list[DocumentSpec]:
    """Which documents a change to this field must reach.

    This is the function that makes "a date change updates every document that
    carries it" true rather than hopeful — the answer is derived from the
    templates, so a document that starts carrying a field starts receiving its
    updates without anyone remembering to wire it up.
    """
    out = []
    for spec in DOCUMENTS:
        fields = spec.fields if audience == "internal" else spec.customer_fields
        if path in fields:
            out.append(spec)
    return out


def audit_audience() -> list[str]:
    """Prove no internal field can reach a customer render.

    Returns a list of violations; empty means the packs differ only in what is
    meant to be hidden. Run by the test suite and by ``packet audit``.
    """
    violations = []
    for spec in DOCUMENTS:
        leaked = spec.customer_fields & INTERNAL_PATHS
        for path in sorted(leaked):
            violations.append(
                f"{spec.slug}: internal field {path} is referenced outside an "
                f"{{{{#internal}}}} block and would render to the customer"
            )
    return violations


def unknown_fields() -> list[str]:
    """Placeholders that will not render.

    Two kinds: a well-formed field path with no registry entry, and anything
    else that survives the field and block patterns. The second kind is the
    dangerous one — it renders as literal braces in a document someone signs.
    """
    out = []
    for spec in DOCUMENTS:
        for path in sorted(spec.fields):
            if path not in BY_PATH:
                out.append(f"{spec.slug}: {{{{{path}}}}} is not a declared field")
        stripped = BLOCK.sub(lambda m: m.group(1), spec.template).replace(DIAGRAM, "")
        for token in sorted(set(LEFTOVER.findall(FIELD.sub("", stripped)))):
            out.append(f"{spec.slug}: {token} is not a placeholder this renderer understands")
    return out
