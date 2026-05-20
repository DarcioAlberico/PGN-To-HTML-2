# -*- coding: utf-8 -*-
import io
import logging

import chess.pgn

try:
    from .models import PgnValidationIssue
except ImportError:
    from models import PgnValidationIssue


IMPORTANT_HEADERS = ("White", "Black", "Result")
UNKNOWN_VALUES = {"", "?", "????.??.??", "unknown", "n/a", "na", "none", "null"}


def _is_unknown(value):
    return (value or "").strip().lower() in UNKNOWN_VALUES


def _is_empty_default_game(game):
    if game is None:
        return True
    if game.comment:
        return False
    if list(game.mainline_moves()):
        return False
    return all(
        game.headers.get(key) == value
        for key, value in {
            "Event": "?",
            "Site": "?",
            "Date": "????.??.??",
            "Round": "?",
            "White": "?",
            "Black": "?",
            "Result": "*",
        }.items()
    )


def _game_context(game):
    white = game.headers.get("White", "?")
    black = game.headers.get("Black", "?")
    event = game.headers.get("Event", "?")
    return f"{white} - {black} | {event}"


def validate_pgn(pgn_text):
    issues = []
    text = (pgn_text or "").lstrip("\ufeff")
    if not text.strip():
        return [
            PgnValidationIssue(
                game_index=0,
                severity="error",
                message="O texto PGN esta vazio.",
            )
        ]

    pgn_io = io.StringIO(text)
    game_index = 0
    starts_with_tag = text.lstrip().startswith("[")

    while True:
        try:
            pgn_logger = logging.getLogger("chess.pgn")
            was_disabled = pgn_logger.disabled
            pgn_logger.disabled = True
            try:
                game = chess.pgn.read_game(pgn_io)
            finally:
                pgn_logger.disabled = was_disabled
        except Exception as exc:
            issues.append(
                PgnValidationIssue(
                    game_index=game_index + 1,
                    severity="error",
                    message=f"Falha ao ler PGN: {exc}",
                )
            )
            break

        if game is None:
            break
        if _is_empty_default_game(game) and game_index == 0 and not starts_with_tag:
            continue

        game_index += 1
        context = _game_context(game)

        for error in getattr(game, "errors", None) or []:
            issues.append(
                PgnValidationIssue(
                    game_index=game_index,
                    severity="error",
                    message=str(error),
                    context=context,
                )
            )

        for header_name in IMPORTANT_HEADERS:
            if _is_unknown(game.headers.get(header_name, "")):
                issues.append(
                    PgnValidationIssue(
                        game_index=game_index,
                        severity="warning",
                        message=f"Tag obrigatoria ou recomendada ausente: {header_name}.",
                        context=context,
                    )
                )

        if not list(game.mainline_moves()):
            issues.append(
                PgnValidationIssue(
                    game_index=game_index,
                    severity="warning",
                    message="A partida nao contem lances na linha principal.",
                    context=context,
                )
            )

    if game_index == 0:
        issues.append(
            PgnValidationIssue(
                game_index=0,
                severity="error",
                message="Nenhuma partida PGN valida foi encontrada.",
            )
        )

    return issues


def format_validation_report(issues, max_items=20):
    if not issues:
        return "PGN validado sem problemas encontrados."

    lines = []
    for issue in issues[:max_items]:
        prefix = "Erro" if issue.severity == "error" else "Aviso"
        game_label = f"partida {issue.game_index}" if issue.game_index else "arquivo"
        context = f" ({issue.context})" if issue.context else ""
        lines.append(f"{prefix} na {game_label}{context}: {issue.message}")

    remaining = len(issues) - len(lines)
    if remaining > 0:
        lines.append(f"... mais {remaining} problema(s).")

    return "\n".join(lines)
