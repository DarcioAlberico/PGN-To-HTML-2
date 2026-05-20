# -*- coding: utf-8 -*-
"""Versao legada Tkinter mantida apenas para referencia historica.

O aplicativo ativo usa PGN_To_HTML_2/PGN_para_Livro_PERFEITO8.py como ponto
de entrada e PGN_To_HTML_2/pgn_qt_window.py para a interface Qt.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import re
import os
import threading
import webbrowser
import tempfile
from datetime import datetime

import chess_diagrams

# ==================== EPUB (opcional) ====================
try:
    from ebooklib import epub

    HAS_EPUB = True
except ImportError:
    HAS_EPUB = False

# ====================== CSS ESTILO CLÁSSICO ======================
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
    font-style: normal;
    text-align: justify;
}

/* Comentários inline dentro de variantes */
.cmt {
    font-style: italic;
    color: #555;
}

/* Variantes */
.variant {
    margin: 18px 0 18px 35px;
    padding: 12px 16px;
    background: #f8f6ee;
    border-left: 4px solid #d4c59a;
    font-style: normal;
    text-align: justify;
}

/* Sub-variantes (aninhadas) */
.subvariant {
    margin-top: 8px;
    margin-bottom: 8px;
    margin-left: 20px;
    padding-left: 12px;
    border-left: 2px solid #c0b283;
    background: rgba(0,0,0,0.02); /* leve destaque */
    display: block;
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
"""


# ====================== FUNÇÕES AUXILIARES ======================

def _clean_engine_tags(s):
    return re.sub(r'\[\%[^\]]*\]', '', s)


def _escape_html(s):
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    return s


def clean_comment_start(txt):
    return re.sub(r'^[\s,;:\.\-–—]+', '', txt).strip()


# ====================== NAG → Unicode ======================

NAG_MAP = {
    "$1": "!", "$2": "?", "$3": "!!", "$4": "??", "$5": "!?", "$6": "?!",
    "$7": "□", "$10": "=", "$11": "=", "$13": "∞", "$14": "⩲−",
    "$15": "⩱", "$16": "±", "$17": "∓", "$18": "+-", "$19": "-+",
    "$22": "⨀", "$23": "○", "$32": "⟳", "$33": "⟳", "$36": "↑",
    "$37": "↑", "$40": "→", "$41": "→", "$44": "⯹", "$45": "⯹",
    "$132": "⇆", "$133": "⇆", "$138": "⨁", "$139": "⨁",
    "$140": "∆", "$141": "∇", "$142": "⌓", "$144": "==",
    "$145": "==", "$146": "N",
}


def replace_nags(text):
    for nag in sorted(NAG_MAP.keys(), key=len, reverse=True):
        text = re.sub(re.escape(nag) + r"(?!\d)", NAG_MAP[nag], text)
    return text


# ====================== CONVERSOR DE LANCES PARA UNICODE ======================
PIECE_TO_UNICODE = {
    "K": "\u2654", "Q": "\u2655", "R": "\u2656", "B": "\u2657", "N": "\u2658",
}

_pat_piece_move = re.compile(r"([KQRBN])([x]?[1-8]?[a-h]?[x]?[a-h]?[a-h][1-8])")
_pat_promo = re.compile(r"([a-h][1-8]=)([QRBN])")
_pat_capture_promo = re.compile(r"([a-h]x[a-h][1-8]=)([QRBN])")


def to_unicode_moves(text):
    def _piece_repl(m):
        return PIECE_TO_UNICODE.get(m.group(1), m.group(1)) + m.group(2)

    def _promo_repl(m):
        return m.group(1) + PIECE_TO_UNICODE.get(m.group(2), m.group(2))

    text = _pat_piece_move.sub(_piece_repl, text)
    text = _pat_capture_promo.sub(_promo_repl, text)
    text = _pat_promo.sub(_promo_repl, text)
    return text


