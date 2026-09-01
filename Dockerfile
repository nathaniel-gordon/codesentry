# codesentry runs as a batch job: it starts, analyzes a checkout and exits.
# The image is therefore a CLI image, not a service image - no server, no port,
# and the only long-lived use is as a base for a CI runner.
#
# Two stages so the runtime layer carries no build backend and no wheel cache.
FROM python:3.14-slim AS builder

WORKDIR /src
# Only what the build backend reads. The corpus, tests and docs are not part of
# the distribution and would invalidate this layer on every edit.
COPY pyproject.toml README.md LICENSE ./
COPY reviewer ./reviewer

RUN python -m pip install --no-cache-dir --upgrade pip build \
    && python -m build --wheel --outdir /dist


FROM python:3.14-slim AS runtime

# git is optional at runtime: without it the churn model falls back to its
# static proxy and `codesentry health` reports the check as skipped rather than
# failed. It is installed because ranking findings by change-proneness is a real
# signal on a real checkout, and a mounted repository has the history for it.
RUN apt-get update \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /dist/*.whl /tmp/
RUN python -m pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl

# Non-root. The reviewed tree is untrusted input, and nothing here needs to
# write outside the directories the caller mounts.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin sentry
USER sentry
WORKDIR /work

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CODESENTRY_LOG_FORMAT=json \
    CODESENTRY_CACHE=/tmp/codesentry-cache/cache.db

# git refuses to read a repository owned by another uid, which is exactly what
# a bind-mounted checkout is. Without this the churn model silently degrades.
RUN git config --global --add safe.directory '*'

# Liveness rather than readiness: /work is whatever the caller mounted and may
# legitimately be empty or read-only, while a broken install must always fail.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["codesentry", "health", "--probe", "liveness"]

ENTRYPOINT ["codesentry"]
CMD ["--help"]
