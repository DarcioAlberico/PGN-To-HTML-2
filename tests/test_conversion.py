# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import threading
import unittest
import zipfile

import chess
import chess.engine


PROJECT_DIR = os.path.join(os.path.dirname(__file__), "..", "PGN_To_HTML_2")
PROJECT_DIR = os.path.abspath(PROJECT_DIR)
sys.path.insert(0, PROJECT_DIR)

import PGN_para_Livro_PERFEITO8 as app
import chess_diagrams


class ConversionTests(unittest.TestCase):
    def test_refactored_modules_are_importable(self):
        import converter
        import html_export
        import models
        import pgn_validation

        self.assertIs(converter.convert_pgn, app.convert_pgn)
        self.assertIs(converter.validate_pgn, app.validate_pgn)
        self.assertTrue(html_export.CSS.strip())
        self.assertIs(models.ConversionResult, app.ConversionResult)
        self.assertIs(pgn_validation.validate_pgn, app.validate_pgn)

    def test_validate_pgn_valid_game_has_no_issues(self):
        pgn = """[White "W"]
[Black "B"]
[Result "1-0"]

1. e4 e5 1-0
"""
        self.assertEqual(app.validate_pgn(pgn), [])

    def test_validate_pgn_reports_illegal_move(self):
        pgn = """[White "W"]
[Black "B"]
[Result "*"]

1. e4 e5 2. e5 *
"""
        issues = app.validate_pgn(pgn)

        self.assertTrue(any(issue.severity == "error" for issue in issues))
        self.assertTrue(any("illegal san" in issue.message.lower() for issue in issues))

    def test_validate_pgn_reports_missing_headers_and_empty_game(self):
        pgn = """[White "?"]
[Result "*"]

*
"""
        issues = app.validate_pgn(pgn)

        self.assertTrue(any(issue.severity == "warning" for issue in issues))
        self.assertTrue(any("Black" in issue.message for issue in issues))
        self.assertTrue(any("lances" in issue.message for issue in issues))

    def test_validation_report_formats_issues(self):
        issues = app.validate_pgn("")
        report = app.format_validation_report(issues)

        self.assertIn("Erro", report)
        self.assertIn("vazio", report)

    def test_css_presets_are_available_and_include_base_rules(self):
        import html_export

        options = dict(html_export.get_css_preset_options())
        self.assertIn("Clássico", options)
        self.assertIn("Moderno limpo", options)
        self.assertIn("Impressão A4", options)
        self.assertIn("E-reader", options)
        self.assertIn("Estudo tático", options)

        for preset in options.values():
            css_text = html_export.load_css_preset(preset)
            self.assertIn(".diagram", css_text)
            self.assertIn(".headers", css_text)

        modern_css = html_export.load_css_preset("modern")
        self.assertIn("Segoe UI", modern_css)

    def test_css_preset_keeps_merida_font_face(self):
        import html_export

        css_text = html_export.load_css_preset("tactics", diagram_style="merida")

        self.assertIn("@font-face", css_text)
        self.assertIn("chess-merida-diagram", css_text)

    def test_simple_pgn_generates_html(self):
        pgn = """[Event "NoFen"]
[Site "?"]
[Date "2026.03.23"]
[White "W"]
[Black "B"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 1-0
"""
        result = app.convert_pgn(pgn)

        self.assertEqual(len(result.blocks), 1)
        self.assertIn("1. e4 e5 2. Nf3 Nc6", result.blocks[0])
        self.assertFalse(result.warnings)

    def test_fen_game_does_not_fall_back_on_internal_errors(self):
        pgn = """[Event "WithFen"]
[Site "?"]
[Date "2026.03.23"]
[White "W"]
[Black "B"]
[Result "*"]
[FEN "8/8/8/8/8/8/8/K6k w - - 0 1"]
[SetUp "1"]

1. Ka2 *
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = app.convert_pgn(pgn, output_dir=temp_dir)

            self.assertEqual(len(result.blocks), 1)
            self.assertNotIn("lances ilegais", result.blocks[0])
            self.assertTrue(result.diagram_assets)
            self.assertTrue(os.path.exists(result.diagram_assets[0].svg_path))
            self.assertEqual(result.blocks[0].count('class="diagram"'), 1)
            self.assertEqual(result.blocks[0].count('class="analysis-links"'), 1)

    def test_diagram_marker_generates_position_diagram_after_move(self):
        pgn = """[Event "MidDiagram"]
[Site "?"]
[Date "2026.03.23"]
[White "W"]
[Black "B"]
[Result "*"]

