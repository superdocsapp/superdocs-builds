"""The as-designed diagram.

The card asks that "the diagram reflects the ordered configuration", so the
diagram is *generated from the order record*, never drawn. A single-path order
and a dual-path order produce structurally different diagrams; changing the
bandwidth changes the labels on the links; changing the CPE model changes the
node text. There is no version of this that can be right about the order and
wrong about the picture, because there is only one source for both.

Mermaid rather than an image, for three reasons that matter to this use case:

* SuperDocs live-renders Mermaid in the editor and rasterises it at export, so
  it survives into the .docx the customer receives.
* Re-editing is free — "add a protect path" rewrites a few lines rather than
  regenerating an image, which matters when a change order arrives at 4pm.
* A delivery manager can read the source and see it is not lying.
"""

from __future__ import annotations

from packet.order import Order


def _diverse(order: Order) -> bool:
    return str(order.raw("service.diversity", "none")).lower() in {"dual", "diverse"}


def as_designed_diagram(order: Order) -> str:
    """A Mermaid flowchart of the ordered service, wrapped for SuperDocs."""
    bandwidth = order.value("service.bandwidth_mbps")
    handoff = order.raw("service.handoff", "customer handoff")
    cpe = order.raw("service.cpe.model", "CPE")
    site_a = order.raw("sites.a.label", "A-end")
    site_b = order.raw("sites.b.label", "B-end")
    circuit = order.raw("service.circuit_id", "circuit")
    protection = order.raw("service.protection", "unprotected")

    # The diagram declares its own configuration in Mermaid comments. Checking
    # the picture by grepping its prose is how you conclude that a diagram
    # captioned "no protection" shows a protect route — the substring is there.
    # A declaration is unambiguous, survives relabelling, and is invisible in
    # the rendered output.
    lines = [
        "flowchart LR",
        f"  %% design:bandwidth={bandwidth}",
        f"  %% design:diversity={'dual' if _diverse(order) else 'single'}",
        f"  %% design:circuit={_esc(circuit)}",
        f'  subgraph A["{_esc(site_a)}"]',
        f'    ACE["Customer equipment<br/>{_esc(handoff)}"]',
        f'    ACPE["{_esc(cpe)}<br/>A-end NTU"]',
        "  end",
        f'  subgraph B["{_esc(site_b)}"]',
        f'    BCPE["{_esc(cpe)}<br/>B-end NTU"]',
        f'    BCE["Customer equipment<br/>{_esc(handoff)}"]',
        "  end",
        f'  ACE ---|"{_esc(handoff)}"| ACPE',
        f'  BCPE ---|"{_esc(handoff)}"| BCE',
    ]

    if _diverse(order):
        lines += [
            '  subgraph CORE["Supplier core"]',
            '    R1["Route A<br/>primary"]',
            '    R2["Route C<br/>protect"]',
            "  end",
            f'  ACPE ==>|"{_esc(bandwidth)} primary"| R1',
            f'  R1 ==>|"{_esc(bandwidth)}"| BCPE',
            f'  ACPE -.->|"{_esc(bandwidth)} protect"| R2',
            f'  R2 -.->|"{_esc(bandwidth)}"| BCPE',
            f'  CORE -.- P["{_esc(protection)}"]',
            "  classDef protect stroke-dasharray: 5 5;",
            "  class R2 protect;",
        ]
    else:
        lines += [
            '  subgraph CORE["Supplier core"]',
            '    R1["Route A<br/>single path — no protection"]',
            "  end",
            f'  ACPE ==>|"{_esc(bandwidth)}"| R1',
            f'  R1 ==>|"{_esc(bandwidth)}"| BCPE',
            "  classDef risk stroke:#c0392b,stroke-width:2px;",
            "  class R1 risk;",
        ]

    lines.append(f'  CORE -.- CID["Circuit {_esc(circuit)}"]')

    caption = (
        f"As-designed: {bandwidth} {order.raw('service.product', 'service')} between "
        f"{site_a} and {site_b}, "
        + ("dual path with protection." if _diverse(order) else
           "single path — an outage on Route A is a service outage.")
    )
    return (
        "<pre class=\"mermaid\">\n" + "\n".join(lines) + "\n</pre>\n"
        f"<p><em>{_esc(caption)}</em></p>"
    )


def diagram_signature(order: Order) -> str:
    """The configuration facts the diagram depends on.

    Change propagation compares this before and after an edit: if it moved, the
    diagram must be regenerated, and if it did not, the diagram must be left
    exactly alone. It is how the diagram stays honest without regenerating it
    on every run.
    """
    return "|".join(
        str(order.raw(p, ""))
        for p in (
            "service.bandwidth_mbps",
            "service.diversity",
            "service.protection",
            "service.handoff",
            "service.cpe.model",
            "service.circuit_id",
            "sites.a.label",
            "sites.b.label",
        )
    )


def _esc(value) -> str:
    """Mermaid node labels live inside quotes; the quote and the angle brackets
    are the two characters that break the parse."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace('"', "'")
        .replace("<", "‹")
        .replace(">", "›")
        .replace("\n", " ")
    )
