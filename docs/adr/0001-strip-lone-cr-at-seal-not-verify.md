# Strip lone CRs at seal time via `lf-strict`, not tolerate them at verify time

Copier templates render sealed files through Jinja, which turns every lone CR into LF (`Icon[\r]` becomes `Icon[\n]`), so a block sealed with `eol = "lf"` reads as locally modified forever. We added an `lf-strict` eol policy that also removes lone CRs before sealing, and left verification untouched: tolerating the mangled file at verify time would report "up to date" for a `.gitignore` whose pattern is already split in two, and would need a new canonical seal form. `lf` keeps its 0.6.0 behavior (cobo#124, cobo#226) so existing seals stay valid.

## Considered Options

- **Verify-side normalization under `lf`**: rejected; hides the corruption and changes how seals are computed.
- **`lf-strict` seal-side opt-out**: chosen; the seal contains nothing a renderer can rewrite.

## Consequences

Consumers who render a macOS seal through Jinja must re-dump with `--eol lf-strict`; their `Icon[\r]` pattern is dropped. Existing `lf` seals that were rendered stay `locally modified` until re-dumped; there is no migration.
