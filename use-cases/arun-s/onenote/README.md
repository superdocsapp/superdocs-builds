# OneNote → styled doc exporter

*Built by Arun S for the SuperDocs Round-2 task.*

A OneNote page is a **freeform canvas**: the Graph API returns every text box and image as
an absolutely-positioned block (inline `top`/`left`), so the order the API gives you is **not**
reading order. A naive HTML→doc conversion scrambles the moment two boxes sit side by side.

This pipeline pulls a notebook's pages through the OneNote Graph API, **re-linearizes** each page
by clustering blocks into reading-order rows from their coordinates, then hands the normalized HTML
to **SuperDocs** to produce a branded, exportable `.docx` — headings and paragraphs intact.

```
OneNote (Graph) --page html--> re-linearize (coords -> rows) --clean html--> SuperDocs --> .docx
```

## What "strong" looks like — proven, keyless
A page with two side-by-side text boxes and an inline image, delivered by the API *out of order*,
exports **top-to-bottom in reading order**. Run it with no credentials:
```bash
python run_demo.py          # re-linearizes sample_page.html and prints the clean HTML
python -m pytest tests/ -q  # 5 tests: block extraction, row clustering, reading-order != DOM order, full pipeline
```
The sample page's API/DOM order is `Risks, Footer, Highlights, image` → the output is
`Highlights, Risks, image, caption, Footer`. That reorder is the whole point.

## Files
| File | What it is |
|---|---|
| `relinearize.py` | The core: parse absolutely-positioned blocks → cluster into reading-order rows → emit clean HTML. Pure, no deps. |
| `graph.py` | Microsoft Graph OneNote client (`list_pages`, `page_html`). Injectable transport for tests. |
| `superdocs_min.py` | Slim SuperDocs hand-off (send document + export). |
| `export.py` | `export_page`: page → reading-order HTML → SuperDocs export. |
| `run_demo.py` | Offline demo, or live against your notebook. |
| `get_token.py` | Device-code helper to get a Graph token (no client secret). |
| `sample_page.html` | A synthetic OneNote page (side-by-side boxes + image) for the offline demo/tests. |
| `tests/` | Keyless proof of the re-linearization and the full pipeline. |

## Run it against a real notebook (what you provide)
1. **Register a free Azure app** — Azure Portal → App registrations → New. Add the *delegated*
   permission **`Notes.Read`**, mark it a **public client**, copy the *Application (client) ID*.
2. **Get a token** (either):
   - Fastest: [Graph Explorer](https://developer.microsoft.com/graph/graph-explorer) → consent to
     `Notes.Read` → copy the access token; or
   - `CLIENT_ID=<app-id> python get_token.py` → sign in with the code it prints.
3. **A real OneNote page** with two side-by-side text boxes and an inline image (the demo case).
4. Run:
   ```bash
   GRAPH_TOKEN=<token> python run_demo.py --page                    # list + re-linearize your page
   GRAPH_TOKEN=<token> SUPERDOCS_API_KEY=<key> python run_demo.py --page --export   # + export to SuperDocs
   ```

## The re-linearization, in one paragraph
Blocks are sorted by `top`, then merged into **rows** by vertical overlap (a block joins the current
row while its `top` is above the row's running bottom; otherwise it starts a new row). Each row is
ordered left-to-right, rows top-to-bottom. Text blocks keep their inner `<h1>/<h2>/<p>` so the export
is a clean document, not a flat wall of text; images become their own paragraph. It reads the *canvas*,
not the API's element order.

## Notes on the OneNote API (the real quirks)
- Page content is `text/html` (not JSON), with `data-absolute-enabled="true"` and inline
  `position:absolute; left/top` on each outline and image — the coordinates are the only reliable
  reading-order signal.
- Element order in the response is **authoring order**, not visual order, so it cannot be trusted.
- Heights are often absent; we cluster by `top` with a default line height, which is enough for the
  side-by-side / stacked cases that break naive converters.

## Where this goes
A pull request into the public repository, **use-cases** folder (per the task). Keep secrets out of
the code (tokens come from the environment), and add a screenshot before opening the PR.
