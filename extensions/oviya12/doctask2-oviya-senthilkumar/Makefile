# Spec-driven client generation pipeline for the SuperDocs API.
# `make all` runs the whole thing; individual stages are available too.
# Real work lives in scripts/pipeline.sh so it runs identically on CI and locally.

.PHONY: all fetch generate compat mock smoke clean

all:            ## Run the full pipeline: fetch -> generate -> compat -> mock -> smoke
	bash scripts/pipeline.sh

fetch:          ## Re-fetch the pinned spec versions and rebuild the breaking demo
	bash scripts/fetch.sh

compat:         ## Regenerate the compatibility report (old -> new) with CI gate
	docker run --rm -v "$(CURDIR):/work" tufin/oasdiff@sha256:8f7daabad46bc986290da569589046813de8bfd669fc4bffc3c78060ab2a548d changelog -f json \
	  /work/specs/superdocs-old.json /work/specs/superdocs-new.json > reports/changelog.json
	python scripts/compat.py --changelog reports/changelog.json \
	  --base specs/superdocs-old.json --revision specs/superdocs-new.json --out reports --gate

mock:           ## Start the Prism mock server on :4010 (Ctrl-C to stop)
	docker run --rm --name superdocs-mock -p 4010:4010 -v "$(CURDIR):/tmp" \
	  stoplight/prism@sha256:08dc16243047a3263beca814b544a5be81e9ec25ca5757cdc4170c84f7431355 mock -h 0.0.0.0 /tmp/specs/superdocs-new.json

clean:          ## Remove generated clients, reports, and local deps
	rm -rf clients/python clients/typescript reports/changelog*.json \
	       reports/compat.* reports/breaking-demo .venv node_modules
	-docker rm -f superdocs-mock 2>/dev/null
