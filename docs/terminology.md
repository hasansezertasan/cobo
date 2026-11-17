# Terminology and naming notes

Working notes from a naming discussion for a future skills repository that
would maintain collections of ready-made files (the sources cobo ships with).
Nothing here is decided except where marked. Nothing in the code has been
changed.

## What the five sources are

| cobo source    | Upstream repository                       | Produces        |
| -------------- | ----------------------------------------- | --------------- |
| `gitignore`    | `github/gitignore`                        | `.gitignore`    |
| `gitattributes`| `gitattributes/gitattributes`             | `.gitattributes`|
| `editorconfig` | `vinibrsl/editorconfig-templates`         | `.editorconfig` |
| `mise`         | `hasansezertasan/mise-cookbooks`          | `mise.toml`     |
| `licenses`     | `spdx/license-list-data` (`text/`)        | `LICENSE`       |

Shared trait: each upstream repo is a **collection of independent, standalone,
single-file items**. You pick one (or a few) and copy it into a repo root. The
repos are independent of cobo; cobo is only one consumer of them. Only
`mise-cookbooks` is owned by the cobo author.

## Findings

### 1. "Boilerplate" is the wrong word for these (to a typical developer)

In common usage a boilerplate is a **starter project**: many files that only
mean something together (`html5-boilerplate`, `react-boilerplate`,
`electron-react-boilerplate`). These collections are the opposite: many
independent files, each useful alone. A name like `boilerplate-skills` would
read as "skills for starter projects".

### 2. "Template" is loose, "artifact" is wrong, "preset" is partial

- **Template**: strictly means placeholders to fill in. Most of these files
  have none (`.gitignore`, `.gitattributes`, `.editorconfig`). Mise cookbooks
  are copy-then-edit starting points. License texts are the closest to true
  templates (some SPDX texts carry `<year>` / `<copyright holders>` slots, not
  verified here). Still the least-wrong widely understood word.
- **Artifact**: normally means build output. These are hand-written. Also
  collides with Claude's "Artifacts" feature.
- **Preset**: a pre-selected set of *settings*. Fits the four config sources;
  does not fit license texts (fixed legal text, not configuration).
- **Cookbook / recipe**: fits `mise-cookbooks` only (opinionated, author's own
  or lifted from mise docs).
- **Ready-made file**: accurate for all five, not an established term.

`spdx/license-list-data` is really a dataset (texts plus JSON metadata) that
cobo happens to use as a template source. Weakest fit in any category.

### 3. Sub-kinds worth keeping apart

- **Composable** collections: items are concatenated into one output
  (`gitignore`, `gitattributes`; `multi_dump=True` in `config/defaults.py`).
- **Pick-one** collections: `editorconfig`, `mise`, `licenses`
  (`multi_dump=False`).
- **Opinionated** collection: `mise-cookbooks`.
- **Nested** layout: `github/gitignore` has `Global/` and `community/`;
  `licenses` uses `subpath="text"`.

### 4. Conflicts found in this repository

| # | Where | Conflict |
| - | ----- | -------- |
| 1 | `README.md:1,9,47`, `pyproject.toml:3`, `src/cobo/__init__.py:1`, `src/cobo/cli.py:34`, `src/cobo/sources/discover.py` (`list_boilerplates`, `find_boilerplate`, ...), `src/cobo/source_commands.py` help strings | The project calls the items **boilerplates** everywhere, including public identifiers and CLI help. This is the word finding 1 argues against. |
| 2 | `README.md:147-148`: "alert you when upstream **templates** change — ... applied to **boilerplates**" | Both words for the same thing in one sentence. |
| 3 | `docs/fragment-updates.md:4,27,201` ("upstream template", "`Python` and `Node` templates", "template content has changed"), `docs/fragment-updates.md:56` ("macOS template") | Docs switch to **template** while code and README say boilerplate. |
| 4 | `src/cobo/config/defaults.py:27,38` ("gitattributes **templates**", "EditorConfig **templates**"), `:49` ("Mise **cookbook configs**"), `:60` ("SPDX license **texts**") | Four source descriptions use four different nouns and no consistent form. |
| 5 | `README.md:68,83` ("reusable Dockerfile **snippets**", "My Dockerfile snippets") | A third noun for the same kind of item. |
| 6 | `pyproject.toml:12-17` keywords: `boilerplate`, `cookbook`, `scaffold`, `template` | Four competing words as keywords. `scaffold` suggests generating whole projects, which cobo does not do. |
| 7 | **`fragment`**: `docs/fragment-updates.md`, `action.yml`, `cobo.lock` (`[[fragment]]`) | In cobo, a **fragment is the rendered output file** tracked in the lockfile (it can combine several boilerplates). Earlier in this discussion "fragment" was used for the *input* piece of a composable collection. These are opposite meanings. Do not reuse "fragment" for inputs. |
| 8 | `README.md:9-14`: "ships with five **sources**" followed by repo links | "Source" is overloaded: a cobo config entry (name, url, extension, subpath, flags) versus the upstream git repo behind it. The list shows source names with repo links, blurring the two. |

