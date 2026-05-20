# -*- coding: utf-8 -*-
import os
import re
import html
from datetime import datetime
from functools import lru_cache

try:
    from . import chess_diagrams
except ImportError:
    import chess_diagrams


STYLE_PRESETS = {
    "classic": ("Clássico", None),
    "modern": ("Moderno limpo", "modern.css"),
    "print-a4": ("Impressão A4", "print-a4.css"),
    "ereader": ("E-reader", "ereader.css"),
    "tactics": ("Estudo tático", "tactics.css"),
    "manuscript": ("Manuscrito editorial", "manuscript.css"),
    "contrast": ("Alto contraste", "contrast.css"),
    "magazine": ("Revista enxadrista", "magazine.css"),
    "green-board": ("Tabuleiro verde", "green-board.css"),
    "minimal": ("Minimalista amplo", "minimal.css"),
    "manuscript-flat-comments": ("Manuscrito editorial - comentários limpos", ("manuscript.css", "comments-flat.css")),
    "contrast-flat-comments": ("Alto contraste - comentários limpos", ("contrast.css", "comments-flat.css")),
    "magazine-flat-comments": ("Revista enxadrista - comentários limpos", ("magazine.css", "comments-flat.css")),
    "green-board-flat-comments": ("Tabuleiro verde - comentários limpos", ("green-board.css", "comments-flat.css")),
    "minimal-flat-comments": ("Minimalista amplo - comentários limpos", ("minimal.css", "comments-flat.css")),
    "classic-plain": ("Clássico sem fundo", "comments-plain.css"),
    "modern-plain": ("Moderno limpo sem fundo", ("modern.css", "comments-plain.css")),
    "print-a4-plain": ("Impressão A4 sem fundo", ("print-a4.css", "comments-plain.css")),
    "ereader-plain": ("E-reader sem fundo", ("ereader.css", "comments-plain.css")),
    "tactics-plain": ("Estudo tático sem fundo", ("tactics.css", "comments-plain.css")),
}


CSS = """
.diagram {
    margin: 25px 0 35px;
    text-align: center;
}

.diagram img {
    max-width: 100%;
    border: 1px solid #444;
    box-shadow: 1px 1px 6px rgba(0,0,0,0.25);
    margin-top: 10px;
}

body {
    font-family: "Georgia", "Palatino Linotype", serif;
    max-width: 720px;
    margin: 70px auto;
    padding: 0 30px;
    background: #fbf7ef;
    color: #222;
    line-height: 1.75;
    font-size: 18px;
}

/* Cabeçalho */
.headers {
    margin: 60px 0 30px;
    padding-bottom: 12px;
    border-bottom: 2px solid #444;
    font-variant: small-caps;
    letter-spacing: 0.5px;
    font-size: 1.3em;
}

.headers .info {
    font-size: 0.85em;
    color: #555;
    font-variant: normal;
    margin-top: 5px;
}

/* Mainline */
p.mainline {
    margin: 14px 0;
    text-align: justify;
    font-weight: bold;
}

/* Comentários (parágrafo fora de variantes) */
p.comment {
    margin: 22px 0 22px 20px;
    padding: 12px 18px;
    background: #f3efe3;
    border-left: 4px solid #8c8c8c;
    font-style: italic;
    text-align: justify;
}

/* Comentários inline dentro de variantes */
.cmt {
    font-style: italic;
    color: #555;
}

/* Variantes */
p.variant {
    margin: 18px 0 18px 35px;
    padding: 12px 16px;
    background: #f8f6ee;
    border-left: 4px solid #d4c59a;
    font-style: italic;
    text-align: justify;
}


/* Separador entre partidas */
hr {
    border: none;
    border-top: 2px dotted #aaa;
    margin: 90px 0;
}

/* Rodapé */
footer {
    text-align: center;
    margin: 100px 0 40px;
    font-size: 0.85em;
    color: #777;
    font-style: italic;
}

/* Botões de Análise */
.analysis-links {
    text-align: center;
    margin-top: 10px;
    margin-bottom: 30px;
}

.analysis-links a {
    display: inline-block;
    margin: 0 8px;
    padding: 6px 14px;
    text-decoration: none;
    color: white;
    border-radius: 4px;
    font-size: 14px;
    font-weight: bold;
    font-family: sans-serif;
    box-shadow: 1px 1px 3px rgba(0,0,0,0.3);
}
.analysis-links a:hover {
    filter: brightness(1.1);
    transform: translateY(-1px);
}

.lichess-btn { background-color: #363636; border-bottom: 2px solid #1b1b1b; }
.chesscom-btn { background-color: #7fa650; border-bottom: 2px solid #5d7c38; }

.engine-eval {
    display: inline-block;
    margin-left: 4px;
    padding: 1px 5px;
    border-radius: 6px;
    background: #eef3f8;
    color: #2c3e50;
    border: 1px solid #d5e0ea;
    font-size: 0.78em;
    font-family: Arial, sans-serif;
    vertical-align: baseline;
}

.toc {
    margin: 20px 0 60px;
    padding-bottom: 28px;
    border-bottom: 2px solid #444;
}

.toc h1 {
    font-size: 1.55em;
    font-variant: small-caps;
    margin: 0 0 18px;
}

.toc ol {
    margin: 0;
    padding-left: 24px;
}

.toc li {
    margin: 8px 0;
}

.toc a {
    color: #222;
    text-decoration: none;
    border-bottom: 1px dotted #777;
}

.toc .toc-meta {
    color: #666;
    font-size: 0.9em;
}

.exercise {
    margin: 42px 0;
    padding: 18px 20px;
    background: #fffaf0;
    border: 1px solid #d6b656;
}

.exercise h2 {
    margin: 0 0 14px;
    font-size: 1.2em;
}

.exercise-question {
    font-weight: bold;
}

.exercise-solution {
    margin-top: 12px;
}

"""


