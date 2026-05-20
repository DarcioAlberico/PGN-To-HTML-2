# -*- coding: utf-8 -*-
import html
import hashlib
import os
import re
import shutil
import sys
from functools import lru_cache
from io import BytesIO

import chess
import chess.svg

try:
    import cairosvg
except ImportError:
    cairosvg = None

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

try:
    from fontTools.ttLib import TTFont
    from fontTools.pens.qtPen import QtPen
except ImportError:
    TTFont = None
    QtPen = None

try:
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QTransform
except ImportError:
    QByteArray = None
    QBuffer = None
    QIODevice = None
    QColor = None
    QImage = None
    QPainter = None
    QPainterPath = None
    QTransform = None


CLASSIC_DIAGRAM_STYLE = "classic"
MERIDA_DIAGRAM_STYLE = "merida"
MERIDA_FONT_FILENAME = "ChessMerida.ttf"
MERIDA_FONT_FAMILY = "Chess Merida"
FONT_DIAGRAM_STYLE_PREFIX = "font:"
FONT_OUTPUT_DIRNAME = "Fonts"
EMBEDDED_FONT_FAMILY_PREFIX = "PGNToHTMLDiagramFont"
SEARCHABLE_FONT_EXTENSIONS = {".ttf", ".otf"}
VALID_PIECES = set("prnbqkPRNBQK")
MERIDA_COMPATIBLE_ENCODINGS = {"merida", "leipzig", "adventurer"}

MERIDA_PIECES = {
    "K": ("K", "k"),
    "Q": ("Q", "q"),
    "R": ("R", "r"),
    "B": ("B", "b"),
    "N": ("N", "n"),
    "P": ("P", "p"),
    "k": ("L", "l"),
    "q": ("W", "w"),
    "r": ("T", "t"),
    "b": ("V", "v"),
    "n": ("M", "m"),
    "p": ("O", "o"),
}

MERIDA_BORDER = {
    "top_left": "!",
    "top_right": "#",
    "bottom_left": "/",
    "bottom_right": ")",
    "left": "$",
    "right": "%",
    "top": '"',
    "bottom": "(",
}

MERIDA_REQUIRED_FONT_CHARS = {
    char
    for piece_chars in MERIDA_PIECES.values()
    for char in piece_chars
}
MERIDA_REQUIRED_FONT_CHARS.update(MERIDA_BORDER.values())


def _normalize_name(value):
    return "".join(char.lower() for char in value if char.isalnum())


def _style_from_font_filename(filename):
    return f"{FONT_DIAGRAM_STYLE_PREFIX}{os.path.basename(filename).lower()}"


def _embedded_font_family(filename):
    normalized = _normalize_name(os.path.splitext(os.path.basename(filename))[0]) or "default"
    return f"{EMBEDDED_FONT_FAMILY_PREFIX}-{normalized}"


def _read_font_names(font_path):
    family_name = os.path.splitext(os.path.basename(font_path))[0]
    display_name = family_name

    if TTFont is None:
        return family_name, display_name

    try:
        font = TTFont(font_path)
    except Exception:
        return family_name, display_name

    for record in font["name"].names:
        try:
            value = record.toUnicode().strip()
        except Exception:
            continue
        if not value:
            continue
        if record.nameID == 1 and family_name == os.path.splitext(os.path.basename(font_path))[0]:
            family_name = value
        if record.nameID == 4 and display_name == family_name:
            display_name = value

    return family_name, display_name


def _display_name_from_path(font_path):
    stem = os.path.splitext(os.path.basename(font_path))[0]
    if stem.lower().startswith("chess") and len(stem) > 5:
        suffix = stem[5:]
        if suffix:
            return f"Chess{suffix}"
    return stem


def _font_has_required_chars(font_path, required_chars):
    if TTFont is None:
        return True

    try:
        font = TTFont(font_path)
    except Exception:
        return False

    available_chars = set()
    for table in font["cmap"].tables:
        for codepoint in table.cmap.keys():
            if 0 <= codepoint <= 0x10FFFF:
                available_chars.add(chr(codepoint))
    return required_chars.issubset(available_chars)


def _detect_font_encoding(font_path):
    basename = os.path.basename(font_path)
    family_name, display_name = _read_font_names(font_path)
    name_blob = _normalize_name(" ".join([basename, family_name, display_name]))

    if not _font_has_required_chars(font_path, MERIDA_REQUIRED_FONT_CHARS):
        return None

    # Chess Leipzig and Chess Adventurer follow the same board/piece encoding
    # family used by Chess Merida for orthodox diagrams.
    if "leipzig" in name_blob:
        return "leipzig"
    if "adventurer" in name_blob:
        return "adventurer"
    if "merida" in name_blob or "kingdom" in name_blob:
        return "merida"

    if "chess" in name_blob:
        return "merida"

    return None


