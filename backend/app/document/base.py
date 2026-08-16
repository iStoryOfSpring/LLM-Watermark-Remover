from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from backend.app.core.models import DocumentSnapshot, Patch


class DocumentAdapter(ABC):
    @abstractmethod
    def load(self, path: Path) -> DocumentSnapshot:
        raise NotImplementedError

    @abstractmethod
    def write(self, snapshot: DocumentSnapshot, patches: list[Patch], output_path: Path) -> None:
        raise NotImplementedError

    @abstractmethod
    def validate_output(self, source_path: Path, output_path: Path, patches: list[Patch]) -> None:
        raise NotImplementedError

