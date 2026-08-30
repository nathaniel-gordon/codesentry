# 5. Ship a CLI container and a GitHub Action, not a service

- Status: accepted
- Date: 2026-08-31

## Context

The delivery question for an analyzer is where it runs relative to the code it
reviews. The candidates in common use are: a hosted service that clones
repositories and posts back, a bot installed on the forge, a container run inside
someone else's CI, and a package developers install locally.

Nothing here is deployed today, so this decision is about what the artifacts
should be shaped for, not about migrating an existing installation.

## Problem

Pick one target, make the container and the docs fit it, and do not build the
plumbing the other targets would need.

## Options considered

1. **A hosted review service.** Would need an HTTP API, authentication, a
   database of installations, credentials for every repository it reads, a queue,
   and an on-call rotation. It also means the operator's proprietary source is
   copied onto someone else's machine, which is a hard sell for a linter.
2. **A GitHub App / bot.** Same custody problem, plus a webhook endpoint that has
   to be publicly reachable and a token store.
3. **A container run inside the user's CI**, with the checkout bind-mounted, plus
   a composite Action wrapping it for the common case, plus the wheel on PyPI for
   local and pre-commit use.
4. **Wheel only, no image.** Fine for local use; leaves CI users pinning a Python
   version and installing on every job.

## Decision

Option 3. The unit of deployment is a container image that runs the CLI over a
mounted tree, and the supported targets are:

- **GitHub Actions** via `action.yml` (installs the package, runs the analyzer,
  uploads SARIF to code scanning) - the primary target;
- **any CI that can run a container**, using the image directly;
- **a developer's machine**, via `pip install` and the pre-commit hook.

`docs/deployment.md` documents the first of those end to end. The image is
single-process, non-root, has a liveness HEALTHCHECK, and carries `git` so the
churn model works against a bind-mounted checkout.

## Reasoning

The analyzer needs three things: the source, a CPU, and somewhere to put a
report. CI already has all three, already has the checkout, and already has an
identity with the right to read it. A service would have to be *given* all of it,
which converts a stateless offline tool into a system with credentials, data
custody obligations and uptime.

Every capability the tool has is per-run and local: results cache to a file, the
report is an artifact, findings go to code scanning through SARIF - a format
GitHub already ingests. There is no cross-repository state that would justify a
central component.

## Trade-offs

- No dashboard, no history, no trend across runs. Each run is an artifact; the
  forge's code-scanning UI is where trends live, and only for what SARIF carries.
- The cache is per-runner and dies with the job unless the user caches the
  directory themselves. A service would keep it warm.
- Users must have Docker or Python in CI. Both are near-universal there.
- No multi-tenancy, no rate limiting, no quotas - because there is no tenant.

## Consequences

- No `docker-compose.yml` in this repository. Compose describes several processes
  that need to talk to each other; this image is one process with no listeners
  and no dependencies, and a compose file for it would be decorative.
- No `/healthz` endpoint. Health is `codesentry health`, which the container
  HEALTHCHECK runs (ADR 0004 covers the same reasoning for metrics).
- The image must stay small enough to pull on every CI job and must never require
  a network at run time. Adding a runtime dependency now has a delivery cost, not
  just a packaging one.
