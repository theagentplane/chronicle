"""Append-only envelope storage."""

from __future__ import annotations

import json
from pathlib import Path

from chronicle.envelope.schema import Envelope


class EnvelopeStore:
    """Append-only JSONL store for immutable envelope records."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, envelope: Envelope) -> None:
        line = envelope.model_dump_json()
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read_all(self) -> list[Envelope]:
        envelopes: list[Envelope] = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    envelopes.append(Envelope.from_json(line))
        return envelopes

    def find_by_trace_id(self, trace_id: str) -> list[Envelope]:
        return [e for e in self.read_all() if e.trace_id == trace_id]

    def find_by_envelope_id(self, envelope_id: str) -> Envelope | None:
        for envelope in self.read_all():
            if envelope.envelope_id == envelope_id:
                return envelope
        return None

    @staticmethod
    def load_fixture(path: str | Path) -> Envelope:
        return Envelope.from_file(str(path))

    @staticmethod
    def save_fixture(envelope: Envelope, path: str | Path) -> Path:
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        envelope.write_file(str(dest))
        return dest

    @staticmethod
    def list_fixtures(directory: str | Path) -> list[Path]:
        root = Path(directory)
        if not root.exists():
            return []
        return sorted(root.glob("*.json"))

    def export_trace(self, trace_id: str, directory: str | Path) -> list[Path]:
        """Export all envelopes for a trace as individual fixture files."""
        dest = Path(directory)
        dest.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for i, envelope in enumerate(self.find_by_trace_id(trace_id)):
            filename = f"{trace_id}-{envelope.node_id}-{i:03d}.json"
            path = dest / filename
            envelope.write_file(str(path))
            paths.append(path)
        return paths