def _iter_font_search_dirs():
    module_dir = os.path.abspath(os.path.dirname(__file__))
    project_dir = os.path.abspath(os.path.join(module_dir, ".."))
    candidate_dirs = [
        os.path.join(module_dir, FONT_OUTPUT_DIRNAME),
        os.path.join(project_dir, FONT_OUTPUT_DIRNAME),
        module_dir,
        project_dir,
        os.path.join(project_dir, "ChessMeridaOCR"),
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        meipass = os.path.abspath(meipass)
        candidate_dirs.extend(
            [
                os.path.join(meipass, FONT_OUTPUT_DIRNAME),
                os.path.join(meipass, "PGN_To_HTML_2", FONT_OUTPUT_DIRNAME),
                meipass,
                os.path.join(meipass, "PGN_To_HTML_2"),
            ]
        )

    seen = set()
    for path in candidate_dirs:
        resolved = os.path.abspath(path)
        if resolved in seen or not os.path.isdir(resolved):
            continue
        seen.add(resolved)
        yield resolved


def _font_sort_key(spec):
    filename = spec["font_filename"].lower()
    display_name = spec["display_name"].lower()
    is_default_merida = filename == MERIDA_FONT_FILENAME.lower()
    return (0 if is_default_merida else 1, display_name, filename)


@lru_cache(maxsize=1)
def get_diagram_font_specs():
    raw_specs = []
    seen_styles = set()

    for directory in _iter_font_search_dirs():
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name.lower())
        except OSError:
            continue

        for entry in entries:
            if not entry.is_file():
                continue
            extension = os.path.splitext(entry.name)[1].lower()
            if extension not in SEARCHABLE_FONT_EXTENSIONS:
                continue

            font_path = os.path.abspath(entry.path)
            encoding = _detect_font_encoding(font_path)
            if not encoding:
                continue

            style = _style_from_font_filename(entry.name)
            if style in seen_styles:
                continue

            family_name, display_name = _read_font_names(font_path)
            raw_specs.append(
                {
                    "style": style,
                    "font_path": font_path,
                    "font_filename": os.path.basename(font_path),
                    "font_family": family_name or display_name,
                    "css_font_family": _embedded_font_family(font_path),
                    "display_name": _display_name_from_path(font_path),
                    "encoding": encoding,
                }
            )
            seen_styles.add(style)

    for spec in raw_specs:
        spec["option_label"] = spec["display_name"]

    raw_specs.sort(key=_font_sort_key)
    return tuple(raw_specs)


def get_diagram_style_options():
    options = [("PNG/SVG padrao", CLASSIC_DIAGRAM_STYLE)]
    options.extend(
        (spec["option_label"], spec["style"])
        for spec in get_diagram_font_specs()
    )
    return options


def get_diagram_font_spec(style):
    normalized_style = normalize_diagram_style(style)
    if normalized_style == CLASSIC_DIAGRAM_STYLE:
        return None
    for spec in get_diagram_font_specs():
        if spec["style"] == normalized_style:
            return spec
    raise RuntimeError(f"Nenhuma fonte compatível foi encontrada para o estilo '{style}'.")


def get_diagram_font_filename(style):
    spec = get_diagram_font_spec(style)
    return spec["font_filename"] if spec else None


def get_diagram_font_href(style, font_dir=FONT_OUTPUT_DIRNAME):
    file_name = get_diagram_font_filename(style)
    if not file_name:
        return None
    return "/".join(part.strip("/\\") for part in (font_dir, file_name) if part)


def get_support_file_media_type(file_name):
    extension = os.path.splitext(file_name)[1].lower()
    if extension == ".otf":
        return "font/otf"
    return "font/ttf"


def get_support_file_css_format(file_name):
    extension = os.path.splitext(file_name)[1].lower()
    if extension == ".otf":
        return "opentype"
    return "truetype"


def _get_default_font_style():
    specs = get_diagram_font_specs()
    for spec in specs:
        if spec["font_filename"].lower() == MERIDA_FONT_FILENAME.lower():
            return spec["style"]
    return specs[0]["style"] if specs else None


