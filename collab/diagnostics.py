"""Structured diagnostics with stable text rendering."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Mapping

@dataclass(frozen=True)
class Diagnostic:
    code: str; category: str; message: str; exit_code: int=1; detail: str | None=None; hint: str | None=None; context: Mapping[str,object]=field(default_factory=dict)
    def render_text(self) -> str:
        lines=[f"ERROR: {self.message}"]
        if self.detail: lines.append(f"DETAIL: {self.detail}")
        if self.hint: lines.append(f"HINT: {self.hint}")
        return '\n'.join(lines)
