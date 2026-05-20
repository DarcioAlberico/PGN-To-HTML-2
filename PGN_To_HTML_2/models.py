# -*- coding: utf-8 -*-
from dataclasses import dataclass, field
from typing import List

try:
    from . import chess_diagrams
except ImportError:
    import chess_diagrams


@dataclass
class DiagramAsset:
    fen: str
    svg_path: str
    png_path: str
    web_path: str


@dataclass
class GameSummary:
    index: int
    white: str = ""
    black: str = ""
    event: str = ""
    site: str = ""
    date: str = ""
    eco: str = ""
    result: str = ""
    anchor: str = ""

    @property
    def title(self):
        players = " - ".join(part for part in (self.white, self.black) if part)
        title = players or f"Partida {self.index}"
        if self.eco:
            title += f" [{self.eco}]"
        return title


@dataclass
class PgnValidationIssue:
    game_index: int
    severity: str
    message: str
    context: str = ""


@dataclass
class ExerciseItem:
    game_index: int
    exercise_index: int
    fen: str
    question: str = ""
    solution: str = ""
    html: str = ""


@dataclass
class ConversionResult:
    blocks: List[str] = field(default_factory=list)
    summaries: List[GameSummary] = field(default_factory=list)
    exercise_blocks: List[str] = field(default_factory=list)
    exercises: List[ExerciseItem] = field(default_factory=list)
    diagram_assets: List[DiagramAsset] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    diagram_style: str = chess_diagrams.CLASSIC_DIAGRAM_STYLE