# ====================== VARIANT + COMMENT INLINE RENDERER ======================
def render_variant_text(s, comments):
    if not s: return ""

    s = replace_nags(s)
    var_map = {}
    cmt_map = {}

    def _var_ph(i):
        return f"__VPL_{i}__"

    def _cmt_ph(i):
        return f"__CPL_{i}__"

    var_counter = 0
    pattern_var = re.compile(r'\(([^()]+)\)')

    while True:
        m = pattern_var.search(s)
        if not m: break
        inner = m.group(1)
        processed_inner = render_variant_text(inner, comments)
        ph = _var_ph(var_counter)
        var_map[ph] = f'<div class="subvariant">({processed_inner})</div>'
        s = s[:m.start()] + ph + s[m.end():]
        var_counter += 1

    cmt_counter = 0

    def _cmt_repl(m):
        nonlocal cmt_counter
        txt = m.group(1).strip()
        txt = clean_comment_start(txt)
        esc = _escape_html(txt)
        html = f'<span class="cmt">{esc}</span>'
        ph = _cmt_ph(cmt_counter)
        cmt_map[ph] = html
        cmt_counter += 1
        return ph

    s = re.sub(r'\{(.*?)\}', _cmt_repl, s, flags=re.S)
    escaped = _escape_html(s)

    for ph, html in cmt_map.items():
        escaped = escaped.replace(_escape_html(ph), html)
    for ph, html in reversed(list(var_map.items())):
        escaped = escaped.replace(_escape_html(ph), html)

    def _main_comment_replacer(match):
        idx = int(match.group(1))
        if 0 <= idx < len(comments):
            raw_comment = comments[idx]
            raw_comment = clean_comment_start(raw_comment)
            esc = _escape_html(raw_comment)
            return f'<span class="cmt">{esc}</span>'
        return ""

    escaped = re.sub(r'__COMMENT_(\d+)__', _main_comment_replacer, escaped)
    escaped = re.sub(r'\s+', ' ', escaped).strip()
    return escaped


# ====================== EXTRATOR DE VARIANTES TOPOLOGICAS ======================
def extract_top_level_variants(text):
    out = []
    variants = []
    depth = 0
    current = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            if depth == 0:
                if current:
                    out.append("".join(current))
                    current = []
                depth = 1
                i += 1
                continue
            else:
                depth += 1
        elif ch == ")":
            if depth > 0:
                depth -= 1
                if depth == 0:
                    v = "".join(current).strip()
                    variants.append(v)
                    placeholder = f" __VAR_{len(variants) - 1}__ "
                    out.append(placeholder)
                    current = []
                    i += 1
                    continue
        if depth > 0:
            current.append(ch)
        else:
            out.append(ch)
        i += 1

    if current and depth == 0:
        out.append("".join(current))
    return ("".join(out), variants)


# ====================== PARSE PGN COMPLETO ======================
def parse_pgn(text, diagram_dir="Images", diagram_web_path=None, use_unicode_moves=False):
    if diagram_web_path is None:
        diagram_web_path = diagram_dir

    diagram_web_path = diagram_web_path.replace("\\", "/")

    # CORREÇÃO: Limpar BOM e espaços
    text = text.strip().lstrip('\ufeff')

    games = re.split(r"(?=\[Event\s)", text)
    blocks = []
    diagram_files = []

    for idx, game in enumerate(games, 1):
        if not game.strip():
            continue

        tags = dict(re.findall(r'\[(\w+)\s+"([^"]*)"\]', game))
        white = tags.get("White", "Brancas")
        black = tags.get("Black", "Pretas")
        event = tags.get("Event", "")
        site = tags.get("Site", "")
        date = tags.get("Date", "????").split(".")[0]
        eco = tags.get("ECO", "")

        header = (
                f'<div class="headers"><div>({idx}) {_escape_html(white)} – {_escape_html(black)}'
                + (f' [{_escape_html(eco)}]' if eco else "")
                + "</div>"
                + f'<div class="info">{_escape_html(event)} • {_escape_html(site)} • {_escape_html(date)}</div></div>'
        )

        fen = tags.get("FEN")
        setup = tags.get("SetUp", "0")
        diagram_html = ""

        if fen and setup == "1":
            try:
                svg_path, png_path = chess_diagrams.generate_complete_diagram(
                    fen,
                    output_dir=diagram_dir,
                    base_name=f"diagram_partida_{idx}",
                    idx=1,
                    size=360,
                )
                png_web = os.path.join(diagram_web_path, os.path.basename(png_path)).replace("\\", "/")
                diagram_files.append({"fen": fen, "png_path": png_path, "web_path": png_web})

                # CORREÇÃO: Texto 'posição' arrumado
                diagram_html = f'''
                    <div class="diagram">
                        <img src="{png_web}" alt="Diagrama da posição">
                    </div>
                '''
            except Exception as e:
                print(f"Erro ao gerar diagrama partida {idx}: {e}")

        body = game
        body = re.sub(r'\[.*?\]\s*', '', body, flags=re.S)
        body = _clean_engine_tags(body)
        body = re.sub(r'\s+', ' ', body).strip()
        body = replace_nags(body)

        if use_unicode_moves:
            body = to_unicode_moves(body)

        comments = []

        def _comment_repl(m):
            comments.append(m.group(1).strip())
            return f" __COMMENT_{len(comments) - 1}__ "

        body = re.sub(r'\{(.*?)\}', _comment_repl, body, flags=re.S)
        body, variants = extract_top_level_variants(body)
        body = re.sub(r'(1-0|0-1|1/2-1/2|\*)$', '', body).strip()
        body = re.sub(r'(__COMMENT_\d+__|__VAR_\d+__)', r' \1 ', body)
        tokens = re.split(r'(__COMMENT_\d+__|__VAR_\d+__)', body)

        html_parts = []
        for tok in tokens:
            tok = tok.strip()
            if not tok: continue

            if tok.startswith("__COMMENT_"):
                i = int(re.search(r'__COMMENT_(\d+)__', tok).group(1))
                if i < len(comments):
                    clean = clean_comment_start(comments[i])
                    esc = _escape_html(clean)
                    html_parts.append(f'<p class="comment">{esc}</p>')
                continue

            if tok.startswith("__VAR_"):
                i = int(re.search(r'__VAR_(\d+)__', tok).group(1))
                if i < len(variants):
                    raw_inner = variants[i]
                    processed = render_variant_text(raw_inner, comments)
                    html_parts.append(f'<div class="variant">({processed})</div>')
                continue

            parts = re.split(r'(?=(\b\d+\.(?:\.\.)?))', tok)
            parts = [p.strip() for p in parts if p.strip()]

            for p in parts:
                pp = p.strip()
                if re.fullmatch(r'\d+\.(\s*…|\.{2,})?', pp): continue
                pp = re.sub(r'\b(\d+)\.\.\.', lambda m: f"{m.group(1)}. …", pp)
                esc = _escape_html(pp)
                html_parts.append(f'<p class="mainline">{esc}</p>')

        blocks.append(header + diagram_html + "\n" + "\n".join(html_parts))

    return blocks, diagram_files


