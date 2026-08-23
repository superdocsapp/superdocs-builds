# Help Centre Localizer

A small CLI extension that localizes help-centre article paragraphs through the SuperDocs API and swaps screenshots to the requested locale.

## What it does

- Localizes `<p>` content into a requested locale.
- Uses SuperDocs as the real localization provider.
- Protects product names, keyboard shortcuts, and code while translating surrounding text.
- Detects which paragraphs changed between two source versions and only translates those paragraphs.
- Replaces English screenshots with locale-specific screenshots.
- Flags a missing locale screenshot instead of silently falling back to English.
- Preserves the existing HTML document structure and paragraph attributes.

## Project structure

```text
help-centre-localizer/
├── src/
│   ├── cli.py
│   ├── incremental.py
│   ├── localizer.py
│   ├── parser.py
│   ├── pipeline.py
│   ├── protector.py
│   ├── screenshots.py
│   ├── superdocs_provider.py
│   └── swapper.py
├── tests/
├── examples/
│   ├── article.html
│   ├── screenshots/
│   └── test_superdocs_api.py
├── .env.example
├── .gitignore
├── README.md
└── requirements.txt
```

## Setup

Use Python 3.11+ and install the dependencies:

```powershell
python -m pip install -r requirements.txt
```

Set `SUPERDOCS_API_KEY` in the process environment. PowerShell example:

```powershell
$env:SUPERDOCS_API_KEY="your-key-here"
```

`.env.example` documents the variable name, but this implementation does not load `.env` files automatically. Never commit a real API key.

## Run

Demo provider:

```powershell
python -m src.cli `
    --input examples\article.html `
    --locale es `
    --screenshots examples\screenshots `
    --output examples\output\es\article.html `
    --provider demo
```

Real SuperDocs provider:

```powershell
python -m src.cli `
    --input examples\article.html `
    --locale es `
    --screenshots examples\screenshots `
    --output examples\output\es\article.html `
    --provider superdocs
```

For incremental localization, provide the previous source article:

```powershell
python -m src.cli `
    --input examples\article.html `
    --previous examples\article.previous.html `
    --locale es `
    --screenshots examples\screenshots `
    --output examples\output\es\article.html `
    --provider superdocs
```

## Localization design

The pipeline treats paragraphs as the incremental translation unit:

```text
source HTML
    ↓
extract paragraphs
    ↓
compare with previous source (when supplied)
    ↓
changed paragraph indices
    ↓
protect product names / shortcuts / code
    ↓
SuperDocs translation request per changed paragraph
    ↓
restore protected content
    ↓
replace only paragraph contents
    ↓
screenshot locale swap
    ↓
localized HTML
```

The implementation deliberately uses the SuperDocs chat response for paragraph translation. The API's `document_changes.updated_html` is reserved for operations where a complete HTML result is explicitly requested.

### Protected content

The following are preserved exactly:

- configured product names such as `SuperDocs`
- keyboard shortcuts such as `Ctrl + K`
- inline code such as `npm install`
- code/preformatted elements in the source HTML

The surrounding human-readable sentence is still translated.

### Incremental localization

On the first run, every paragraph is localized. When `--previous` is supplied, the incremental analyzer compares normalized paragraph text and returns only changed paragraph indices. Unchanged paragraphs are copied through without another translation request.

### Screenshots

Screenshots are resolved from:

```text
examples/screenshots/<locale>/...
```

If a locale screenshot exists, its source is replaced. If it does not exist, the English image is not used as a fallback; the image is flagged in the output and CLI report.

## Tests

Run the deterministic test suite:

```powershell
python -m unittest discover -s tests -v
```

The live SuperDocs integration test is opt-in so normal test runs do not require an API key:

```powershell
$env:RUN_REAL_SUPERDOCS_TEST="1"
python -m unittest tests.test_real_superdocs -v
Remove-Item Env:RUN_REAL_SUPERDOCS_TEST
```

## Scope and assumptions

The current implementation treats `<p>` elements as the translatable and incremental content units. Structural elements such as headings, document metadata, image attributes, and figure captions are preserved by the pipeline. Screenshot files are separate locale assets and are not translated by the API.

Generated files under `examples/output/`, local virtual environments, Python bytecode, and secrets are intentionally excluded from source control.
