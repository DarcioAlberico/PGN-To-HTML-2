# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Callable, Iterable

import chess
import chess.engine

try:
    from .models import MoveAnalysis
except ImportError:
    from models import MoveAnalysis


class AnalysisCancelled(Exception):
    pass


def _score_to_fields(score):
    if score is None:
        return None, None

    mate = score.mate()
    if mate is not None:
        return None, mate
    return score.score(mate_score=100000), None


def analyze_game(
    game,
    engine_path,
    depth=12,
    game_index=1,
    engine_factory: Callable[[str], object] | None = None,
    progress_callback: Callable[[str], None] | None = None,
    cancel_callback: Callable[[], bool] | None = None,
) -> list[MoveAnalysis]:
    if not engine_path:
        return []

    depth = max(1, int(depth or 12))
    factory = engine_factory or chess.engine.SimpleEngine.popen_uci
    engine = factory(engine_path)
    analyses = []
    board = game.board()
    moves = list(game.mainline_moves())
    total = len(moves)

    try:
        for ply, move in enumerate(moves, start=1):
            if cancel_callback and cancel_callback():
                raise AnalysisCancelled("Analise cancelada pelo usuario.")
            san = board.san(move)
            board.push(move)
            if progress_callback:
                progress_callback(f"Analisando partida {game_index}, lance {ply}/{total}...")

            info = engine.analyse(board, chess.engine.Limit(depth=depth))
            if cancel_callback and cancel_callback():
                raise AnalysisCancelled("Analise cancelada pelo usuario.")
            pov_score = info.get("score")
            if pov_score is not None:
                pov_score = pov_score.pov(chess.WHITE)
            score_cp, mate = _score_to_fields(pov_score)

            best_move_san = ""
            pv = info.get("pv") or []
            if pv:
                try:
                    best_move_san = board.san(pv[0])
                except Exception:
                    best_move_san = str(pv[0])

            analyses.append(
                MoveAnalysis(
                    game_index=game_index,
                    ply=ply,
                    san=san,
                    fen=board.fen(),
                    score_cp=score_cp,
                    mate=mate,
                    best_move=best_move_san,
                )
            )
    finally:
        quit_method = getattr(engine, "quit", None)
        if quit_method:
            quit_method()

    return analyses


def analyses_by_ply(analyses: Iterable[MoveAnalysis] | None):
    return {analysis.ply: analysis for analysis in analyses or []}