1. e4 {#diagram Posicao depois de e4} e5 *
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = app.convert_pgn(pgn, output_dir=temp_dir)

            self.assertEqual(len(result.blocks), 1)
            self.assertEqual(len(result.diagram_assets), 1)
            self.assertTrue(os.path.exists(result.diagram_assets[0].svg_path))
            self.assertIn("Posicao depois de e4", result.blocks[0])
            self.assertNotIn("#diagram", result.blocks[0])
            self.assertIn(result.diagram_assets[0].web_path, result.blocks[0])

    def test_hash_bracket_comment_generates_diagram_after_move(self):
        pgn = """[Event "HashBracketDiagram"]
[Site "?"]
[Date "2026.03.23"]
[White "W"]
[Black "B"]
[Result "*"]

1. e4 {[#]} e5 *
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = app.convert_pgn(pgn, output_dir=temp_dir)

            self.assertEqual(len(result.diagram_assets), 1)
            self.assertIn('class="diagram"', result.blocks[0])
            self.assertNotIn("[#]", result.blocks[0])

    def test_infer_fen_from_html_cursor_after_move(self):
        pgn = """[Event "CursorDiagram"]
[Site "?"]
[Date "2026.03.23"]
[White "W"]
[Black "B"]
[Result "*"]

1. e4 e5 2. Nf3 *
"""
        result = app.convert_pgn(pgn)
        html_text = result.blocks[0]
        cursor_offset = html_text.index("e5") + len("e5")
        fen = app.infer_fen_from_html_cursor(pgn, html_text, cursor_offset)

        board = chess.Board()
        board.push_san("e4")
        board.push_san("e5")
        self.assertEqual(fen, board.fen())

    def test_infer_fen_from_html_cursor_before_first_move(self):
        pgn = """[Event "CursorInitial"]
[Site "?"]
[Date "2026.03.23"]
[White "W"]
[Black "B"]
[Result "*"]

1. d4 d5 *
"""
        result = app.convert_pgn(pgn)
        html_text = result.blocks[0]
        cursor_offset = html_text.index('<p class="mainline">')
        fen = app.infer_fen_from_html_cursor(pgn, html_text, cursor_offset)

        self.assertEqual(fen, chess.Board().fen())

    def test_empty_diagram_marker_comment_does_not_render_comment_text(self):
        pgn = """[Event "OnlyMarker"]
[Site "?"]
[Date "2026.03.23"]
[White "W"]
[Black "B"]
[Result "*"]

1. d4 {[%diagram]} d5 *
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = app.convert_pgn(pgn, output_dir=temp_dir)

            self.assertEqual(len(result.diagram_assets), 1)
            self.assertNotIn("[%diagram]", result.blocks[0])
            self.assertIn(result.diagram_assets[0].web_path, result.blocks[0])

    def test_exercise_marker_creates_exercise_metadata(self):
        pgn = """[Event "Exercise"]
[White "W"]
[Black "B"]
[Result "*"]

1. e4 {#exercise Encontre a melhor resposta} e5 *
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = app.convert_pgn(pgn, output_dir=temp_dir)

            self.assertEqual(len(result.exercises), 1)
            self.assertEqual(len(result.exercise_blocks), 1)
            self.assertIn("Encontre a melhor resposta", result.exercise_blocks[0])
            self.assertIn("e5", result.exercise_blocks[0])
            self.assertNotIn("#exercise", result.blocks[0])
            self.assertNotIn("Encontre a melhor resposta", result.blocks[0])
            self.assertNotIn('class="diagram"', result.blocks[0])
            self.assertIn('class="diagram"', result.exercise_blocks[0])

    def test_exercise_mode_only_outputs_exercises(self):
        pgn = """[Event "ExerciseOnly"]
[White "W"]
[Black "B"]
[Result "*"]

1. d4 {[%exercise "Brancas jogam"]} d5 *
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = app.convert_pgn(pgn, output_dir=temp_dir, exercise_mode="exercises")

            self.assertEqual(len(result.blocks), 1)
            self.assertIn('class="exercise"', result.blocks[0])
            self.assertIn("Brancas jogam", result.blocks[0])
            self.assertNotIn('class="headers"', result.blocks[0])

    def test_exercise_mode_both_outputs_book_and_exercises(self):
        pgn = """[Event "ExerciseBoth"]
[White "W"]
[Black "B"]
[Result "*"]

1. c4 {#exercise Melhor defesa?} e5 *
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = app.convert_pgn(pgn, output_dir=temp_dir, exercise_mode="both")

            self.assertEqual(len(result.blocks), 2)
            self.assertIn('class="headers"', result.blocks[0])
            self.assertIn('class="exercise"', result.blocks[1])

    def test_engine_analysis_is_optional_and_renders_badge(self):
        class FakeEngine:
            def analyse(self, board, limit):
                return {
                    "score": chess.engine.PovScore(chess.engine.Cp(34), chess.WHITE),
                    "pv": list(board.legal_moves)[:1],
                }

            def quit(self):
                self.closed = True

        pgn = """[Event "Engine"]
[White "W"]
[Black "B"]
[Result "*"]

1. e4 e5 *
"""
        result = app.convert_pgn(
            pgn,
            include_engine_analysis=True,
            engine_path="fake-stockfish",
            engine_depth=3,
            engine_factory=lambda _path: FakeEngine(),
        )

        self.assertEqual(len(result.analyses), 2)
        self.assertIn('class="engine-eval"', result.blocks[0])
        self.assertIn("+0.34", result.blocks[0])

    def test_engine_analysis_failure_is_warning_only(self):
        def broken_factory(_path):
            raise RuntimeError("engine missing")

        pgn = """[Event "EngineFail"]
[White "W"]
[Black "B"]
[Result "*"]

1. d4 d5 *
"""
        result = app.convert_pgn(
            pgn,
            include_engine_analysis=True,
            engine_path="missing-stockfish",
            engine_factory=broken_factory,
        )

        self.assertEqual(len(result.blocks), 1)
        self.assertIn("1. d4 d5", result.blocks[0])
        self.assertTrue(any("Stockfish" in warning for warning in result.warnings))

    def test_engine_analysis_can_be_cancelled(self):
        class FakeEngine:
            def analyse(self, board, limit):
                return {
                    "score": chess.engine.PovScore(chess.engine.Cp(10), chess.WHITE),
                    "pv": list(board.legal_moves)[:1],
                }

            def quit(self):
                pass

        cancel_event = threading.Event()
        calls = {"count": 0}

        def progress(_message):
            calls["count"] += 1
            cancel_event.set()

        pgn = """[Event "EngineCancel"]
[White "W"]
[Black "B"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 *
"""
        result = app.convert_pgn(
            pgn,
            progress_callback=progress,
            include_engine_analysis=True,
            engine_path="fake-stockfish",
            engine_factory=lambda _path: FakeEngine(),
            cancel_event=cancel_event,
        )

        self.assertFalse(result.blocks)
        self.assertTrue(any("cancelada" in warning.lower() for warning in result.warnings))

    def test_classic_diagram_cache_reuses_same_asset_for_same_fen(self):
        fen = "8/8/8/8/8/8/8/K6k w - - 0 1"
        with tempfile.TemporaryDirectory() as temp_dir:
            first = chess_diagrams.render_diagram_html(
                fen,
                output_dir=os.path.join(temp_dir, "Diagrams"),
                base_name="first",
                idx=1,
                web_root=temp_dir,
            )
            second = chess_diagrams.render_diagram_html(
                fen,
                output_dir=os.path.join(temp_dir, "Diagrams"),
                base_name="second",
                idx=99,
                web_root=temp_dir,
            )

            self.assertEqual(first["asset"]["svg_path"], second["asset"]["svg_path"])
            self.assertEqual(first["asset"]["png_path"], second["asset"]["png_path"])
            self.assertTrue(os.path.basename(first["asset"]["svg_path"]).startswith("diagram_"))

            files = os.listdir(os.path.join(temp_dir, "Diagrams"))
            self.assertEqual(len([name for name in files if name.endswith(".svg")]), 1)
            self.assertEqual(len([name for name in files if name.endswith(".png")]), 1)

    def test_clear_diagram_cache_removes_cached_assets_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            diagram_dir = os.path.join(temp_dir, "Diagrams")
            os.makedirs(diagram_dir)
            cached_svg = os.path.join(diagram_dir, "diagram_abc123def456.svg")
            cached_png = os.path.join(diagram_dir, "diagram_abc123def456.png")
            legacy_svg = os.path.join(diagram_dir, "diagram_partida_1_1.svg")
            for path in (cached_svg, cached_png, legacy_svg):
                with open(path, "w", encoding="utf-8") as file_obj:
                    file_obj.write("x")

            removed = chess_diagrams.clear_diagram_cache(diagram_dir)

            self.assertEqual(removed, 2)
            self.assertFalse(os.path.exists(cached_svg))
            self.assertFalse(os.path.exists(cached_png))
            self.assertTrue(os.path.exists(legacy_svg))

    def test_write_html_bundle_saves_css(self):
        pgn = """[Event "Save"]
[Site "?"]
[Date "2026.03.23"]
[White "W"]
[Black "B"]
[Result "1-0"]

1. d4 d5 1-0
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = app.convert_pgn(pgn, output_dir=temp_dir)
            html_path = os.path.join(temp_dir, "book.html")
            app.write_html_bundle(html_path, result)

            self.assertTrue(os.path.exists(html_path))
            self.assertTrue(os.path.exists(os.path.join(temp_dir, "style.css")))

    def test_html_bundle_includes_toc_and_game_anchors(self):
        pgn = """[Event "Book"]
[Site "S"]
[Date "2026.03.23"]
[White "W1"]
[Black "B1"]
[Result "1-0"]
[ECO "C20"]

1. e4 e5 1-0

[Event "Book"]
[Site "S"]
[Date "2026.03.24"]
[White "W2"]
[Black "B2"]
[Result "0-1"]

1. d4 d5 0-1
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = app.convert_pgn(pgn, output_dir=temp_dir)
            html_path = os.path.join(temp_dir, "book.html")
            app.write_html_bundle(html_path, result)

            self.assertEqual(len(result.summaries), 2)
            self.assertEqual(result.summaries[0].title, "W1 - B1 [C20]")

            with open(html_path, "r", encoding="utf-8") as file_obj:
                html_text = file_obj.read()

            self.assertIn('<nav class="toc">', html_text)
            self.assertIn('href="#game-1"', html_text)
            self.assertIn('href="#game-2"', html_text)
            self.assertIn('id="game-1"', html_text)
            self.assertIn('id="game-2"', html_text)

    def test_scan_and_filter_game_headers(self):
        pgn = """[Event "Book"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]
[ECO "C20"]

1. e4 e5 1-0

[Event "Book"]
[White "Carol"]
[Black "Alice"]
[Result "0-1"]
[ECO "D30"]

1. d4 d5 0-1
"""
        summaries = app.scan_pgn_headers(pgn)

        self.assertEqual([summary.index for summary in summaries], [1, 2])
        self.assertEqual(app.filter_game_summaries(summaries, player="alice"), summaries)
        self.assertEqual(
            [summary.index for summary in app.filter_game_summaries(summaries, eco="D30")],
            [2],
        )
        self.assertEqual(
            [summary.index for summary in app.filter_game_summaries(summaries, result="1-0")],
            [1],
        )

    def test_convert_pgn_selected_game_indexes(self):
        pgn = """[Event "Book"]
[White "W1"]
[Black "B1"]
[Result "1-0"]

1. e4 e5 1-0

[Event "Book"]
[White "W2"]
[Black "B2"]
[Result "0-1"]

1. d4 d5 0-1
"""
        result = app.convert_pgn(pgn, selected_game_indexes=[2])

        self.assertEqual(len(result.blocks), 1)
        self.assertEqual([summary.index for summary in result.summaries], [2])
        self.assertIn("W2", result.blocks[0])
        self.assertNotIn("W1", result.blocks[0])

    def test_convert_pgn_empty_selection_returns_warning(self):
        pgn = """[White "W"]
[Black "B"]
[Result "1-0"]

1. e4 e5 1-0
"""
        result = app.convert_pgn(pgn, selected_game_indexes=[])

        self.assertFalse(result.blocks)
        self.assertIn("Nenhuma partida", result.warnings[0])

    def test_merida_mode_generates_text_diagram_and_copies_font(self):
        pgn = """[Event "Merida"]
[Site "?"]
[Date "2026.03.23"]
[White "W"]
[Black "B"]
[Result "*"]
[FEN "8/8/8/8/8/8/8/K6k w - - 0 1"]
[SetUp "1"]

1. Ka2 *
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = app.convert_pgn(
                pgn,
                output_dir=temp_dir,
                diagram_style="merida",
            )
            html_path = os.path.join(temp_dir, "book.html")
            app.write_html_bundle(html_path, result)

            self.assertTrue(chess_diagrams.uses_merida_style(result.diagram_style))
            self.assertIn("chess-merida-diagram", result.blocks[0])
            self.assertFalse(result.diagram_assets)
            self.assertTrue(os.path.exists(os.path.join(temp_dir, "Fonts", "ChessMerida.ttf")))

            css_path = os.path.join(temp_dir, "style.css")
            with open(css_path, "r", encoding="utf-8") as file_obj:
                css_text = file_obj.read()
            self.assertIn("@font-face", css_text)
            self.assertIn("ChessMerida.ttf", css_text)

    def test_docx_export_writes_merida_diagram_as_font(self):
        pgn = """[Event "Docx"]
[Site "?"]
[Date "2026.03.23"]
[White "W"]
[Black "B"]
[Result "*"]
[FEN "8/8/8/8/8/8/8/K6k w - - 0 1"]
[SetUp "1"]

1. Ka2 *
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = app.convert_pgn(
                pgn,
                output_dir=temp_dir,
                diagram_style="merida",
            )
            docx_path = os.path.join(temp_dir, "book.docx")
            app.write_docx_file(docx_path, result)

            self.assertTrue(os.path.exists(docx_path))
            with zipfile.ZipFile(docx_path, "r") as archive:
                names = archive.namelist()
                document_xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")

            self.assertIn("word/document.xml", names)
            self.assertIn("Chess Merida", document_xml)
            self.assertIn('!""""""""#', document_xml)
            self.assertFalse(any(name.startswith("word/media/") for name in names))

    def test_docx_export_writes_classic_diagram_as_embedded_image(self):
        pgn = """[Event "DocxClassic"]
[Site "?"]
[Date "2026.03.23"]
[White "W"]
[Black "B"]
[Result "*"]
[FEN "8/8/8/8/8/8/8/K6k w - - 0 1"]
[SetUp "1"]

1. Ka2 *
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = app.convert_pgn(
                pgn,
                output_dir=temp_dir,
                diagram_style="classic",
            )
            docx_path = os.path.join(temp_dir, "book_classic.docx")
            app.write_docx_file(docx_path, result)

            self.assertTrue(os.path.exists(docx_path))
            with zipfile.ZipFile(docx_path, "r") as archive:
                names = archive.namelist()

            self.assertTrue(any(name.startswith("word/media/") for name in names))

    def test_pdf_export_writes_bundle_and_uses_renderer(self):
        pgn = """[Event "Pdf"]
[Site "?"]
[Date "2026.03.23"]
[White "W"]
[Black "B"]
[Result "*"]
[FEN "8/8/8/8/8/8/8/K6k w - - 0 1"]
[SetUp "1"]

1. Ka2 *
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = app.convert_pgn(pgn, output_dir=temp_dir)
            pdf_path = os.path.join(temp_dir, "book.pdf")
            seen = {}

            def fake_renderer(html_path, target_pdf_path):
                seen["html_exists"] = os.path.exists(html_path)
                seen["css_exists"] = os.path.exists(os.path.join(os.path.dirname(html_path), "style.css"))
                seen["diagram_exists"] = os.path.exists(
                    os.path.join(
                        os.path.dirname(html_path),
                        "Diagrams",
                        os.path.basename(result.diagram_assets[0].svg_path),
                    )
                )
                with open(target_pdf_path, "wb") as file_obj:
                    file_obj.write(b"%PDF-1.4\n%test\n")

            app.write_pdf_file(pdf_path, result, renderer=fake_renderer)

            self.assertTrue(os.path.exists(pdf_path))
            self.assertTrue(seen["html_exists"])
            self.assertTrue(seen["css_exists"])
            self.assertTrue(seen["diagram_exists"])

    def test_merida_png_renderer_is_not_blank(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            png_path = os.path.join(temp_dir, "merida.png")
            diagram_text = chess_diagrams.build_merida_diagram_text(
                "1K1k4/1PR5/8/8/8/8/8/r7 w - - 0 19"
            )
            chess_diagrams.render_merida_diagram_png(diagram_text, png_path)

            from PIL import Image

            image = Image.open(png_path).convert("RGB")
            pixels = image.load()
            non_white = 0
            for y in range(image.height):
                for x in range(image.width):
                    if pixels[x, y] != (255, 255, 255):
                        non_white += 1

            self.assertGreater(non_white, 5000)

    def test_pgn_without_event_tag_is_parsed(self):
        pgn = """[White "W"]
[Black "B"]
[Result "1-0"]

1. e4 e5 1-0
"""
        result = app.convert_pgn(pgn)

        self.assertEqual(len(result.blocks), 1)
        self.assertIn("(1) W", result.blocks[0])
        self.assertIn("1. e4 e5", result.blocks[0])
        self.assertFalse(result.warnings)

    def test_text_preamble_is_ignored_before_first_game(self):
        pgn = """Texto introdutorio que nao faz parte do PGN.

[White "W"]
[Black "B"]
[Result "1-0"]

1. d4 d5 1-0
"""
        result = app.convert_pgn(pgn)

        self.assertEqual(len(result.blocks), 1)
        self.assertIn("1. d4 d5", result.blocks[0])


if __name__ == "__main__":
    unittest.main()
