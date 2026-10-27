# Copier integration

## cobo output reaches Copier projects unrendered, and cobo keeps ownership afterwards

**Id:** 2c75d682-d928-4d4b-b3c9-48c0abb0a2f8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** issue #243 discussion and the closed PR #249; a local `copier copy` check
**Verification:** uncorroborated
**Revisit when:** copier-pyproject ships its sealed `.gitignore` and shows how it actually does it, or Copier changes which files it renders

The maintainer's decision: run cobo next to a Copier template, not inside it. Copier seeds the project once with a sealed block, and from then on the generated project's own `cobo.lock` and cobo's scheduled sync keep it current, so two tools never own the same bytes. The sealed file ships without the template suffix (no `.jinja`), either pre-dumped or produced by a post-copy `_tasks` step running `cobo gitignore dump`, and is listed in `_skip_if_exists` so `copier update` does not three-way merge a block `cobo sync` also rewrites.

Evidence is mixed, so the entry carries the weaker grade. Confirmed locally: Copier copies a file without the template suffix byte for byte (a lone CR survives) and renders a `.jinja` file through Jinja (the CR becomes LF). Inferred and not yet checked against copier-pyproject or the Copier docs: the `_skip_if_exists` and `_tasks` behavior (a `_tasks` step also needs the user to pass `--trust`).

**Reason:** a renderer rewrites bytes it was never meant to touch, and a second updater on the same block only adds conflicts. cobo's pinned upstream and scheduled sync already do the maintaining.

**Rejected alternatives:**
- Making cobo-generated files part of the template and letting `copier update` maintain them: duplicates cobo's own update path and conflicts with it.
- Changing cobo's seal to suit the renderer: see [managed-blocks.md](managed-blocks.md#a-sealed-block-is-never-rewritten-to-survive-a-renderer).
