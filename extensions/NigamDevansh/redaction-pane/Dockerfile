# Two stages, and the first one is why: the pane is a Vite build, the service is
# Python, and a reviewer should type one command rather than install Node to run
# a Word add-in.
#
# This image carries no LangGraph, no pgvector, no checkpointer — the analyst's
# dependencies are not this app's, and that separation is the whole claim of
# `cp -r extensions/redaction-pane` being a complete pull request.

# ── 1 · the task pane ─────────────────────────────────────────────────────
FROM node:24-slim AS pane
WORKDIR /ui
COPY ui/package.json ui/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY ui/ ./
RUN npm run build

# ── 2 · the service ───────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime
WORKDIR /app

RUN pip install --no-cache-dir uv==0.5.29

# Dependencies before source, so editing a Python file does not reinstall them.
#
# `[ner]` is tier 2 — GLiNER, which finds a name in prose locally, with no
# network call and no model API. It brings torch, and the CPU-only wheel is
# installed explicitly first: the default index resolves torch to a CUDA build
# of well over 2GB, in an image that will never see a GPU.
COPY pyproject.toml ./
# Which tier-3 provider SDK to bake in. openai is a base dependency and always
# present; gemini/anthropic each add their own extra. Driven by the LLM_PROVIDER
# build arg (docker-compose passes it from .env, default openai), so the image
# carries the ONE provider the deployment selected rather than all three. To
# switch provider, change LLM_PROVIDER in .env and `make up` — a plain restart
# re-reads .env but does not re-pull dependencies.
ARG LLM_PROVIDER=openai
RUN uv pip install --system --no-cache \
      --index-strategy unsafe-best-match \
      --extra-index-url https://download.pytorch.org/whl/cpu \
      "torch>=2.2" \
 && EXTRAS="ner" \
 && if [ "$LLM_PROVIDER" = "gemini" ]; then EXTRAS="$EXTRAS,gemini"; fi \
 && if [ "$LLM_PROVIDER" = "anthropic" ]; then EXTRAS="$EXTRAS,anthropic"; fi \
 && echo "LLM provider: ${LLM_PROVIDER} — installing extras [${EXTRAS}] (openai is always present)" \
 && uv pip install --system --no-cache ".[${EXTRAS}]"

# The model, downloaded at BUILD time rather than on first scan.
#
# Baking it in is a slower build once, against a stall on the first redaction
# every time a container starts — and a pane that hangs for ninety seconds the
# first time somebody clicks Scan is a pane they conclude is broken. It also
# means the running service needs no network for tiers 1 and 2 at all.
#
# **`ignore_patterns` is worth 1.1GB and it is not an optimisation.** Calling
# `GLiNER.from_pretrained` directly pulls the entire repository, which ships
# three ONNX exports beside the PyTorch weights — `model.onnx` (634MB),
# `model_fp16.onnx` (318MB) and `model_quint8.onnx` (188MB). This app loads
# `pytorch_model.bin` and never opens any of them. Measured, not assumed: the
# first build of this image was 1.93GB in this layer alone.
# `HF_HUB_OFFLINE` at RUN time, not just build time: the model is in the image,
# so a running container has no business reaching the Hub. Without it, a scan on
# a machine with no network waits out an HTTP timeout before falling back to the
# cache it already had — a redaction pane that appears to hang for thirty
# seconds because it is asking the internet about a file it is sitting on.
ENV HF_HOME=/opt/models \
    HF_HUB_DISABLE_TELEMETRY=1
# Into a plain DIRECTORY, not the Hub cache — which is what makes the pruning
# stick, and it took three attempts to find out why.
#
#   * The repository ships three ONNX exports beside the PyTorch weights:
#     `model.onnx` 634MB, `model_fp16.onnx` 318MB, `model_quint8.onnx` 188MB.
#     This app loads `pytorch_model.bin` and opens none of them.
#   * Deleting them afterwards does nothing: the Hub stores content in
#     hash-named blobs and the `*.onnx` names are symlinks, so
#     `find -name '*.onnx' -delete` removes 1.1GB of links and no data.
#   * Downloading with `ignore_patterns` into the CACHE does not work either —
#     `GLiNER.from_pretrained(repo_id)` re-resolves the snapshot and refuses an
#     incomplete one with `IncompleteSnapshotError`.
#
# A local directory has no completeness check and no network path at all.
# Measured: 1.93GB → 645MB.
#
# The second command is the check on the first: it is the same load the service
# performs, with the Hub switched OFF. If anything is missing, this build fails
# rather than the first scan failing on a machine with no network.
ENV GLINER_MODEL=/opt/gliner
RUN python -c "\
from huggingface_hub import snapshot_download; \
snapshot_download('knowledgator/gliner-pii-base-v1.0', local_dir='/opt/gliner', \
                  ignore_patterns=['onnx/*', '*.onnx'])" \
 && HF_HUB_OFFLINE=1 python -c "\
from gliner import GLiNER; GLiNER.from_pretrained('/opt/gliner')" \
 && rm -rf /opt/models/hub \
 && chmod -R a+rX /opt/gliner

ENV HF_HUB_OFFLINE=1

COPY service/ service/
COPY --from=pane /ui/dist ui/dist

# SQLite and any exported files live here; compose mounts a volume over it so a
# restart does not lose an audit log.
RUN mkdir -p /app/data && useradd --create-home --uid 1000 pane \
 && chown -R pane:pane /app
USER pane

EXPOSE 8443

# HTTPS is not optional — Office refuses an http:// task pane, even on
# localhost. The certificate is generated and TRUSTED ON THE HOST, because Word
# runs on the host, and mounted in read-only. That one step cannot be
# containerised; everything else here can.
CMD ["uvicorn", "service.app:app", \
     "--host", "0.0.0.0", "--port", "8443", \
     "--ssl-keyfile", "/certs/localhost.key", \
     "--ssl-certfile", "/certs/localhost.crt"]
