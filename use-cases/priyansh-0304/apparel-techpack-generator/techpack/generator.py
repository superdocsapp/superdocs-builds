"""Builds the tech pack HTML from a style dict. All measurement values here
are already-graded, code-computed numbers — no AI involvement in the math."""

from techpack.grading import build_graded_spec


def generate_tech_pack_html(style: dict) -> str:
    graded = build_graded_spec(style)
    sizes = style["size_range"]

    rows = ""
    for point in style["measurement_points"]:
        cells = "".join(f"<td>{graded[point['point_name']][s]}\"</td>" for s in sizes)
        rows += f"<tr><td>{point['point_name']}</td>{cells}<td>±{point['tolerance']}\"</td></tr>"

    bom_rows = "".join(
        f"<tr><td>{m['component']}</td><td>{m['spec']}</td><td>{m['placement']}</td></tr>"
        for m in style["materials"]
    )
    construction_list = "".join(f"<li>{note}</li>" for note in style["construction_notes"])

    return f"""
    <h1>{style['style_name']} — Technical Pack</h1>
    <p><b>Style ID:</b> {style['style_id']} | <b>Base Size:</b> {style['base_size']}</p>

    <h2>Graded Measurement Specification</h2>
    <table border="1">
      <tr><th>Point of Measure</th>{"".join(f"<th>{s}</th>" for s in sizes)}<th>Tolerance</th></tr>
      {rows}
    </table>

    <h2>Bill of Materials</h2>
    <table border="1">
      <tr><th>Component</th><th>Spec</th><th>Placement</th></tr>
      {bom_rows}
    </table>

    <h2>Construction Notes</h2>
    <ul>{construction_list}</ul>
    """