def normalize_diagram_style(style):
    normalized_input = (style or "").strip().lower()
    aliases = {
        "": CLASSIC_DIAGRAM_STYLE,
        CLASSIC_DIAGRAM_STYLE: CLASSIC_DIAGRAM_STYLE,
        "svg": CLASSIC_DIAGRAM_STYLE,
        "image": CLASSIC_DIAGRAM_STYLE,
        "images": CLASSIC_DIAGRAM_STYLE,
        MERIDA_DIAGRAM_STYLE: _get_default_font_style(),
        "chessmerida": _get_default_font_style(),
        "chess_merida": _get_default_font_style(),
        "chess-merida": _get_default_font_style(),
    }

    if style is None:
        return CLASSIC_DIAGRAM_STYLE

    if normalized_input in aliases and aliases[normalized_input]:
        return aliases[normalized_input]

    for spec in get_diagram_font_specs():
        if spec["style"] == normalized_input:
            return spec["style"]

    raise ValueError(f"Estilo de diagrama desconhecido: {style}")


def uses_merida_style(style):
    return normalize_diagram_style(style) != CLASSIC_DIAGRAM_STYLE


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def diagram_cache_key(fen, style=CLASSIC_DIAGRAM_STYLE, size=360):
    normalized_style = normalize_diagram_style(style)
    payload = f"{fen}|{normalized_style}|{int(size)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def generate_svg(fen, svg_path, size=360):
    board = chess.Board(fen)
    svg_code = chess.svg.board(board, size=size)
    with open(svg_path, "w", encoding="utf-8") as file_obj:
        file_obj.write(svg_code)
    return svg_code


def generate_png(svg_code, png_path, size=360):
    if cairosvg is not None:
        cairosvg.svg2png(
            bytestring=svg_code.encode("utf-8"),
            write_to=png_path,
            output_width=size,
            output_height=size,
        )
        return

    if Image is None:
        raise RuntimeError(
            "Nao foi possivel gerar PNG: instale 'cairosvg' ou 'Pillow'."
        )

    try:
        image = Image.open(BytesIO(svg_code.encode("utf-8")))
        image.save(png_path)
    except Exception as exc:
        raise RuntimeError(
            "Nao foi possivel converter SVG para PNG sem 'cairosvg'."
        ) from exc


def generate_complete_diagram(
    fen,
    output_dir="Diagrams",
    base_name="diagram",
    idx=1,
    size=360,
    cache_key=None,
):
    ensure_dir(output_dir)

    if cache_key:
        file_stem = f"diagram_{cache_key}"
    else:
        file_stem = f"{base_name}_{idx}"

    svg_path = os.path.join(output_dir, f"{file_stem}.svg")
    png_path = os.path.join(output_dir, f"{file_stem}.png")

    if os.path.exists(svg_path):
        with open(svg_path, "r", encoding="utf-8") as file_obj:
            svg_code = file_obj.read()
    else:
        svg_code = generate_svg(fen, svg_path, size=size)

    if not os.path.exists(png_path):
        generate_png(svg_code, png_path, size=size)

    return svg_path, png_path


def clear_diagram_cache(output_dir="Diagrams"):
    if not os.path.isdir(output_dir):
        return 0

    removed = 0
    for entry in os.scandir(output_dir):
        if not entry.is_file():
            continue
        name = entry.name.lower()
        if not re.fullmatch(r"diagram_[0-9a-f]{12}\.(svg|png)", name):
            continue
        os.remove(entry.path)
        removed += 1
    return removed


def get_merida_font_source_path():
    default_style = _get_default_font_style()
    if not default_style:
        return None
    return get_diagram_font_spec(default_style)["font_path"]


def require_merida_font_source_path():
    font_path = get_merida_font_source_path()
    if font_path is None:
        raise RuntimeError(
            "A fonte ChessMerida.ttf nao foi encontrada. Coloque-a em "
            f"'{FONT_OUTPUT_DIRNAME}/ChessMerida.ttf' ou em 'ChessMeridaOCR/ChessMerida.ttf'."
        )
    return font_path


def copy_support_files(style, output_dir, font_filename=None, target_subdir=FONT_OUTPUT_DIRNAME):
    normalized_style = normalize_diagram_style(style)
    copied_files = []

    if normalized_style != CLASSIC_DIAGRAM_STYLE:
        target_dir = os.path.join(output_dir, target_subdir)
        ensure_dir(target_dir)
        spec = get_diagram_font_spec(normalized_style)
        source_path = spec["font_path"]
        target_name = font_filename or spec["font_filename"]
        target_path = os.path.join(target_dir, target_name)
        shutil.copyfile(source_path, target_path)
        copied_files.append(target_path)

    return copied_files