# ====================== GERADOR HTML ======================

def gerar_html(blocks, css_externo=False):
    css_tag = '<link rel="stylesheet" href="style.css">' if css_externo else f"<style>{CSS}</style>"
    content = "<hr>".join(blocks)
    rodape = f'<footer>Gerado em {datetime.now().strftime("%d/%m/%Y às %H:%M")}</footer>'
    return f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>Livro de Xadrez</title>{css_tag}</head><body>{content}{rodape}</body></html>'


# ====================== APLICATIVO TKINTER ======================

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("PGN → Livro de Xadrez (Versão Clássica)")
        self.root.geometry("1450x920")
        self.root.configure(bg="#f4f4f4")
        self.blocks = None
        self.diagram_images = []
        self.var_unicode_moves = tk.BooleanVar(value=False)

        top = tk.Frame(self.root, bg="#2c3e50", pady=20)
        top.pack(fill="x")

        btn_bar = tk.Frame(top, bg="#2c3e50")
        btn_bar.pack(fill="x")

        btns = [
            ("Abrir PGN", self.abrir, "#3498db"),
            ("Processar PGN", self.processar, "#27ae60"),
            ("Ver no Navegador", self.preview, "#e67e22"),
            ("SALVAR HTML + CSS", self.salvar_html, "#9b59b6"),
        ]
        if HAS_EPUB:
            btns.append(("Salvar EPUB", self.salvar_epub, "#1abc9c"))

        for texto, func, cor in btns:
            tk.Button(btn_bar, text=texto, command=func, bg=cor, fg="white",
                      font=("Arial", 12, "bold"), width=18, height=2).pack(side="left", padx=12)

        options_bar = tk.Frame(top, bg="#2c3e50")
        options_bar.pack(fill="x", pady=(8, 0))
        tk.Checkbutton(options_bar, text="Usar pecas unicode (\u2654\u2655\u2656\u2657\u2658)",
                       variable=self.var_unicode_moves, bg="#2c3e50", fg="white",
                       selectcolor="#2c3e50", activebackground="#2c3e50",
                       activeforeground="white").pack(side="left", padx=12)

        pan = tk.PanedWindow(self.root, orient="horizontal", sashwidth=6)
        pan.pack(fill="both", expand=True, padx=15, pady=15)

        left = tk.Frame(pan, bg="white")
        tk.Label(left, text="Cole ou abra o PGN aqui", font=("Arial", 12, "bold"), bg="white").pack(anchor="w", pady=5)
        self.txt_pgn = scrolledtext.ScrolledText(left, font=("Consolas", 11))
        self.txt_pgn.pack(fill="both", expand=True)
        pan.add(left)

        right = tk.Frame(pan, bg="white")
        tk.Label(right, text="HTML gerado (pronto para salvar)", font=("Arial", 12, "bold"), bg="white").pack(
            anchor="w", pady=5)
        self.txt_html = scrolledtext.ScrolledText(right, font=("Georgia", 12))
        self.txt_html.pack(fill="both", expand=True)
        pan.add(right)

    def abrir(self):
        arq = filedialog.askopenfilename(filetypes=[("PGN", "*.pgn")])
        if arq:
            self.txt_pgn.delete("1.0", "end")
            with open(arq, "r", encoding="utf-8", errors="ignore") as f:
                self.txt_pgn.insert("1.0", f.read())

    def processar(self):
        def run():
            texto = self.txt_pgn.get("1.0", "end").strip()
            if not texto:
                self.root.after(0, lambda: messagebox.showwarning("Aviso", "Cole ou abra um arquivo PGN primeiro!"))
                return

            try:
                # Chama o parser
                blocks, diagram_images = parse_pgn(texto, use_unicode_moves=self.var_unicode_moves.get())

                # Gera HTML
                html = gerar_html(blocks)

                # Atualiza GUI na thread principal
                def update_ui():
                    self.blocks, self.diagram_images = blocks, diagram_images
                    self.txt_html.delete("1.0", "end")
                    self.txt_html.insert("1.0", html)
                    messagebox.showinfo("PRONTO!", f"{len(blocks)} partidas convertidas!")

                self.root.after(0, update_ui)

            except Exception as e:
                # Reporta erro na thread principal
                print(f"Erro detalhado: {e}")
                self.root.after(0, lambda: messagebox.showerror("Erro", f"Falha ao processar PGN:\n{e}"))

        threading.Thread(target=run, daemon=True).start()

    def preview(self):
        if not self.blocks:
            messagebox.showinfo("Info", "Processe o PGN primeiro.")
            return

        try:
            with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
                f.write(gerar_html(self.blocks))
                webbrowser.open("file://" + f.name)
        except Exception as e:
            messagebox.showerror("Erro no Preview", str(e))

    def salvar_html(self):
        if not self.blocks:
            messagebox.showinfo("Info", "Processe o PGN primeiro.")
            return

        arq = filedialog.asksaveasfilename(defaultextension=".html", filetypes=[("HTML", "*.html")])
        if not arq:
            return

        try:
            pasta = os.path.dirname(arq)
            texto = self.txt_pgn.get("1.0", "end").strip()

            # Recalcula para garantir caminhos de imagem relativos corretos
            blocks, diagram_images = parse_pgn(
                texto,
                diagram_dir=os.path.join(pasta, "Images"),
                diagram_web_path="Images",
                use_unicode_moves=self.var_unicode_moves.get()
            )

            open(arq, "w", encoding="utf-8").write(gerar_html(blocks, css_externo=True))
            open(os.path.join(pasta, "style.css"), "w", encoding="utf-8").write(CSS)

            self.blocks, self.diagram_images = blocks, diagram_images
            messagebox.showinfo("OK!", "HTML + CSS salvos com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro ao Salvar", str(e))

    def salvar_epub(self):
        if not self.blocks:
            messagebox.showinfo("Info", "Processe o PGN primeiro.")
            return

        arq = filedialog.asksaveasfilename(defaultextension=".epub")
        if not arq:
            return

        try:
            pasta = os.path.dirname(arq)
            texto = self.txt_pgn.get("1.0", "end").strip()
            blocks, diagram_images = parse_pgn(
                texto,
                diagram_dir=os.path.join(pasta, "Images"),
                diagram_web_path="Images",
                use_unicode_moves=self.var_unicode_moves.get()
            )

            book = epub.EpubBook()
            book.set_title("Livro de Xadrez - PGN")
            book.set_language("pt")

            style = epub.EpubItem(uid="style", file_name="style/style.css",
                                  media_type="text/css", content=CSS.encode())
            book.add_item(style)

            caps = []
            for i, cont in enumerate(blocks, 1):
                c = epub.EpubHtml(title=f"Partida {i}", file_name=f"p{i}.xhtml")
                c.content = f"<html><head><link rel=\"stylesheet\" href=\"style/style.css\"/></head><body>{cont}</body></html>".encode()
                book.add_item(c)
                caps.append(c)

            book.toc = caps
            book.spine = ["nav"] + caps

            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())

            added_imgs = set()
            for info in diagram_images:
                png_path = info.get("png_path")
                web_path = info.get("web_path", "")
                if not png_path or not os.path.isfile(png_path):
                    continue
                file_name = web_path.replace("\\", "/") or os.path.basename(png_path)
                if file_name in added_imgs:
                    continue
                added_imgs.add(file_name)
                with open(png_path, "rb") as imgf:
                    content = imgf.read()
                img_item = epub.EpubItem(
                    uid=file_name,
                    file_name=file_name,
                    media_type="image/png",
                    content=content
                )
                book.add_item(img_item)

            epub.write_epub(arq, book)
            messagebox.showinfo("EPUB criado!", arq)
        except Exception as e:
            messagebox.showerror("Erro no EPUB", str(e))

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