def get_css_preset_options():
    return [(label, key) for key, (label, _filename) in STYLE_PRESETS.items()]


@lru_cache(maxsize=None)
def _load_preset_override(preset):
    preset_key = normalize_css_preset(preset)
    filenames = STYLE_PRESETS[preset_key][1]
    if not filenames:
        return ""
    if isinstance(filenames, str):
        filenames = (filenames,)

    css_parts = []
    for filename in filenames:
        style_path = os.path.join(os.path.dirname(__file__), "styles", filename)
        with open(style_path, "r", encoding="utf-8") as file_obj:
            css_parts.append(file_obj.read().strip())
    return "\n\n".join(part for part in css_parts if part)


def normalize_css_preset(preset):
    preset_key = (preset or "classic").strip().lower()
    aliases = {
        "": "classic",
        "classico": "classic",
        "clássico": "classic",
        "classic": "classic",
        "classic-plain": "classic-plain",
        "classico-sem-fundo": "classic-plain",
        "clássico-sem-fundo": "classic-plain",
        "modern": "modern",
        "moderno": "modern",
        "modern-plain": "modern-plain",
        "moderno-sem-fundo": "modern-plain",
        "print": "print-a4",
        "print-a4": "print-a4",
        "a4": "print-a4",
        "print-a4-plain": "print-a4-plain",
        "a4-sem-fundo": "print-a4-plain",
        "ereader": "ereader",
        "e-reader": "ereader",
        "kindle": "ereader",
        "ereader-plain": "ereader-plain",
        "e-reader-sem-fundo": "ereader-plain",
        "tactics": "tactics",
        "tatico": "tactics",
        "tático": "tactics",
        "manuscript": "manuscript",
        "manuscrito": "manuscript",
        "contrast": "contrast",
        "contraste": "contrast",
        "alto-contraste": "contrast",
        "magazine": "magazine",
        "revista": "magazine",
        "green-board": "green-board",
        "verde": "green-board",
        "tabuleiro-verde": "green-board",
        "minimal": "minimal",
        "minimalista": "minimal",
        "manuscript-flat-comments": "manuscript-flat-comments",
        "manuscrito-comentarios-limpos": "manuscript-flat-comments",
        "contrast-flat-comments": "contrast-flat-comments",
        "contraste-comentarios-limpos": "contrast-flat-comments",
        "magazine-flat-comments": "magazine-flat-comments",
        "revista-comentarios-limpos": "magazine-flat-comments",
        "green-board-flat-comments": "green-board-flat-comments",
        "tabuleiro-verde-comentarios-limpos": "green-board-flat-comments",
        "minimal-flat-comments": "minimal-flat-comments",
        "minimalista-comentarios-limpos": "minimal-flat-comments",
        "tactics-plain": "tactics-plain",
        "tatico-sem-fundo": "tactics-plain",
        "tático-sem-fundo": "tactics-plain",
    }
    normalized = aliases.get(preset_key, preset_key)
    if normalized not in STYLE_PRESETS:
        raise ValueError(f"Tema CSS desconhecido: {preset}")
    return normalized