def get_support_file_bytes(style):
    normalized_style = normalize_diagram_style(style)
    files = {}

    if normalized_style != CLASSIC_DIAGRAM_STYLE:
        spec = get_diagram_font_spec(normalized_style)
        font_path = spec["font_path"]
        with open(font_path, "rb") as file_obj:
            files[spec["font_filename"]] = file_obj.read()

    return files


def get_additional_css(style, font_href=None):
    normalized_style = normalize_diagram_style(style)
    if normalized_style == CLASSIC_DIAGRAM_STYLE:
        return ""

    spec = get_diagram_font_spec(normalized_style)
    escaped_href = html.escape(font_href or spec["font_filename"], quote=True)
    font_family = html.escape(spec["css_font_family"], quote=True)
    font_format = get_support_file_css_format(spec["font_filename"])
    return f"""
@font-face {{
    font-family: "{font_family}";
    src: url("{escaped_href}") format("{font_format}");
    font-style: normal;
    font-weight: normal;
    font-display: block;
}}

.diagram--merida {{
    max-width: 100%;
}}

.diagram--merida .chess-merida-diagram {{
    display: inline-block;
    max-width: 100%;
    box-sizing: border-box;
    margin: 0;
    padding: 0.18em 0.22em;
    font-family: "{font_family}", monospace;
    font-size: 2.25em;
    line-height: 1em;
    letter-spacing: 0;
    white-space: pre;
    background: #fff;
    border: 1px solid #444;
    box-shadow: 1px 1px 6px rgba(0,0,0,0.18);
}}
"""


def parse_fen_board(fen):
    board_part = fen.strip().split()[0]
    rows = board_part.split("/")
    if len(rows) != 8:
        raise ValueError("FEN invalido: o tabuleiro deve ter 8 ranks.")

    parsed_rows = []
    for row in rows:
        expanded = []
        for char in row:
            if char.isdigit():
                expanded.extend([""] * int(char))
            elif char in VALID_PIECES:
                expanded.append(char)
            else:
                raise ValueError(f"FEN invalido: peca inesperada '{char}'.")
        if len(expanded) != 8:
            raise ValueError("FEN invalido: rank com largura diferente de 8.")
        parsed_rows.append(expanded)
    return parsed_rows


def merida_square_char(piece, is_dark_square):
    if not piece:
        return "+" if is_dark_square else " "
    dark_char, light_char = MERIDA_PIECES[piece]
    return dark_char if is_dark_square else light_char


def build_merida_board_chars(board_rows):
    rows = []
    rows.append(
        MERIDA_BORDER["top_left"]
        + (MERIDA_BORDER["top"] * 8)
        + MERIDA_BORDER["top_right"]
    )

    for row_index, row in enumerate(board_rows):
        line = [MERIDA_BORDER["left"]]
        for col_index, piece in enumerate(row):
            is_dark_square = (row_index + col_index) % 2 == 1
            line.append(merida_square_char(piece, is_dark_square))
        line.append(MERIDA_BORDER["right"])
        rows.append("".join(line))

    rows.append(
        MERIDA_BORDER["bottom_left"]
        + (MERIDA_BORDER["bottom"] * 8)
        + MERIDA_BORDER["bottom_right"]
    )
    return rows


def build_merida_diagram_text(fen):
    return "\n".join(build_merida_board_chars(parse_fen_board(fen)))


def build_font_diagram_text(fen, style):
    spec = get_diagram_font_spec(style)
    if spec["encoding"] in MERIDA_COMPATIBLE_ENCODINGS:
        return build_merida_diagram_text(fen)
    return build_merida_diagram_text(fen)


def load_merida_font_data(font_path):
    if TTFont is None or QtPen is None or QPainterPath is None:
        return None, None

    tt_font = TTFont(font_path)
    glyphset = tt_font.getGlyphSet()
    mac_cmap = {}
    for table in tt_font["cmap"].tables:
        if table.platformID == 1:
            mac_cmap.update(table.cmap)
    return glyphset, mac_cmap


def render_merida_glyph(painter, glyphset, mac_cmap, merida_char, x, y, square):
    glyph_name = mac_cmap.get(ord(merida_char))
    if not glyph_name:
        return

    path = QPainterPath()
    pen = QtPen(glyphset, path)
    glyphset[glyph_name].draw(pen)

    bounds = path.boundingRect()
    if bounds.isEmpty():
        return

    scale = square / max(bounds.width(), bounds.height())
    transform = QTransform()
    transform.translate(x, y + square)
    transform.scale(scale, -scale)
    transform.translate(-bounds.x(), -bounds.y())
    painter.drawPath(transform.map(path))


