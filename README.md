# cobo: copy boilerplates from configurable git repositories

[![CI](https://github.com/hasansezertasan/cobo/actions/workflows/ci.yml/badge.svg)](https://github.com/hasansezertasan/cobo/actions/workflows/ci.yml)
[![Codecov](https://codecov.io/gh/hasansezertasan/cobo/branch/main/graph/badge.svg)](https://codecov.io/gh/hasansezertasan/cobo)
[![PyPI - Version](https://img.shields.io/pypi/v/cobo.svg)](https://pypi.org/project/cobo)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/cobo.svg)](https://pypi.org/project/cobo)
[![License - MIT](https://img.shields.io/github/license/hasansezertasan/cobo.svg)](https://opensource.org/licenses/MIT)

`cobo` (short for **copy boilerplates**) is a command-line tool for fetching boilerplate files from configurable git repositories. It ships with five sources baked in:

- **`gitignore`** — GitHub's [`github/gitignore`](https://github.com/github/gitignore) templates
- **`gitattributes`** — community [`gitattributes/gitattributes`](https://github.com/gitattributes/gitattributes) templates
- **`editorconfig`** — [`vinibrsl/editorconfig-templates`](https://github.com/vinibrsl/editorconfig-templates)
- **`mise`** — [`mise-cookbooks`](https://github.com/hasansezertasan/mise-cookbooks) configs
- **`licenses`** — SPDX license texts from [`spdx/license-list-data`](https://github.com/spdx/license-list-data)

You can add your own sources via a single TOML config file.

`cobo` is the successor to [`micoo`](https://github.com/hasansezertasan/micoo), which is now deprecated.

## Installation

```sh
uv tool install cobo
```

or

```sh
pipx install cobo
```

or

```sh
mise install pipx:cobo
```

## Quick start

Fetch the baked sources once:

```sh
cobo update
```

List boilerplates in a source:

```sh
cobo gitignore list
cobo mise list
```

Dump one to stdout:

```sh
cobo mise dump python > mise.local.toml
cobo gitignore dump Python Node > .gitignore
cobo gitattributes dump Python > .gitattributes
cobo editorconfig dump Python > .editorconfig
```

## Configuration

A user config file at the platform-specific config path (e.g.
`~/.config/cobo/config.toml` on Linux) can override baked sources or add
new ones.

Suppose you maintain a repo of reusable Dockerfile snippets laid out like
this:

```text
example/dockerfiles  (https://example.invalid/you/dockerfiles)
└── templates/
    ├── python.Dockerfile
    ├── node.Dockerfile
    └── rust.Dockerfile
```

The matching source entry:

```toml
[sources.dockerfiles]
description = "My Dockerfile snippets"
url = "https://example.invalid/you/dockerfiles"
branch = "main"
extension = ".Dockerfile"
subpath = "templates"
multi_dump = false
inject_header = true
comment_prefix = "#"
```

Field semantics:

- `extension` — suffix used to discover boilerplates. A file
  `templates/python.Dockerfile` is exposed as the name `python`.
- `subpath` — only scan this subdirectory of the clone (omit to scan the
  whole repo).
- `branch` — branch to track; pin to whatever the upstream default is.
- `multi_dump` — when `true`, `dump` accepts multiple names and
  concatenates them (used by `gitignore` and `gitattributes`).
- `inject_header` / `comment_prefix` — prepend a provenance comment block
  on dump using the given line prefix.

Once added, the source becomes a first-class subcommand:

```sh
cobo dockerfiles list             # python, node, rust
cobo dockerfiles dump python      # contents of templates/python.Dockerfile
```

> **Trust boundary.** The config file is a trust boundary: `url` and `branch`
> values are passed directly to `git`. Only add sources you trust.

> **Branch drift.** Baked-in sources pin the upstream default branch (some
> `main`, others `master`). If an upstream renames its default branch, override
> the `branch` field in your user config until the baked default is updated.

> **Disposable cache.** Source clones under the cache root
> (`cobo root` / `cobo <source> root`) are managed by `cobo update`, which
> performs `fetch` + hard reset + `clean -fdx`. Any local edits, untracked
> files, or commits inside those clones are discarded on the next update —
> never use the cache as a working tree.

## Command reference

```
cobo
├── update              (clone/pull all sources)
├── version
├── info
├── list-sources
├── root                (cache directory path)
├── config              (resolved merged config)
├── config-path         (user config file path)
└── <source>            (one subcommand per configured source)
    ├── update
    ├── list
    ├── search <term>
    ├── dump <name>...
    ├── root            (this source's clone path)
    └── remote          (this source's git URL)
```

## Keeping fragments up to date

cobo can track dumped boilerplates and alert you when upstream templates change —
the same Dependabot/Renovate pattern applied to boilerplates.

**Record a dump:**

```sh
cobo gitignore dump Python Node --out .gitignore --lock
```

`--lock` writes a `cobo.lock` file: cobo walks up from the current working
directory for the nearest existing `cobo.lock` and updates it, or creates one
in the current working directory if none is found. Re-run after
`cobo gitignore update` to refresh the pin. (`--lock` requires `--out`.)

Already have dumped files from before the lockfile? Adopt them from their
provenance headers:

```sh
cobo lock import .gitignore .editorconfig   # reconstruct lock entries from headers
```

**Check for drift:**

```sh
cobo check          # Rich table; exits 0 (clean), 1 (updates available), 2 (no/invalid lock)
cobo check --strict # also exit non-zero when a fragment errored (CI gate)
cobo check --json   # machine-readable JSON with outdated_count, error_count, fragments
cobo check --exclude '.github/*'  # skip fragments whose path matches a glob
```

**Apply updates:**

```sh
cobo sync           # re-renders outdated fragments and advances cobo.lock
cobo sync --dry-run # shows changes without writing
cobo sync --exclude '.github/*'  # leave matching fragments untouched
```

Commit the updated output files and `cobo.lock` together.

**Hold a fragment back:** set `update = false` in its `[[fragment]]` block in
`cobo.lock`; `check` and `sync` skip it and show it as "held".

**Automate with GitHub Actions:** add `hasansezertasan/cobo@v1` to a weekly
workflow — it runs `cobo sync` and opens a PR when fragments drift. Requires
`permissions: contents: write` and `pull-requests: write`. A pre-built Docker
variant (`hasansezertasan/cobo/docker@v1`) is also available for faster
cold-starts.

See [docs/fragment-updates.md](docs/fragment-updates.md) for the full guide:
lockfile format, exit-code tables, provenance headers, and a ready-to-paste
consuming workflow.

## Author

Maintained by [Hasan Sezer Taşan](https://github.com/hasansezertasan).

## License

MIT. See [LICENSE](https://github.com/hasansezertasan/cobo/blob/main/LICENSE).
