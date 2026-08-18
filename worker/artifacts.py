from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class Artifact:
    path: Path
    sha256: str


class ArtifactTracker:
    def __init__(self):
        self.uploaded: set[str] = set()

    def scan_new(self, root: Path) -> list[Artifact]:
        artifacts: list[Artifact] = []
        if not root.exists():
            return artifacts
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.name.startswith("_temp_") or path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            digest = sha256_file(path)
            if digest in self.uploaded:
                continue
            artifacts.append(Artifact(path=path, sha256=digest))
        artifacts.sort(key=lambda item: (item.path.stat().st_mtime, str(item.path)))
        return artifacts

    def mark_uploaded(self, artifact: Artifact) -> None:
        self.uploaded.add(artifact.sha256)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
