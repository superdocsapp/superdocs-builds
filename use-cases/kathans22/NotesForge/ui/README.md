# Compliance console

A console over the compliance CLI's own run artifacts — no second pipeline,
no recomputation. Everything it shows is `state/*.json`, `config/` and
`out/`, exactly as the CLI already wrote them.

## Usage

```bash
cd ui
npm run dev
```

That's the whole setup — no separate `npm install` step. `predev`
installs dependencies (a no-op if already installed) and runs
`npm run sync`, which copies `../state/*.json`, the client/requirement
registers, the amendment notices and the corpus notes into `public/data/`
as static JSON — that's what the browser actually fetches. Open the
printed URL and you're looking at real data from the first paint.

### Running commands from the browser

Each tab (except RUN) has a button — "Run coverage check", "Generate all
packs", "Seed version registry" / "Refresh consent matrix",
"Detect and apply amendment" — that runs the real
`npm run dev -- compliance --<command>` in the parent project, streams its
output live, then re-runs `npm run sync` and refreshes the screen
automatically. This is the *same* CLI a person would otherwise type by
hand in a terminal — the button is a trigger, not a second implementation.
It's wired through a dev-only Vite plugin
([`vite-plugin-cli-runner.ts`](vite-plugin-cli-runner.ts), registered via
`configureServer`, never `configurePreviewServer`), so the `/api/run`
endpoint exists only under `npm run dev` — it is not present in
`npm run build`'s output or `npm run preview`.

You can still run any `compliance` command by hand in the parent directory
and just click "refresh" (or re-run `npm run sync`) instead, if you'd
rather drive it from the terminal.

## Screens

| Tab | Source artifacts |
|---|---|
| COVERAGE | `state/coverage.json` |
| CLIENTS | `config/clients.yaml`, `state/versions.json`, `state/consent-matrix.json` |
| PACKS | `state/packs.json`, `out/<client_id>/` |
| AMENDMENTS | `state/amendments/**/event.json` |
| RUN | `state/ledger.json` |

Every generated pack and amendment notice carries its own
"draft for professional review" banner — this console does not add or
imply a compliance determination beyond what the CLI already computed.