def render_merida_diagram_png_qt(
    diagram_text,
    png_path,
    font_path=None,
    square=62,
    margin=10,
):
    if None in (TTFont, QtPen, QByteArray, QBuffer, QIODevice, QColor, QImage, QPainter, QPainterPath, QTransform):
        raise RuntimeError("Dependencias Qt/fontTools indisponiveis para renderizar com Merida.")

    font_path = font_path or require_merida_font_source_path()
    glyphset, mac_cmap = load_merida_font_data(font_path)
    if glyphset is None or not mac_cmap:
        raise RuntimeError("Nao foi possivel carregar os glyphs da Chess Merida.")

    rows = [row for row in diagram_text.splitlines() if row]
    if not rows:
        raise RuntimeError("Diagrama Merida vazio.")

    cols = max(len(row) for row in rows)
    image_width = cols * square + margin * 2
    image_height = len(rows) * square + margin * 2

    image = QImage(image_width, image_height, QImage.Format_ARGB32)
    image.fill(QColor(255, 255, 255))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(0, 0, 0))
    painter.setPen(QColor(0, 0, 0))

    for row_index, row_text in enumerate(rows):
        padded_row = row_text.ljust(cols)
        for col_index, merida_char in enumerate(padded_row):
            x = margin + col_index * square
            y = margin + row_index * square
            render_merida_glyph(painter, glyphset, mac_cmap, merida_char, x, y, square)
    painter.end()

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    with open(png_path, "wb") as file_obj:
        file_obj.write(bytes(data))
    return png_path


def render_merida_diagram_png(
    diagram_text,
    png_path,
    font_path=None,
    font_size=64,
    padding=18,
):
    font_path = font_path or require_merida_font_source_path()

    try:
        return render_merida_diagram_png_qt(
            diagram_text,
            png_path,
            font_path=font_path,
        )
    except Exception:
        pass

    if Image is None or ImageDraw is None or ImageFont is None:
        raise RuntimeError("Nao foi possivel renderizar Chess Merida em PNG.")

    font = ImageFont.truetype(font_path, size=font_size)

    scratch = Image.new("RGB", (32, 32), (255, 255, 255))
    scratch_draw = ImageDraw.Draw(scratch)
    bbox = scratch_draw.multiline_textbbox(
        (0, 0),
        diagram_text,
        font=font,
        spacing=0,
    )
    width = max(1, bbox[2] - bbox[0] + padding * 2)
    height = max(1, bbox[3] - bbox[1] + padding * 2)

    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.multiline_text(
        (padding - bbox[0], padding - bbox[1]),
        diagram_text,
        font=font,
        fill=(0, 0, 0),
        spacing=0,
    )
    image.save(png_path, format="PNG")
    return png_path


def render_diagram_html(
    fen,
    output_dir="Diagrams",
    base_name="diagram",
    idx=1,
    size=360,
    style=CLASSIC_DIAGRAM_STYLE,
    web_root=".",
    use_cache=True,
):
    normalized_style = normalize_diagram_style(style)

    if normalized_style == CLASSIC_DIAGRAM_STYLE:
        cache_key = diagram_cache_key(fen, normalized_style, size) if use_cache else None
        svg_path, png_path = generate_complete_diagram(
            fen,
            output_dir=output_dir,
            base_name=base_name,
            idx=idx,
            size=size,
            cache_key=cache_key,
        )
        rel_path = os.path.relpath(svg_path, web_root).replace("\\", "/")
        return {
            "style": normalized_style,
            "html": (
                f'<div class="diagram"><img src="{html.escape(rel_path, quote=True)}" '
                'alt="Diagrama"></div>'
            ),
            "asset": {
                "fen": fen,
                "svg_path": svg_path,
                "png_path": png_path,
                "web_path": rel_path,
            },
        }

    spec = get_diagram_font_spec(normalized_style)
    font_family = html.escape(spec["css_font_family"], quote=True)
    font_file = html.escape(spec["font_filename"], quote=True)
    diagram_text = html.escape(build_font_diagram_text(fen, normalized_style), quote=False)
    return {
        "style": normalized_style,
        "html": (
            '<div class="diagram diagram--merida">'
            f'<pre class="chess-merida-diagram" aria-label="Diagrama de xadrez" '
            f'style="font-family: &quot;{font_family}&quot;, monospace;" '
            f'data-font-family="{font_family}" data-font-file="{font_file}">{diagram_text}</pre>'
            "</div>"
        ),
        "asset": None,
    }
