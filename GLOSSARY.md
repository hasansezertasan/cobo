# cobo

cobo dumps upstream template files into a tracked file as a cobo-owned region, and detects when that region or its upstream changes.

## Language

**Managed block**:
The cobo-owned region of a tracked file, between the fence markers; everything outside it belongs to the user.
_Avoid_: Managed region, section

**Fence**:
The begin/end marker pair that delimits a managed block; the end marker carries the seal.
_Avoid_: Markers (alone), guard

**Seal**:
The SHA-256 of a managed block's body, recorded in the end marker so a hand-edit is detectable.
_Avoid_: Block hash, checksum, fence hash

**Locally modified**:
A managed block whose body no longer matches its seal.
_Avoid_: Dirty, drifted (drift means upstream change)

**Eol policy**:
The per-fragment choice (`preserve`, `lf` or `lf-strict`) of how line endings are normalized before a body is sealed and written.
_Avoid_: Line-ending mode, newline setting

**Lone CR**:
A carriage return inside a line, not part of a line terminator; content, not a line ending (e.g. the `Icon[\r]` gitignore pattern); `lf-strict` removes it.
_Avoid_: Stray CR, bare CR
