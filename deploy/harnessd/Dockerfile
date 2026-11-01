# harnessd, the HarnessWeaver sidecar (DESIGNS No. 24, ADR-0038).
#
# Build from the repository root:
#   docker build -f deploy/harnessd/Dockerfile -t harnessd .
# Serve the spec in the current directory (its overlays, profiles and code too):
#   docker run --rm -p 127.0.0.1:7070:7070 -e HARNESSD_TOKEN -v "$PWD:/app:ro" harnessd
#
# Base images are pinned by digest and the install follows uv.lock (RULES S5).
# harnessd runs as an unprivileged user and refuses to start without a token (S6).

ARG PYTHON_IMAGE=python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/harnessd
WORKDIR /src
COPY . .
# The sidecar and the first-party plugins a served spec commonly names. Add the
# plugins your specs use: --build-arg PACKAGES="harnessweaver-sidecar ...".
ARG PACKAGES="harnessweaver-sidecar harnessweaver-openai harnessweaver-anthropic harnessweaver-otel harnessweaver-cel"
RUN uv sync --frozen --no-dev --no-editable $(printf -- '--package %s ' $PACKAGES)

FROM ${PYTHON_IMAGE}
RUN useradd --system --uid 10001 --no-create-home --home-dir /nonexistent harnessd
COPY --from=build /opt/harnessd /opt/harnessd
ENV PATH=/opt/harnessd/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /app
USER 10001
EXPOSE 7070
# All interfaces of the container's own network; publish the port on 127.0.0.1
# of the host, as above, so only local apps reach it (S6).
ENTRYPOINT ["harnessd", "--host", "0.0.0.0"]
CMD ["harness.yaml"]
