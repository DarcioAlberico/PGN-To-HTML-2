# -*- coding: utf-8 -*-
"""
API de conversão PGN.

Este módulo é a entrada preferida para código novo. No momento ele delega para
o backend legado para preservar compatibilidade durante a refatoração gradual.
"""

try:
    from .PGN_para_Livro_PERFEITO8 import (
        GameHtmlBuilder,
        analyze_game,
        convert_pgn,
        fallback_parse_game,
        format_validation_report,
        filter_game_summaries,
        infer_fen_from_html_cursor,
        iter_pgn_games,
        processar_pgn_worker,
        scan_pgn_headers,
        validate_pgn,
    )
except ImportError:
    from PGN_para_Livro_PERFEITO8 import (
        GameHtmlBuilder,
        analyze_game,
        convert_pgn,
        fallback_parse_game,
        format_validation_report,
        filter_game_summaries,
        infer_fen_from_html_cursor,
        iter_pgn_games,
        processar_pgn_worker,
        scan_pgn_headers,
        validate_pgn,
    )

__all__ = [
    "GameHtmlBuilder",
    "analyze_game",
    "convert_pgn",
    "fallback_parse_game",
    "format_validation_report",
    "filter_game_summaries",
    "infer_fen_from_html_cursor",
    "iter_pgn_games",
    "processar_pgn_worker",
    "scan_pgn_headers",
    "validate_pgn",
]
