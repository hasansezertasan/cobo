# syntax=docker/dockerfile:1
# Docker-action image for cobo fragment updates.
#
# Unlike the composite action (../action.yml), which runs the cobo that ships
# with the action ref, this variant installs cobo from PyPI for a fast,
# pre-bakeable image. Pin COBO_VERSION to the release matching your action ref
# when lockfile-schema fidelity matters.
FROM python:3.14-slim

# cobo shells out to git (via GitPython), which is absent from -slim images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

ARG COBO_VERSION=""
RUN pip install --no-cache-dir "cobo${COBO_VERSION:+==$COBO_VERSION}"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