def build_css(
    diagram_style=chess_diagrams.CLASSIC_DIAGRAM_STYLE,
    font_href=None,
    preset="classic",
):
    normalized_style = chess_diagrams.normalize_diagram_style(diagram_style)
    merida_font_href = font_href or chess_diagrams.get_diagram_font_href(normalized_style)
    preset_css = _load_preset_override(preset)
    css_parts = [CSS]
    if preset_css:
        css_parts.append("\n/* Tema */\n" + preset_css + "\n")
    css_parts.append(chess_diagrams.get_additional_css(
        normalized_style,
        font_href=merida_font_href,
    ))
    return "\n".join(part for part in css_parts if part)


def load_css_preset(
    preset,
    diagram_style=chess_diagrams.CLASSIC_DIAGRAM_STYLE,
    font_href=None,
):
    return build_css(diagram_style=diagram_style, font_href=font_href, preset=preset)


def ensure_diagram_font_css(css_text, diagram_style):
    css_text = css_text or ""
    normalized_style = chess_diagrams.normalize_diagram_style(diagram_style)
    if not chess_diagrams.uses_merida_style(normalized_style):
        return css_text

    for spec in chess_diagrams.get_diagram_font_specs():
        font_filename = spec["font_filename"]
        font_href = chess_diagrams.get_diagram_font_href(spec["style"])
        font_format = chess_diagrams.get_support_file_css_format(font_filename)
        css_text = re.sub(
            rf'src\s*:\s*url\((["\']?)[^)"\']*{re.escape(font_filename)}\1\)\s*(?:format\((["\']).*?\2\))?\s*;',
            f'src: url("{font_href}") format("{font_format}");',
            css_text,
            flags=re.IGNORECASE,
        )

    has_font_face = "@font-face" in css_text
    has_merida_rules = ".chess-merida-diagram" in css_text
    if has_font_face and has_merida_rules:
        return css_text

    support_css = chess_diagrams.get_additional_css(
        normalized_style,
        font_href=chess_diagrams.get_diagram_font_href(normalized_style),
    ).strip()
    if not support_css:
        return css_text

    if not css_text.strip():
        return build_css(diagram_style=normalized_style)

    return css_text.rstrip() + "\n\n" + support_css + "\n"


def _escape_html(value):
    return html.escape(value or "", quote=True)


def build_toc_html(summaries):
    summaries = [summary for summary in (summaries or []) if getattr(summary, "anchor", "")]
    if not summaries:
        return ""

    items = []
    for summary in summaries:
        title = _escape_html(summary.title)
        anchor = _escape_html(summary.anchor)
        meta_parts = [
            part
            for part in (
                getattr(summary, "event", ""),
                getattr(summary, "site", ""),
                getattr(summary, "date", ""),
                getattr(summary, "result", ""),
            )
            if part
        ]
        meta_html = (
            f' <span class="toc-meta">{" • ".join(_escape_html(part) for part in meta_parts)}</span>'
            if meta_parts
            else ""
        )
        items.append(f'<li><a href="#{anchor}">{title}</a>{meta_html}</li>')

    return '<nav class="toc"><h1>Sumário</h1><ol>' + "\n".join(items) + "</ol></nav>"


def gerar_html_final(
    blocks,
    css_externo=False,
    diagram_style=chess_diagrams.CLASSIC_DIAGRAM_STYLE,
    font_href=None,
    css_text=None,
    summaries=None,
    css_preset="classic",
):
    css_text = css_text if css_text is not None else build_css(
        diagram_style=diagram_style,
        font_href=font_href,
        preset=css_preset,
    )
    css_text = ensure_diagram_font_css(css_text, diagram_style)
    css_tag = '<link rel="stylesheet" href="style.css">' if css_externo else f"<style>{css_text}</style>"
    toc_html = build_toc_html(summaries)
    content = toc_html + "<hr>".join(blocks)
    rodape = f'<footer>Gerado em {datetime.now().strftime("%d/%m/%Y às %H:%M")}</footer>'
    return f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>Livro de Xadrez</title>{css_tag}</head><body>{content}{rodape}</body></html>'


def write_html_bundle(html_path, conversion_result):
    output_dir = os.path.dirname(html_path)
    font_href = chess_diagrams.get_diagram_font_href(conversion_result.diagram_style)
    if chess_diagrams.uses_merida_style(conversion_result.diagram_style):
        chess_diagrams.copy_support_files(conversion_result.diagram_style, output_dir)

    with open(html_path, "w", encoding="utf-8") as file_obj:
        file_obj.write(
            gerar_html_final(
                conversion_result.blocks,
                css_externo=True,
                diagram_style=conversion_result.diagram_style,
                font_href=font_href,
                summaries=conversion_result.summaries,
            )
        )

    with open(os.path.join(output_dir, "style.css"), "w", encoding="utf-8") as file_obj:
        file_obj.write(
            build_css(
                diagram_style=conversion_result.diagram_style,
                font_href=font_href,
            )
        )
