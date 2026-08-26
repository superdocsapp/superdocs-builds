# BUG-002: Image-insert chat appends extra generic sections and placeholder.com figures

**Date:** 18 August 2026  
**What I did:** `generate_images_for_markdown` for healthcare after `warranted=yes` on sections 6 and 8. Chat instruction: insert one figure in that slide-equivalent only; do not change other sections; caption must start with `Presenter visual (not a slide)`.  
**Expected:** Sections 6 and 8 each gain one SuperDocs-hosted image; headings stay `## Slide-equivalent N — …`; no new sections.  
**Got instead:** Export kept the real §6/§8 GCS images **and** appended `## Section 6: Proof / Case Study` and `## Section 8: ROI / Business Case` with `via.placeholder.com` figures and “Please fill: Client Name” filler.  
**How badly it blocked:** Markdown scorer still found §6–§8 via the real headings, but the file was no longer a clean speaking script.  
**Minimal repro:** Upload a nine-section speaking script; chat once per image_eligible section asking to generate an image in that section only; export markdown.  
**Workaround adopted:** Strip the extra `## Section N` blocks and `placeholder.com` images from the healthcare export; keep the GCS (then locally mirrored) figures under the real slide-equivalent headings.
