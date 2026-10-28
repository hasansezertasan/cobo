# Actions

## Two GitHub Action flavours: composite and Docker

**Id:** aeb9cede-e1bb-4263-be08-19f71bedb06d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** PR #55 notes; `docker/Dockerfile` and `docker/entrypoint.sh` comments; maintainer interview, 2026-10-28 (a hedged recollection)
**Verification:** uncorroborated
**Revisit when:** the Docker action's `image:` is switched to the prebuilt image, or CI dependency drift makes the split a problem

`action.yml` is a composite action: it runs the cobo that ships with the action ref and opens the update pull request itself. `docker/action.yml` runs a container that installs cobo from PyPI for a fast, pre-bakeable image; a Docker action cannot open a PR, so it only emits `sync-failed` and `summary` outputs and the calling workflow adds the PR step. Releases publish the image to ghcr.io with version, major and `latest` tags.

**Reason:** the stated reason is the speed of a pre-baked image for GitHub Actions use. The maintainer recalled this only tentatively, so the intent is inferred. The original design spec said to revisit a Docker action only if CI dependency drift became a problem; it was added later during review of #55.

**Deferred:** pointing the Docker action's `image:` at the prebuilt image was judged premature before 1.0.