### 5. Open questions (nothing decided)

1. **What should the skills repo be called?** Pattern follows
   `application-skills` (`<subject>-skills`, one folder per skill under
   `skills/`). The subject should be the collection, not cobo (the repos are
   independent of cobo) and not "boilerplate" (finding 1).
   - `template-collection-skills`: leading candidate.
   - `file-template-collection-skills`: unambiguous, but long.
   - `template-catalog-skills`, `repo-files-skills`, `template-library-skills`:
     other options considered.
   - Ruled out so far: `boilerplate-skills` (finding 1), `cobo-skills` (repos
     are not bound to cobo).
2. **Which word is the umbrella term for one item?** "Template" is loose
   (finding 2); "ready-made file" is accurate but not established. Does the
   skills repo, and possibly cobo, adopt one?
3. **Should cobo's own vocabulary change to match?** Conflicts 1-6 touch public
   CLI help, package metadata and internal function names, so this is separate
   from naming the skills repo and may not be worth the churn.
4. **How should "source" be disambiguated** (conflict 8)? For example "source"
   for the cobo config entry and "upstream repo" for the git repository.
5. **Is `spdx/license-list-data` a "collection" in the same sense**, or a
   dataset treated as one by cobo? This decides whether the umbrella term has
   to cover it.
6. **Where do skills for upstream repos you do not own go** (`github/gitignore`,
   `spdx/license-list-data`)? They can cover picking, staleness checks and
   contributing, but not maintaining the repos directly. Is that in scope?

## Glossary (proposed)

Terms marked *cobo today* describe how this codebase already uses a word.

| Term | Meaning |
| ---- | ------- |
| **Collection** | An upstream git repo holding many independent single-file templates. Proposed name for what the five repos are. |
| **Template** | One ready-made file in a collection, meant to be copied into a repo and used as-is or edited. Used loosely: not every one has placeholders. |
| **Source** | *cobo today:* a configured entry (name, url, branch, extension, subpath, `multi_dump`, `inject_header`) pointing at one collection. Not the same as the repo itself. |
| **Upstream repo** | The git repository behind a source. Use this, not "source", when meaning the repo. |
| **Boilerplate** | *cobo today:* the name for one item in a source. Conventionally a starter project; avoid in new naming. |
| **Fragment** | *cobo today:* a rendered output file tracked in `cobo.lock`, possibly built from several boilerplates. Not an input piece. |
| **Composable collection** | A collection whose templates are concatenated into one output (`gitignore`, `gitattributes`). |
| **Pick-one collection** | A collection where you choose a single template (`editorconfig`, `mise`, `licenses`). |
| **Cookbook** | An opinionated, author-curated set of recipes. Specific to `mise-cookbooks`. |
| **Preset** | Pre-selected configuration. Fits the four config sources, not license texts. Not used by cobo. |
| **Artifact** | Build output. Do not use for these files. |
| **Skill** | An agent skill (a folder with a `SKILL.md`). The proposed skills repo holds one folder per skill, named for the task and collection, e.g. `sync-gitignore-collection`, `add-mise-cookbook`. |
