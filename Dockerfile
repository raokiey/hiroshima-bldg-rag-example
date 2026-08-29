# syntax=docker/dockerfile:1
#
# Multi-stage build following pixi's official container deployment pattern
# (https://pixi.prefix.dev/latest/deployment/container/). The build stage
# resolves and installs the pixi-managed environment (from the linux-64
# entries in pixi.lock); the production stage is a minimal Ubuntu image with
# no pixi/conda toolchain, just the resolved environment plus app code.
#
# The frontend is NOT built here — frontend/src/static/ is already built and
# committed to the repo, so this image only needs the Python backend.

FROM ghcr.io/prefix-dev/pixi:0.78.0 AS build
WORKDIR /app

# Copy only the lockfile inputs first so dependency installation is cached
# independently of application code changes.
COPY pixi.toml pixi.lock ./
RUN pixi install --locked

# `pixi shell-hook` bakes environment activation (PATH, PYTHONHOME, etc.) into
# a script the production stage can source without pixi itself being present.
RUN pixi shell-hook -s bash > /shell-hook
RUN echo '#!/bin/bash' > /app/entrypoint.sh && \
    cat /shell-hook >> /app/entrypoint.sh && \
    echo 'exec "$@"' >> /app/entrypoint.sh

FROM ubuntu:24.04 AS production
WORKDIR /app

COPY --from=build /app/.pixi/envs/default /app/.pixi/envs/default
COPY --from=build --chmod=0755 /app/entrypoint.sh /app/entrypoint.sh

# Application code and the data it reads at runtime. GPKG_PATH etc. are only
# used by the offline pipeline (src/pipeline/*), not the running app, but the
# full data/ dir is small (~20MB) and copying it all avoids surprises if that
# ever changes.
COPY src/ src/
COPY data/ data/

# The pre-built RAG database (~140MB). Not tracked in git (see .gitignore)
# but present in the local build context, matching how the pipeline produces
# it (`pixi run enrich`) before this image is built.
COPY output/plateau_rag.duckdb output/plateau_rag.duckdb

# huggingface_hub's newer "Xet" fast-download backend (hf_xet) fails inside
# this minimal Ubuntu image with "Reqwest error: builder error" when
# sentence-transformers downloads the RURI model — confirmed by testing.
# Falling back to the plain HTTP downloader avoids it.
ENV HF_HUB_DISABLE_XET=1

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
