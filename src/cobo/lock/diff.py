"""Pure drift computation: stored blobs vs current blobs. No git, no FS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from cobo.lock.schema import Fragment


@dataclass(frozen=True, slots=True)
class FileDrift:
    """A single input file whose content moved since it was locked.

    Attributes:
        name: The boilerplate name.
        path: Repo-relative path of the file.
        old_blob: Blob SHA recorded in the lock.
        new_blob: Current blob SHA, or None when the file is gone/unresolved.
    """

    name: str
    path: str
    old_blob: str
    new_blob: str | None

    def __post_init__(self) -> None:
        """Reject a non-drift: a FileDrift must record an actual change.

        Raises:
            ValueError: When ``old_blob`` equals ``new_blob`` (no drift), which
                would otherwise be a constructible but meaningless instance.
        """
        if self.old_blob == self.new_blob:
            msg = f"FileDrift {self.path!r} requires old_blob != new_blob"
            raise ValueError(msg)


def compute_fragment_drift(
    fragment: Fragment, current_blobs: Mapping[str, str | None]
) -> tuple[FileDrift, ...]:
    """Compare a fragment's locked blobs against current blobs.

    Args:
        fragment: The locked fragment.
        current_blobs: Map of repo-relative path -> current blob SHA (or None
            when the file could not be resolved in the refreshed clone).

    Returns:
        One FileDrift per file whose current blob differs from the locked blob.
    """
    drifts: list[FileDrift] = []
    for file in fragment.files:
        current = current_blobs.get(file.path)
        if current != file.blob:
            drifts.append(
                FileDrift(
                    name=file.name,
                    path=file.path,
                    old_blob=file.blob,
                    new_blob=current,
                )
            )
    return tuple(drifts)
