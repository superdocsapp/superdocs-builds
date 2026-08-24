# clausekeeper video toolchain — same package/voice as Task 4

Ported verbatim from `doctask-sambaths` per spec 0014 § Reuse rail (locked).
Only path/bundle-name renames (e.g., `clausekeeper-demo.mp4`); CSS/ffmpeg/voice params are byte-loyal to `doctask-sambaths` sources at `docs/issues/done/0026:62-76`.

## Package

- `tools/make_slides.py` — Chrome headless HTML → 1920×1080 PNGs, Paper & Ink editorial (`#FDFBF7` background, `#111111` caption bar, `Fraunces` serif beats + `IBM Plex Sans` body + `Geist Mono` code, `border-radius:14px`, `box-shadow` cards), caption bars baked (ffmpeg 8.1.1 has no `libass`)
- `tools/make_video.py` — `ffprobe`-timed concat: `probe(vo)+PAD(0.6)` per beat, `-f concat` with `fps=30,format=yuv420p`, `apad=whole_dur`, `libx264 medium crf 20` + `aac 128k` + `+faststart`
- `tools/make_bundle.py` — `writeup.pdf` (Chrome `print-to-pdf` from `docs/writeup.md`) + `thumbnail.jpg` (dedicated card) + `MANIFEST.txt` + `SCRUB-AUDIT.txt` (0 hits, solid-box never blur)
- `scripts/render_diagram.sh` — headless Chrome + vendored `tools/vendor/mermaid.min.js` ~3.3M (mermaid 10.9.1, `mermaid.initialize({theme:"base", ...})`) renders `docs/architecture.mmd` → `out/task4-bundle/architecture.{svg,png}` (2400×1400)
- `tools/vendor/mermaid.min.js` — vendored, offline render, no network at build time
- Voice: Kokoro TTS `am_eric` male, Apache 2.0, `speed 0.92` ad cadence, fully synthetic, disclosed everywhere (YouTube title+description + `writeup.md` + `MANIFEST`)

## Prerequisites (vendor deps)

Documented here and in `docs/writeup.md` prerequisites; no new proprietary binary beyond what `docs/issues/done/0026` required.

- `ffmpeg 8.1.1 + ffprobe` — `brew install ffmpeg` (verified: `ffmpeg -version` → 8.1.1, `ffprobe -version` → 8.1.1)
- `Chrome headless` — `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --headless` (verified: `Google Chrome 151.x`)
- `pip install kokoro` + `espeak-ng` + `spacy en_core_web_sm` G2P pre-load

```bash
brew install espeak-ng ffmpeg
pip install kokoro spacy
python -m spacy download en_core_web_sm
# verify G2P pre-load (no HF hang at synthesis time)
python -c "import spacy; spacy.load('en_core_web_sm'); print('G2P ok')"
espeak-ng --version
```

## Kokoro synthesis (keyless, same voice as doctask 2:05)

```bash
python - <<'PY'
from kokoro import KPipeline
import soundfile as sf
# explicit G2P path avoids HF download hang; am_eric speed 0.92 per spec
pipeline = KPipeline(lang_code='a')
# use en_core_web_sm already loaded via spacy; Kokoro will use espeak-ng G2P
for _, _, audio in pipeline("Hello from clausekeeper — a gap that names its cause.", voice='am_eric', speed=0.92):
    sf.write('/tmp/vo-test.aiff', audio, 24000)
    break
print("wrote /tmp/vo-test.aiff")
PY
ffprobe -v quiet -show_entries format=duration -of csv=p=0 /tmp/vo-test.aiff  # >0
```

Notes:
- `am_eric` is Apache 2.0, male, ad cadence; `speed 0.92` matches `doctask-sambaths/out/task4-bundle/doctask-demo.mp4` 2:05
- Explicit `KPipeline(lang_code='a')` + `spacy.load('en_core_web_sm')` pre-load avoids HuggingFace hang (see `docs/issues/done/0026:62`)
- Per-beat segments `out/media/vo-b*.aiff` are generated from `docs/media/narration-script.txt` which is derived verbatim from the final `docs/writeup.md` before synthesis; sum VO ≈115s±10s (reference: doctask 115s across 7 segments)

## Same package/voice reuse

This toolchain reuses **identical** Paper & Ink design system, ffmpeg params, and Kokoro `am_eric` voice that produced `doctask-sambaths/out/task4-bundle/doctask-demo.mp4` 2:05. No theme/ffmpeg/voice param drift — diff shows only `clausekeeper` bundle/paths renames.

## Deterministic render (no footage yet — smoke)

```bash
# placeholder smoke without committed transcripts (keeps CI green before 0016 lands)
mkdir -p docs/media/transcripts
echo "Clause 8.7 lost its evidence: section 'Disposition of nonconforming devices' was deleted by edit chg_42 at 2026-08-22T14:02:00Z, instruction 'remove the NCR section', job job_9f2." > docs/media/transcripts/placeholder.txt
cat > docs/architecture.mmd <<'MMD'
flowchart LR
  A[roster+save] --> B[link compact+durables]
  B --> C[edit HITL]
  C --> D[recheck doc-events]
  D --> E[show]
  E --> F[pack templates→pre-signed]
MMD
python tools/make_slides.py                          # -> out/media/slides/*.png 1920x1080
python tools/make_video.py                           # -> out/media/seg/b1.mp4, clausekeeper-demo.mp4 (≈ probe(vo)+0.6 within 0.3s)
scripts/render_diagram.sh out/task4-bundle           # -> out/task4-bundle/architecture.png
python tools/make_bundle.py                          # -> out/task4-bundle/{writeup.pdf,thumbnail.jpg,MANIFEST.txt,SCRUB-AUDIT.txt}
rg -n "sk-|Bearer|\.env" tools/ scripts/  # 0 hits
python -m pytest -q  # 46 passed, no surface change
```

For full render after 0016 lands (real transcripts):
```bash
python tools/make_slides.py && python tools/make_video.py && scripts/render_diagram.sh && python tools/make_bundle.py
ls out/task4-bundle/clausekeeper-demo.mp4 && ffprobe -v quiet -show_entries format=duration -of csv=p=0 out/task4-bundle/clausekeeper-demo.mp4
```

## Design reference

- CSS at `tools/make_slides.py: CSS = """... #FDFBF7 ... Fraunces ... IBM Plex Sans ... Geist Mono ..."""` — byte-loyal
- Video at `tools/make_video.py: PAD=0.6 / probe / -f concat / fps=30,format=yuv420p / libx264 medium crf 20 / aac 128k / +faststart`
- Bundle at `tools/make_bundle.py: MANIFEST + SCRUB-AUDIT`
- Diagram at `scripts/render_diagram.sh: Chrome + mermaid 10.9.1`
