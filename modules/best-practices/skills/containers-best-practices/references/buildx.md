# Buildx & cache backend rules

Detailed explanation for each `BUILDX-NNN` rule. These cover the
build-execution side of BuildKit: cache backends, builder drivers,
multi-target builds with bake, and the `--load` / `--push` / `--output`
distinction that trips up most newcomers.

These rules pair with the BuildKit-side rules in `dockerfile.md`
(DOCKER-009 cache mounts, DOCKER-010 secret mounts, DOCKER-017
multi-arch cache scoping) and the security/build rules in
`security-build.md` (SEC-002 BuildKit-by-default, SEC-004
multi-platform, SEC-006 secret mounts).

Citations point at [Docker build docs](https://docs.docker.com/build/),
[cache backend reference](https://docs.docker.com/build/cache/backends/),
[buildx driver docs](https://docs.docker.com/build/builders/drivers/),
and [bake reference](https://docs.docker.com/build/bake/).

---

## BUILDX-001 — Pick a cache backend per scenario

**What.** BuildKit supports several `--cache-from` / `--cache-to`
backend types. The right choice depends on where the build runs:

| Backend | Best for | Driver requirement |
|---|---|---|
| `type=inline` | Image-exporter builds where you push to a registry anyway | All drivers |
| `type=registry` | Cross-CI portability; biggest fit when you push to a registry | `docker-container` / `kubernetes` (or `docker` with containerd image store) |
| `type=gha` | GitHub Actions specifically — built-in cache backend with action support | `docker-container` / `kubernetes` |
| `type=local` | Single-machine builds with a persistent cache dir | All drivers |
| `type=s3` | AWS-native CI (still flagged unreleased; preview only) | `docker-container` / `kubernetes` |
| `type=azblob` | Azure-native CI (also still preview) | `docker-container` / `kubernetes` |

**Why.** External caches are "almost essential" in ephemeral CI runners
(per the [official docs](https://docs.docker.com/build/cache/backends/))
because nothing persists between runs. Picking the right backend for
your CI platform makes the difference between 30-second cache hits and
5-minute cold builds.

The **default `docker` driver** has limited cache export — without
enabling the containerd image store, it only supports `inline` and a
narrow form of `gha`. If you want full cache backends, switch builder
drivers (BUILDX-005).

**How.** Decision tree:

- **Building on GitHub Actions?** Use `type=gha`. Cache lives in GHA's own cache store; no extra registry plumbing.
- **Building on any other CI, pushing to a registry?** Use `type=registry`. Tag the cache image at `myrepo/myimage:buildcache` (or per-branch).
- **Inline-only is acceptable?** Use `type=inline`. Simplest, embeds cache metadata in the pushed image — but mode is fixed at `min` and it doesn't separate cache from artifact.
- **Local dev, want a persistent cache dir between builds?** Use `type=local,dest=./buildcache` and `type=local,src=./buildcache`.

**When NOT to apply.** Single ephemeral build with no future runs — no
cache backend needed. Air-gapped environments where registry/cloud
backends are unreachable — fall back to `type=local`.

---

## BUILDX-002 — Set up `--cache-from` and `--cache-to` correctly

**What.** Cache reuse requires both flags. `--cache-from` reads cache;
`--cache-to` writes cache. Neither is automatic. They use the same
syntax shape:

```
--cache-from type=<backend>,ref=<location>[,parameters...]
--cache-to   type=<backend>,ref=<location>[,parameters...]
```

You can specify `--cache-from` multiple times to read from several
sources (e.g. the current branch's cache + a fallback to `main`).

**Why.** People often add `--cache-to` and assume cache reuse "just
works" — but the cache only exists *after* the first build with
`--cache-to`. The next build needs `--cache-from` pointing at the same
location to consume it. Forgetting `--cache-from` means the cache is
written but never read.

The `mode=` parameter controls how much is cached:

- `mode=min` (default) — only the layers exported into the final image. Smaller cache, faster export, but lower hit rate when builds rebuild intermediate stages.
- `mode=max` — all layers, including intermediate stages discarded by multi-stage builds. Bigger cache, higher hit rate, especially for multi-stage builds with lots of `RUN` steps. Worth the extra storage.

**How.** GitHub Actions, `type=gha`:

```yaml
- uses: docker/build-push-action@v6
  with:
    context: .
    push: true
    tags: ghcr.io/myorg/myapp:${{ github.sha }}
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

GitLab CI / any registry-pushing CI, `type=registry`:

```bash
docker buildx build --push \
  --tag ghcr.io/myorg/myapp:${CI_COMMIT_SHA} \
  --cache-from type=registry,ref=ghcr.io/myorg/myapp:buildcache-${CI_COMMIT_REF_SLUG} \
  --cache-from type=registry,ref=ghcr.io/myorg/myapp:buildcache-main \
  --cache-to   type=registry,ref=ghcr.io/myorg/myapp:buildcache-${CI_COMMIT_REF_SLUG},mode=max \
  .
```

Two important details from that example:

1. **Two `--cache-from` sources** — branch cache (most likely hit) with fallback to the `main` cache. First PR on a new branch still benefits from main's cache.
2. **Per-branch cache tag** — each branch writes its own cache (`buildcache-${BRANCH}`). Without this, parallel CI runs on different branches overwrite each other.

ECR / AWS-incompatible registry — add `image-manifest=true`:

```bash
--cache-to type=registry,ref=...,mode=max,oci-mediatypes=true,image-manifest=true
```

Cite: [Cache backends](https://docs.docker.com/build/cache/backends/),
[GHA cache backend](https://docs.docker.com/build/cache/backends/gha/),
[Registry cache backend](https://docs.docker.com/build/cache/backends/registry/).

**When NOT to apply.** When build time is dominated by I/O or external
network (cache won't help). Cold-start CI with no prior runs (cache
empty anyway — first run pays the cost regardless).

---

## BUILDX-003 — Know `--load` vs `--push` vs `--output`

**What.** A `docker buildx build` invocation produces output, and you
have to tell it *where to put the result*. There are three modes,
mutually exclusive:

| Flag | What it does | When to use |
|---|---|---|
| `--load` | Loads the built image into the local Docker daemon (so `docker images` / `docker run` see it). | Local dev, single-arch only. |
| `--push` | Pushes the built image directly to a registry without ever touching the local daemon. | CI builds, multi-arch. |
| `--output type=<exporter>,...` | The general form. Includes `--load` and `--push` as shortcuts; also supports `oci`, `tar`, `local`, `image,...`, etc. | When you want OCI archives, tarballs, or non-default exporters. |

**Why.** This is the most common "why isn't my multi-arch image working
locally" failure: `docker buildx build --platform linux/amd64,linux/arm64
--load .` **fails** with "docker exporter does not currently support
exporting manifest lists." The local daemon can only hold one
architecture per image, so `--load` is single-arch only.

Default behavior with the `docker-container` driver and no output flag:
the build runs but the result is **discarded**. Nothing happens. People
miss this because the build looks successful.

**How.**

```bash
# Local dev, single-arch — load into Docker so you can `docker run` it
docker buildx build --load --tag myimage:dev .

# CI, single or multi-arch — push to registry
docker buildx build --push \
  --platform linux/amd64,linux/arm64 \
  --tag ghcr.io/myorg/myapp:v1 .

# Multi-arch locally — must use --push (registry) or --output type=oci to a tar
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --output type=oci,dest=./multi-arch.tar \
  --tag myimage:multiarch .

# Export to a local image dir
docker buildx build --output type=local,dest=./dist .
```

If you build without specifying `--load`/`--push`/`--output` and the
build succeeds but `docker images` shows nothing — that's the discard
case. You forgot to tell buildx what to do with the result.

**When NOT to apply.** Never — every buildx build needs to specify an
output. If you don't, you wasted compute.

---

## BUILDX-004 — Use `docker buildx bake` for multi-target / declarative builds

**What.** `bake` lets you define build targets, args, platforms, tags,
and cache config in a file (HCL, JSON, or directly from a
`compose.yaml`) and invoke them by name. Replaces long
`docker buildx build` command lines with reusable, version-controlled
build definitions.

**Why.** Three real wins over raw `docker buildx build`:

1. **No more CLI sprawl.** A typical "build multi-arch with cache and SBOM" command is 6+ flags; bake captures that once.
2. **Multi-target builds.** Build several images in one invocation (`docker buildx bake` builds *all* default targets in parallel). One source of truth for the whole image set.
3. **Compose integration.** Bake reads `compose.yaml` directly — every service with a `build:` section becomes a target. The same compose file describes both runtime and build.

**How.** `docker-bake.hcl` (the canonical name):

```hcl
# Common config for all our images
target "_common" {
  context    = "."
  platforms  = ["linux/amd64", "linux/arm64"]
  cache-from = ["type=registry,ref=ghcr.io/myorg/api:buildcache"]
  cache-to   = ["type=registry,ref=ghcr.io/myorg/api:buildcache,mode=max"]
}

target "api" {
  inherits   = ["_common"]
  dockerfile = "Dockerfile"
  target     = "final"
  tags       = ["ghcr.io/myorg/api:latest"]
}

target "worker" {
  inherits   = ["_common"]
  dockerfile = "Dockerfile.worker"
  tags       = ["ghcr.io/myorg/worker:latest"]
}

# A group lets `bake all` build everything in parallel
group "all" {
  targets = ["api", "worker"]
}

# Default group invoked by bare `docker buildx bake`
group "default" {
  targets = ["api"]
}
```

```bash
docker buildx bake               # builds default group (api)
docker buildx bake all           # builds api + worker in parallel
docker buildx bake api worker    # explicit list
docker buildx bake --push all    # push everything
```

Compose-driven bake (the same compose file as your dev stack):

```bash
docker buildx bake --file compose.yaml --push
```

Cite: [Bake introduction](https://docs.docker.com/build/bake/introduction/),
[Bake reference](https://docs.docker.com/build/bake/reference/).

**When NOT to apply.** Single-image, single-arch projects with no
cache backend — `docker buildx build .` is simpler. When the team is
unfamiliar with HCL and the CLI hasn't grown to "too many flags" yet.

---

## BUILDX-005 — Pick the right builder driver

**What.** Buildx supports four drivers. The choice determines what
features are available:

| Driver | Default? | Multi-arch | Full cache export | Notes |
|---|---|---|---|---|
| `docker` | Yes | ❌ | Limited | Uses BuildKit baked into the Docker daemon. Simplest; least flexible. Auto-loads images. |
| `docker-container` | No | ✅ | ✅ | Spawns a BuildKit container. The "normal upgrade" — full feature set. |
| `kubernetes` | No | ✅ | ✅ | Spawns BuildKit pods in a K8s cluster. For build farms / large orgs. |
| `remote` | No | ✅ | ✅ | Connects to a pre-managed BuildKit daemon you run elsewhere. |

**Why.** Default `docker` driver hits walls fast:

- `docker buildx build --platform linux/amd64,linux/arm64 --push .` → fails ("docker exporter does not currently support exporting manifest lists").
- `--cache-to type=registry,...` → may fail or silently degrade depending on engine config.
- `--output type=oci` → not supported.

Each of these works the moment you switch to `docker-container`.

**How.** Create and use a `docker-container` builder:

```bash
# Create — runs once per machine
docker buildx create --name container --driver docker-container --use

# Optional: bootstrap immediately so first build doesn't pay the cost
docker buildx inspect --bootstrap

# Now multi-arch + full cache backends work
docker buildx build --platform linux/amd64,linux/arm64 --push -t myimage .
```

In CI, the `docker/setup-buildx-action` (GitHub Actions) creates a
`docker-container` builder by default — no extra setup needed.

For per-architecture native builders (avoid QEMU emulation cost):

```bash
# Append a remote arm64 native node to a builder
docker buildx create --name multi --driver docker-container --node node-amd64
docker buildx create --append --name multi --node node-arm64 ssh://user@arm-host
docker buildx use multi
```

Cite: [Buildx drivers](https://docs.docker.com/build/builders/drivers/).

**When NOT to apply.** Local single-arch dev where `--load` and "just
works" matter more than feature completeness — the default `docker`
driver is fine there.

---

## BUILDX-006 — Prefer native multi-arch runners over QEMU emulation

**What.** `docker buildx build --platform linux/amd64,linux/arm64`
under a single-node builder uses QEMU to emulate the non-native
architecture. This is *slow* — typically 3–10× slower than native
execution for CPU-heavy builds. For non-trivial builds, set up a
multi-node builder with one native node per architecture, or use
per-arch CI runners that combine into a manifest list.

**Why.** QEMU emulation tax is real:

- Compilation: 3–10× slower (gcc, rustc, golang under emulation grind).
- Native dependency builds (npm `node-gyp`, Python C extensions, Rust crates): often 5–10× slower; sometimes hit bugs unique to emulation.
- Time savings disappear after multiple cache misses.

For small images (single `apt-get install` + scripts), QEMU is fine —
the build is I/O bound, not CPU bound.

**How.** Option 1 — multi-node buildx builder (one builder, multiple
backends):

```bash
# Native amd64 (local)
docker buildx create --name multi --driver docker-container --platform linux/amd64 --node local
# Native arm64 (remote SSH)
docker buildx create --append --name multi --platform linux/arm64 \
  --node remote-arm64 ssh://user@arm64-host
docker buildx use multi

docker buildx build --platform linux/amd64,linux/arm64 --push -t myimage .
# amd64 stage runs on local node, arm64 stage runs on remote, in parallel
```

Option 2 — separate CI jobs per arch, then merge into a manifest list:

```yaml
# .github/workflows/build.yml — sketched
jobs:
  build-amd64:
    runs-on: ubuntu-latest
    steps:
      - uses: docker/build-push-action@v6
        with:
          platforms: linux/amd64
          tags: ghcr.io/myorg/api:${{ github.sha }}-amd64
          push: true

  build-arm64:
    runs-on: ubuntu-24.04-arm   # native ARM runner
    steps:
      - uses: docker/build-push-action@v6
        with:
          platforms: linux/arm64
          tags: ghcr.io/myorg/api:${{ github.sha }}-arm64
          push: true

  manifest:
    needs: [build-amd64, build-arm64]
    runs-on: ubuntu-latest
    steps:
      - run: |
          docker buildx imagetools create \
            --tag ghcr.io/myorg/api:${{ github.sha }} \
            ghcr.io/myorg/api:${{ github.sha }}-amd64 \
            ghcr.io/myorg/api:${{ github.sha }}-arm64
```

GitHub now offers free `ubuntu-*-arm` native ARM runners for public
repos; AWS Graviton, Oracle Ampere, and similar cover production-scale
needs.

Cite: [Multi-platform builds](https://docs.docker.com/build/building/multi-platform/),
[buildx imagetools create](https://docs.docker.com/reference/cli/docker/buildx/imagetools/create/).

**When NOT to apply.** Builds where QEMU overhead is small (tiny
images, I/O-bound steps). Hobby projects where the CI complexity isn't
worth the speedup. Single-arch deployments — don't pay multi-arch tax
at all (SEC-004).

---

## BUILDX-007 — Use `docker buildx debug build` for interactive step-through of failing builds

**What.** `docker buildx debug build` (GA since buildx v0.33.0; earlier
it was experimental) runs the build under an interactive debugger. For
editor-integrated debugging there's also `docker buildx dap build`,
which speaks the Debug Adapter Protocol so VS Code and other DAP clients
can drive the step-through. When a step fails, you get a shell
*inside the failing step's environment* — same filesystem, same env
vars, same uid — so you can poke at the state that caused the failure
without rebuilding from scratch.

```bash
docker buildx debug --invoke /bin/sh build .
```

Cite: [docker buildx debug build reference](https://docs.docker.com/reference/cli/docker/buildx/debug/build/).

**Why.** Before buildx debug, the canonical "I need to see what's
inside a failing build" hack was:

```dockerfile
# bad — wedge a sleep + exec into the failing step, then docker exec into it
RUN <thing-that-fails> || sleep 999
```

Then `docker exec -it <containerid> sh` to look around. Several
problems with this:

- Requires editing the Dockerfile (commit, push, hope you remember to
  revert).
- The sleeping container ties up a build slot.
- `docker exec` doesn't necessarily give you the same env as the `RUN`
  step (different PATH, different CWD, different uid depending on
  `USER`).
- Doesn't work for `COPY`/`ADD` failures — those don't run a shell.

`buildx debug build` solves all of these. It rebuilds up to (but not
through) the failing step, drops you into a shell at exactly the
filesystem and environment state the failing step would have seen, and
exits cleanly when you're done. No Dockerfile edits, no orphaned
containers.

It's also useful for *exploration*, not just failure — `buildx debug
build --invoke /bin/sh --on=success .` opens a shell at the end of a
successful build so you can verify the final filesystem state without
running the image.

**How.** Common workflows:

```bash
# Default: shell drops in on the first failing step
docker buildx debug --invoke /bin/sh build .

# Stop at a specific stage's end (useful when iterating mid-build)
docker buildx debug --invoke /bin/sh build --target builder .

# Open a shell on success too (for post-build poking)
docker buildx debug --invoke /bin/sh --on=error --on=success build .

# Use bash if it's installed in the image you're debugging
docker buildx debug --invoke /bin/bash build .
```

Inside the debug shell, useful commands:

- `cat /etc/passwd` — confirm which user the step ran as.
- `env` — see the full environment the step had.
- `ls -la` / `pwd` — verify CWD and visible files.
- `exit` — leaves the debugger. The build does **not** continue;
  buildx debug always halts at the inspected step.

To inspect a build that already failed (without re-running it),
buildx debug also supports replaying from a build's debug state — see
the reference doc for the full set of subcommands (`tree`, `list`,
`continue`).

**When NOT to apply.**

- Builds that work fine — there's no failure to inspect. (`--on=success` is occasionally useful for exploration, but daily.)
- buildx <0.12 — `debug build` doesn't exist; fall back to the `sleep 999` hack until you can upgrade.
- CI pipelines — `debug build` is interactive by definition. For non-interactive build diagnostics, prefer `--progress=plain` to see full step output.

---

## BUILDX-008 — `--sbom=true --provenance=mode=max` + registry-compatibility caveats

**What.** `docker buildx build --sbom=true --provenance=mode=max` emits
an OCI image **with attestations**: a separate manifest for the SBOM
(Software Bill of Materials) and another for SLSA build provenance.
The result is an OCI manifest *index* that points at the image
manifest plus the two attestation manifests.

Since BuildKit v0.21, OCI media types and the `image-manifest=true`
index form are the **default** output, so on a current toolchain pushing
to a modern registry this round-trips without any extra flags — the
workaround below is now mostly a legacy concern. The remaining catch:
some *older* registries don't accept OCI manifest indexes pointing
at non-image artifacts. ECR (pre-2024), older Harbor versions, and a
handful of internal/self-hosted registries fail the push or fail
subsequent pulls because they expect a manifest list to point at
*platform-image* manifests, not arbitrary attestation manifests.

**Why.** This is the most common "I followed the supply-chain
hardening guide and now my registry is broken" failure. The build
itself succeeds; the push either fails with a cryptic media-type error
or succeeds but subsequent `docker pull` fails with "manifest unknown"
or "unsupported media type." It's misdiagnosed as a build problem when
it's actually a registry-compatibility problem.

The fix has two paths depending on what your registry supports:

1. **Force the OCI media types and `image-manifest=true` index.**
   Modern OCI-compliant registries (ghcr.io, Docker Hub, GitLab,
   Quay, Artifactory ≥7.50, Harbor ≥2.10, ECR as of late 2024) accept
   this and round-trip attestations correctly:

   ```bash
   docker buildx build \
     --sbom=true --provenance=mode=max \
     --output type=image,name=ghcr.io/myorg/myapp:${TAG},push=true,oci-mediatypes=true,image-manifest=true \
     .
   ```

2. **Fall back to `mode=min`.** `--provenance=mode=min` embeds a
   smaller provenance attestation in the image manifest itself (no
   separate attestation manifest, no index complications). Less
   information than `mode=max` (omits build args, env, and source ref)
   but works on every registry that handles single-arch images:

   ```bash
   docker buildx build \
     --provenance=mode=min \
     --output type=image,name=oldregistry.example.com/myapp:${TAG},push=true \
     .
   ```

**How.** Decision: do you control the registry?

- **ghcr.io / Docker Hub / Quay / GitLab Container Registry / modern Harbor / modern ECR** → `mode=max` + `oci-mediatypes=true,image-manifest=true` and you get full attestations.
- **Older Harbor (<2.10), ECR before late 2024, custom in-house registries you don't control** → start with `mode=min` and check whether the registry round-trips it; upgrade the registry before you upgrade attestations.
- **Unsure** → push to a staging tag first, then `docker buildx imagetools inspect <ref>` to see whether the attestation manifests survived the push:

  ```bash
  docker buildx imagetools inspect ghcr.io/myorg/myapp:${TAG} --raw \
    | jq '.manifests[] | {mediaType, digest, "platform.architecture": .platform.architecture, "annotations.in-toto": .annotations."in-toto.io/predicate-type"}'
  ```

  You should see entries with `mediaType:
  application/vnd.oci.image.manifest.v1+json` and an `in-toto.io/predicate-type`
  annotation for the attestations. If they're missing, the registry
  stripped them.

BUILDX-008 is the "how to actually push attestations without breaking
the registry" detail; for the broader signing + SBOM workflow (cosign,
syft, sigstore keyless), reach for the dedicated tooling docs.

**When NOT to apply.**

- Projects with no supply-chain threat model — `mode=max` produces large attestations that nobody reads. Default to no attestations until there's a reason.
- Single-arch builds being loaded into the local daemon (`--load`) instead of pushed — the daemon's image store handles attestations differently, and you mostly don't care about attestations for local-only images.
- Registries that genuinely refuse attestations entirely (some air-gapped self-hosted setups) — keep `mode=min` and sign the image out-of-band with cosign instead. The cosign signature lands in a separate ref, sidestepping the manifest-index issue.

## BUILDX-009 — Use `bake` matrix targets + composable attributes for multi-variant builds

**What.** `docker buildx bake` (GA) matrix targets fork one target
definition into a cartesian product of variants (arch × environment ×
flavor) built in parallel, and composable HCL attributes let
`attest`/`cache-from`/`cache-to` be structured objects that inherit
cleanly instead of fragile CSV strings.

**Why.** Hand-maintaining a separate `docker buildx build ...` command per
variant drifts — someone bumps a cache ref or an attestation flag in one
and forgets the others. A matrix defines the variants once and keeps every
combination in lockstep; composable attributes stop the
`type=registry,ref=...,mode=max` string-concatenation errors.

**How.**

```hcl
# docker-bake.hcl
target "app" {
  name = "app-${tgt.arch}"
  matrix = { tgt = [{ arch = "amd64" }, { arch = "arm64" }] }
  platforms  = ["linux/${tgt.arch}"]
  cache-to   = [{ type = "registry", ref = "ghcr.io/org/cache:${tgt.arch}", mode = "max" }]
  cache-from = [{ type = "registry", ref = "ghcr.io/org/cache:${tgt.arch}" }]
}
```

```bash
docker buildx bake          # builds all matrix entries in parallel
```

**When NOT to apply.** Single-target, single-arch builds — a matrix is
overhead with nothing to vary. Extends BUILDX-004 (use bake at all); this
rule is specifically about the matrix/composable features.

---

## BUILDX-010 — Pin the Docker GitHub Actions by commit SHA

**What.** Pin `docker/setup-buildx-action`, `docker/build-push-action`,
and `docker/bake-action` (current majors v4 / v7 / v7) to a full commit
SHA, not a floating `@v7` tag.

**Why.** A version tag is mutable — a compromised or hijacked tag runs
attacker-controlled code in your build with registry credentials in
scope (the same supply-chain class as SEC-021). Pinning the SHA makes the
action immutable and auditable. Older majors also predate
`SOURCE_DATE_EPOCH` injection (DOCKER-030) and default attestations, so
the pin doubles as a floor.

**How.**

```yaml
- uses: docker/setup-buildx-action@<full-sha>   # v4.x
- uses: docker/build-push-action@<full-sha>     # v7.x
```

Resolve the SHA with
`gh api repos/docker/build-push-action/git/refs/tags/v7.0.0 --jq .object.sha`,
and let Dependabot/Renovate bump the SHA with the version comment.

**When NOT to apply.** Nothing real for CI pipelines — always pin. A
throwaway local experiment that never runs in CI can float.

---
