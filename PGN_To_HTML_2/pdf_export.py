# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
from pathlib import Path

try:
    from . import chess_diagrams
    from .html_export import build_css, ensure_diagram_font_css, gerar_html_final
except ImportError:
    import chess_diagrams
    from html_export import build_css, ensure_diagram_font_css, gerar_html_final


def _copy_pdf_support_files(conversion_result, output_dir):
    if chess_diagrams.uses_merida_style(conversion_result.diagram_style):
        chess_diagrams.copy_support_files(conversion_result.diagram_style, output_dir)

    if not conversion_result.diagram_assets:
        return

    diagram_dir = os.path.join(output_dir, "Diagrams")
    os.makedirs(diagram_dir, exist_ok=True)
    for asset in conversion_result.diagram_assets:
        for asset_path in (asset.svg_path, asset.png_path):
            if not asset_path or not os.path.isfile(asset_path):
                continue
            target_path = os.path.join(diagram_dir, os.path.basename(asset_path))
            if os.path.abspath(asset_path) == os.path.abspath(target_path):
                continue
            shutil.copyfile(asset_path, target_path)


def _write_pdf_html_bundle(html_path, conversion_result, css_text=None):
    output_dir = os.path.dirname(html_path)
    os.makedirs(output_dir, exist_ok=True)
    _copy_pdf_support_files(conversion_result, output_dir)

    font_href = chess_diagrams.get_diagram_font_href(conversion_result.diagram_style)
    css_text = css_text if css_text is not None else build_css(
        diagram_style=conversion_result.diagram_style,
        font_href=font_href,
    )
    css_text = ensure_diagram_font_css(css_text, conversion_result.diagram_style)

    with open(os.path.join(output_dir, "style.css"), "w", encoding="utf-8") as file_obj:
        file_obj.write(css_text)

    with open(html_path, "w", encoding="utf-8") as file_obj:
        file_obj.write(
            gerar_html_final(
                conversion_result.blocks,
                css_externo=True,
                diagram_style=conversion_result.diagram_style,
                font_href=font_href,
                summaries=conversion_result.summaries,
                css_text=css_text,
            )
        )


def _render_pdf_with_playwright(html_path, pdf_path):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Exportacao PDF exige o pacote 'playwright'. Instale com "
            "'python -m pip install playwright' e depois "
            "'python -m playwright install chromium'."
        ) from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(Path(html_path).as_uri(), wait_until="networkidle")
            page.pdf(path=pdf_path, format="A4", print_background=True)
        finally:
            browser.close()


def write_pdf_file(pdf_path, conversion_result, css_text=None, renderer=None):
    if not conversion_result.blocks:
        raise RuntimeError("Nao ha conteudo convertido para exportar em PDF.")

    output_dir = os.path.dirname(pdf_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pgn_pdf_") as temp_dir:
        html_path = os.path.join(temp_dir, "book.html")
        _write_pdf_html_bundle(html_path, conversion_result, css_text=css_text)

        pdf_renderer = renderer or _render_pdf_with_playwright
        pdf_renderer(html_path, pdf_path)

    if not os.path.exists(pdf_path):
        raise RuntimeError("A exportacao PDF terminou sem criar o arquivo de saida.")

    return pdf_path
