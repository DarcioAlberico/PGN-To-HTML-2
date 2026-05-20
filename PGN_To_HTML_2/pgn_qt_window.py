import base64
import json
import os
import queue
import re
import shutil
import sys
import tempfile
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

try:
    from .app_settings import ensure_settings_dir, get_settings_load_candidates, get_settings_path
except ImportError:
    from app_settings import ensure_settings_dir, get_settings_load_candidates, get_settings_path


VIEWER_LINE_CLICK_PREFIX = "CODEx_VIEWER_LINE:"


def _build_dom_click_bridge_script():
    return f"""
(() => {{
    if (window.__codexViewerClickBridgeInstalled) return true;
    window.__codexViewerClickBridgeInstalled = true;

    document.addEventListener('click', (event) => {{
        let el = event.target;
        if (!el) return;

        let tagged = el.closest('[data-source-line]');
        if (!tagged) {{
            const elements = document.querySelectorAll('[data-source-line]');
            let best = null;
            let bestDistance = Infinity;
            const clickY = event.clientY;
            for (const candidate of elements) {{
                const rect = candidate.getBoundingClientRect();
                const dy = Math.abs(rect.top - clickY);
                if (dy < bestDistance) {{
                    best = candidate;
                    bestDistance = dy;
                }}
            }}
            tagged = best;
        }}

        if (!tagged) return;
        const line = parseInt(tagged.getAttribute('data-source-line'), 10) || 0;
        if (line > 0) console.info('{VIEWER_LINE_CLICK_PREFIX}' + line);
    }}, true);

    return true;
}})();
"""


class ClickAwareWebEnginePage(QWebEnginePage):
    def __init__(self, line_click_callback=None, parent=None):
        super().__init__(parent)
        self.line_click_callback = line_click_callback

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        if self.line_click_callback and isinstance(message, str) and message.startswith(VIEWER_LINE_CLICK_PREFIX):
            try:
                self.line_click_callback(int(message[len(VIEWER_LINE_CLICK_PREFIX):]))
            except (TypeError, ValueError):
                pass
            return
        super().javaScriptConsoleMessage(level, message, line_number, source_id)


class ClickAwareWebEngineView(QWebEngineView):
    def __init__(self, line_click_callback=None, parent=None):
        super().__init__(parent)
        self._click_page = ClickAwareWebEnginePage(line_click_callback, self)
        self.setPage(self._click_page)

    def install_click_bridge(self):
        self.page().runJavaScript(_build_dom_click_bridge_script())


class HtmlEditorHighlighter(QSyntaxHighlighter):
    STATE_IN_STYLE = 1

    def __init__(self, document):
        super().__init__(document)
        self.formats = {
            "tag_bracket": self._make_format("#9a3412"),
            "tag_name": self._make_format("#1d4ed8"),
            "attr_name": self._make_format("#b45309"),
            "attr_value": self._make_format("#15803d"),
            "comment": self._make_format("#6b7280"),
            "doctype": self._make_format("#0f766e"),
            "css_selector": self._make_format("#7c2d12"),
            "css_property": self._make_format("#0369a1"),
            "css_value": self._make_format("#047857"),
        }
        self.tag_pattern = re.compile(r"<(/?)([A-Za-z][\\w:-]*)([^<>]*?)(/?)>")
        self.attr_pattern = re.compile(r'([A-Za-z_:][\\w:.-]*)(\\s*=\\s*)(".*?"|\\\'.*?\\\'|[^\\s"\\\'>/=]+)')
        self.comment_pattern = re.compile(r"<!--.*?-->")
        self.doctype_pattern = re.compile(r"<!DOCTYPE[^>]*>", re.IGNORECASE)
        self.css_rule_pattern = re.compile(r"([^{]+)\\{([^}]*)\\}")
        self.css_property_pattern = re.compile(r"([A-Za-z-]+)\\s*:\\s*([^;}{]+)")

    def _make_format(self, color):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        return fmt

    def highlightBlock(self, text):
        for match in self.comment_pattern.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.formats["comment"])

        for match in self.doctype_pattern.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.formats["doctype"])

        for match in self.tag_pattern.finditer(text):
            full_start, full_end = match.span()
            slash, tag_name, attrs, self_close = match.groups()
            tag_name_start = full_start + 1 + len(slash)
            tag_name_end = tag_name_start + len(tag_name)

            self.setFormat(full_start, 1 + len(slash), self.formats["tag_bracket"])
            self.setFormat(tag_name_start, tag_name_end - tag_name_start, self.formats["tag_name"])
            self.setFormat(full_end - 1 - len(self_close), 1 + len(self_close), self.formats["tag_bracket"])

            attrs_start = tag_name_end
            for attr_match in self.attr_pattern.finditer(attrs):
                name_start = attrs_start + attr_match.start(1)
                name_end = attrs_start + attr_match.end(1)
                value_start = attrs_start + attr_match.start(3)
                value_end = attrs_start + attr_match.end(3)
                self.setFormat(name_start, name_end - name_start, self.formats["attr_name"])
                self.setFormat(value_start, value_end - value_start, self.formats["attr_value"])

        self._highlight_css(text)

    def _highlight_css(self, text):
        lower_text = text.lower()
        ranges = []
        if self.previousBlockState() == self.STATE_IN_STYLE:
            end_idx = lower_text.find("</style>")
            if end_idx == -1:
                ranges.append((0, len(text)))
                self.setCurrentBlockState(self.STATE_IN_STYLE)
            else:
                ranges.append((0, end_idx))
                self.setCurrentBlockState(0)
        else:
            self.setCurrentBlockState(0)

        start_idx = lower_text.find("<style")
        if start_idx != -1:
            open_end = lower_text.find(">", start_idx)
            if open_end != -1:
                close_idx = lower_text.find("</style>", open_end + 1)
                if close_idx == -1:
                    ranges.append((open_end + 1, len(text)))
                    self.setCurrentBlockState(self.STATE_IN_STYLE)
                else:
                    ranges.append((open_end + 1, close_idx))

        for range_start, range_end in ranges:
            css_text = text[range_start:range_end]
            for rule_match in self.css_rule_pattern.finditer(css_text):
                selector_start = range_start + rule_match.start(1)
                selector_end = range_start + rule_match.end(1)
                self.setFormat(selector_start, selector_end - selector_start, self.formats["css_selector"])

                body_text = rule_match.group(2)
                body_start = range_start + rule_match.start(2)
                for prop_match in self.css_property_pattern.finditer(body_text):
                    prop_start = body_start + prop_match.start(1)
                    prop_end = body_start + prop_match.end(1)
                    value_start = body_start + prop_match.start(2)
                    value_end = body_start + prop_match.end(2)
                    self.setFormat(prop_start, prop_end - prop_start, self.formats["css_property"])
                    self.setFormat(value_start, value_end - value_start, self.formats["css_value"])


class ClickAwarePlainTextEdit(QPlainTextEdit):
    leftClicked = Signal()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.leftClicked.emit()


class App:
    def __init__(self, backend):
        self.backend = backend
        self.qt_app = QApplication.instance() or QApplication(sys.argv)
        self.window = QMainWindow()
        self.window.setWindowTitle("PGN → Livro de Xadrez (Vex. python-chess)")
        self.window.resize(1450, 920)
        self.project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.settings_path = get_settings_path()

        self.blocks = None
        self.conversion_result = None
        self.queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.processing_active = False
        self.preview_dir = None
        self.html_viewer_dirty = False
        self.viewer_last_mode = "completo"
        self.force_full_viewer_load = False
        self.pending_scroll_line = None
        self.pending_scroll_anchor = None
        self.suspend_game_nav_change = False
        self.suspend_html_modified = False
        self.suspend_css_modified = False
        self.css_user_modified = False
        self.selected_game_indexes = None
        self.diagram_style_options = dict(self.backend.chess_diagrams.get_diagram_style_options())
        self.css_preset_options = dict(self.backend.get_css_preset_options())
        self.exercise_mode_options = {
            "Livro completo": "book",
            "Somente exercícios": "exercises",
            "Livro + exercícios": "both",
        }
        self.user_settings = self.load_user_settings()
        self.last_dir = self.resolve_existing_dir(self.user_settings.get("last_dir", "."))
        self.pgn_dir = self.last_dir

        self.html_viewer_timer = QTimer()
        self.html_viewer_timer.setSingleShot(True)
        self.html_viewer_timer.timeout.connect(self.refresh_html_viewer)

        self.css_apply_timer = QTimer()
        self.css_apply_timer.setSingleShot(True)
        self.css_apply_timer.timeout.connect(self.apply_css_changes)

        self.queue_timer = QTimer()
        self.queue_timer.timeout.connect(self.check_queue)

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.window.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        top = QWidget()
        top.setStyleSheet("background:#2c3e50; color:#ecf0f1;")
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(24, 20, 24, 16)
        top_layout.setSpacing(10)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.setSpacing(10)
        buttons = [
            ("Abrir PGN", self.abrir, "#3498db"),
            ("Validar PGN", self.validar_pgn, "#607d8b"),
            ("Selecionar Partidas", self.selecionar_partidas, "#546e7a"),
            ("Processar PGN", self.iniciar_processamento, "#27ae60"),
            ("Limpar Cache", self.limpar_cache_diagramas, "#795548"),
            ("Ver no Navegador", self.preview, "#e67e22"),
            ("SALVAR HTML", self.salvar_html, "#9b59b6"),
        ]
        if self.backend.HAS_EPUB:
            buttons.append(("Salvar EPUB", self.salvar_epub, "#1abc9c"))
        buttons.append(("Salvar DOCX", self.salvar_docx, "#8e6e53"))
        buttons.append(("Salvar PDF", self.salvar_pdf, "#455a64"))
        for text, callback, color in buttons:
            button_row.addWidget(self._make_button(text, callback, color))
        self.cancel_button = self._make_button("Cancelar", self.cancelar_processamento, "#c0392b")
        self.cancel_button.setEnabled(False)
        button_row.addWidget(self.cancel_button)
        button_row.addStretch(1)
        top_layout.addLayout(button_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        top_layout.addWidget(self.progress_bar)

        self.status_lbl = QLabel("Aguardando arquivo...")
        self.status_lbl.setStyleSheet("color:#bdc3c7;")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_layout.addWidget(self.status_lbl)

        options_row = QHBoxLayout()
        options_row.addStretch(1)
        diagram_label = QLabel("Diagramas:")
        diagram_label.setStyleSheet("font-weight:600;")
        options_row.addWidget(diagram_label)
        self.diagram_style_combo = QComboBox()
        for label_text, style_value in self.diagram_style_options.items():
            self.diagram_style_combo.addItem(label_text, style_value)
        self.diagram_style_combo.setMinimumWidth(180)
        self.diagram_style_combo.currentIndexChanged.connect(self.on_diagram_style_changed)
        options_row.addWidget(self.diagram_style_combo)
        theme_label = QLabel("Tema:")
        theme_label.setStyleSheet("font-weight:600;")
        options_row.addWidget(theme_label)
        self.css_preset_combo = QComboBox()
        for label_text, preset_value in self.css_preset_options.items():
            self.css_preset_combo.addItem(label_text, preset_value)
        self.css_preset_combo.setMinimumWidth(160)
        self.css_preset_combo.currentIndexChanged.connect(self.on_css_preset_changed)
        options_row.addWidget(self.css_preset_combo)
        exercise_label = QLabel("Exercícios:")
        exercise_label.setStyleSheet("font-weight:600;")
        options_row.addWidget(exercise_label)
        self.exercise_mode_combo = QComboBox()
        for label_text, mode_value in self.exercise_mode_options.items():
            self.exercise_mode_combo.addItem(label_text, mode_value)
        self.exercise_mode_combo.setMinimumWidth(160)
        options_row.addWidget(self.exercise_mode_combo)
        options_row.addStretch(1)
        top_layout.addLayout(options_row)

        engine_row = QHBoxLayout()
        engine_row.addStretch(1)
        self.engine_enabled_checkbox = QCheckBox("Análise Stockfish")
        self.engine_enabled_checkbox.setChecked(bool(self.user_settings.get("engine_enabled", False)))
        self.engine_enabled_checkbox.toggled.connect(self.save_user_settings)
        engine_row.addWidget(self.engine_enabled_checkbox)
        self.engine_path_edit = QLineEdit()
        self.engine_path_edit.setPlaceholderText("Caminho do stockfish.exe")
        self.engine_path_edit.setText(self.user_settings.get("engine_path", ""))
        self.engine_path_edit.setMinimumWidth(340)
        self.engine_path_edit.editingFinished.connect(self.save_user_settings)
        engine_row.addWidget(self.engine_path_edit)
        engine_browse_button = QPushButton("Escolher")
        engine_browse_button.clicked.connect(self.choose_engine_path)
        engine_row.addWidget(engine_browse_button)
        engine_row.addWidget(QLabel("Profundidade:"))
        self.engine_depth_spin = QSpinBox()
        self.engine_depth_spin.setRange(1, 30)
        self.engine_depth_spin.setValue(int(self.user_settings.get("engine_depth", 12) or 12))
        self.engine_depth_spin.valueChanged.connect(self.save_user_settings)
        engine_row.addWidget(self.engine_depth_spin)
        engine_row.addStretch(1)
        top_layout.addLayout(engine_row)
        root_layout.addWidget(top)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        root_layout.addWidget(self.splitter, 1)

        self.left_tabs = QTabWidget()
        self.splitter.addWidget(self.left_tabs)

        self._build_tabs()
        self._build_tabs_corner_actions()
        self._build_html_panel()
        self.left_tabs.currentChanged.connect(self.on_left_tab_changed)
        self.splitter.setSizes([640, 810])
        self.set_css_text(self.build_selected_preset_css())

    def _build_tabs(self):
        pgn_tab = QWidget()
        pgn_layout = QVBoxLayout(pgn_tab)
        pgn_layout.setContentsMargins(12, 12, 12, 12)
        pgn_layout.setSpacing(6)
        pgn_layout.addWidget(self._make_section_label("Cole ou abra o PGN aqui"))
        self.txt_pgn = self._make_editor("Consolas", 11)
        pgn_layout.addWidget(self.txt_pgn, 1)
        self.left_tabs.addTab(pgn_tab, "PGN")

        self.viewer_tab = QWidget()
        viewer_layout = QVBoxLayout(self.viewer_tab)
        viewer_layout.setContentsMargins(12, 12, 12, 12)
        viewer_layout.setSpacing(6)
        viewer_top = QHBoxLayout()
        viewer_top.addWidget(self._make_section_label("HTML Viewer"))
        viewer_top.addStretch(1)
        viewer_top.addWidget(QLabel("Partida:"))
        self.game_nav_combo = QComboBox()
        self.game_nav_combo.setMinimumWidth(210)
        self.game_nav_combo.addItem("Todas", "")
        self.game_nav_combo.currentIndexChanged.connect(self.on_game_nav_changed)
        viewer_top.addWidget(self.game_nav_combo)
        viewer_top.addWidget(QLabel("Modo:"))
        self.viewer_mode_combo = QComboBox()
        self.viewer_mode_combo.addItem("Normal", "normal")
        self.viewer_mode_combo.addItem("A4", "a4")
        self.viewer_mode_combo.addItem("E-reader", "ereader")
        self.viewer_mode_combo.currentIndexChanged.connect(self.on_viewer_mode_changed)
        viewer_top.addWidget(self.viewer_mode_combo)
        viewer_top.addWidget(QLabel("Zoom:"))
        self.viewer_zoom_combo = QComboBox()
        for label, factor in (("75%", 0.75), ("100%", 1.0), ("125%", 1.25), ("150%", 1.5), ("200%", 2.0)):
            self.viewer_zoom_combo.addItem(label, factor)
        self.viewer_zoom_combo.setCurrentIndex(1)
        self.viewer_zoom_combo.currentIndexChanged.connect(self.on_viewer_zoom_changed)
        viewer_top.addWidget(self.viewer_zoom_combo)
        self.auto_viewer_checkbox = QCheckBox("Auto")
        self.auto_viewer_checkbox.setChecked(True)
        self.auto_viewer_checkbox.toggled.connect(self.on_auto_viewer_toggle)
        viewer_top.addWidget(self.auto_viewer_checkbox)
        refresh_button = QPushButton("Atualizar Viewer")
        refresh_button.clicked.connect(self.refresh_html_viewer_now)
        viewer_top.addWidget(refresh_button)
        self.full_viewer_button = QPushButton("Documento completo")
        self.full_viewer_button.clicked.connect(self.refresh_full_html_viewer)
        viewer_top.addWidget(self.full_viewer_button)
        viewer_layout.addLayout(viewer_top)
        self.viewer_status = QLabel("Preview aguardando HTML...")
        self.viewer_status.setStyleSheet("color:#666;")
        viewer_layout.addWidget(self.viewer_status)
        self.html_view = ClickAwareWebEngineView(self.on_html_viewer_line_click)
        self.html_view.loadFinished.connect(self.on_html_viewer_load_finished)
        viewer_layout.addWidget(self.html_view, 1)
        self.left_tabs.addTab(self.viewer_tab, "HTML Viewer")

        css_tab = QWidget()
        css_layout = QVBoxLayout(css_tab)
        css_layout.setContentsMargins(12, 12, 12, 12)
        css_layout.setSpacing(6)
        css_top = QHBoxLayout()
        css_top.addWidget(self._make_section_label("CSS"))
        css_top.addStretch(1)
        load_button = QPushButton("Carregar CSS")
        load_button.clicked.connect(self.load_css_file)
        css_top.addWidget(load_button)
        save_button = QPushButton("Salvar CSS")
        save_button.clicked.connect(self.save_css_file)
        css_top.addWidget(save_button)
        css_layout.addLayout(css_top)
        self.txt_css = self._make_editor("Consolas", 10)
        self.txt_css.textChanged.connect(self.on_css_modified)
        css_layout.addWidget(self.txt_css, 1)
        self.left_tabs.addTab(css_tab, "CSS")

    def _build_tabs_corner_actions(self):
        self.generate_diagram_tab_button = QPushButton("Gerar Diagrama")
        self.generate_diagram_tab_button.setToolTip(
            "Insere um diagrama no HTML gerado usando a posição do cursor."
        )
        self.generate_diagram_tab_button.clicked.connect(self.gerar_diagrama_no_html)
        self.left_tabs.setCornerWidget(
            self.generate_diagram_tab_button,
            Qt.Corner.TopRightCorner,
        )

    def _build_html_panel(self):
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(6)
        right_layout.addWidget(self._make_section_label("HTML gerado"))
        self.txt_html = self._make_editor("Georgia", 12, editor_class=ClickAwarePlainTextEdit)
        self.txt_html.textChanged.connect(self.on_html_modified)
        self.txt_html.leftClicked.connect(self.on_html_editor_clicked)
        self.html_highlighter = HtmlEditorHighlighter(self.txt_html.document())
        right_layout.addWidget(self.txt_html, 1)
        self.splitter.addWidget(right_panel)

    def _make_button(self, text, callback, color):
        button = QPushButton(text)
        button.clicked.connect(callback)
        button.setMinimumSize(165, 48)
        button.setStyleSheet(
            f"QPushButton {{ background:{color}; color:white; font-weight:700; border:none; padding:10px 18px; }}"
        )
        return button

    def _make_section_label(self, text):
        label = QLabel(text)
        font = QFont("Arial", 12)
        font.setBold(True)
        label.setFont(font)
        return label

    def _make_editor(self, family, size, editor_class=QPlainTextEdit):
        editor = editor_class()
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        editor.setFont(QFont(family, size))
        editor.setStyleSheet("background:white; color:#111;")
        return editor

    def get_selected_diagram_style(self):
        return self.diagram_style_combo.currentData()

    def get_selected_css_preset(self):
        return self.css_preset_combo.currentData() if hasattr(self, "css_preset_combo") else "classic"

    def get_selected_exercise_mode(self):
        return self.exercise_mode_combo.currentData() if hasattr(self, "exercise_mode_combo") else "book"

    def load_user_settings(self):
        for settings_path in get_settings_load_candidates(self.project_dir):
            try:
                with open(settings_path, "r", encoding="utf-8") as file_obj:
                    data = json.load(file_obj)
                return data if isinstance(data, dict) else {}
            except FileNotFoundError:
                continue
            except (OSError, json.JSONDecodeError):
                return {}
        return {}

    def save_user_settings(self, *_args):
        if not hasattr(self, "engine_path_edit"):
            return
        data = {
            "engine_enabled": self.engine_enabled_checkbox.isChecked(),
            "engine_path": self.engine_path_edit.text().strip(),
            "engine_depth": self.engine_depth_spin.value(),
            "last_dir": self.last_dir,
        }
        try:
            ensure_settings_dir(self.settings_path)
            with open(self.settings_path, "w", encoding="utf-8") as file_obj:
                json.dump(data, file_obj, indent=2)
        except OSError:
            pass

    def resolve_existing_dir(self, path):
        candidate = os.path.abspath(path or ".")
        if os.path.isfile(candidate):
            candidate = os.path.dirname(candidate)
        while candidate and not os.path.isdir(candidate):
            parent = os.path.dirname(candidate)
            if parent == candidate:
                return os.path.abspath(".")
            candidate = parent
        return candidate or os.path.abspath(".")

    def remember_file_dir(self, path):
        if not path:
            return
        self.last_dir = self.resolve_existing_dir(os.path.dirname(path) or path)
        self.pgn_dir = self.last_dir
        self.save_user_settings()

    def initial_file_path(self, extension=""):
        if not extension:
            return self.last_dir
        return os.path.join(self.last_dir, extension)

    def choose_engine_path(self):
        current = self.engine_path_edit.text().strip()
        start_dir = os.path.dirname(current) if current else ""
        path, _ = QFileDialog.getOpenFileName(
            self.window,
            "Selecionar Stockfish",
            start_dir,
            "Executáveis (*.exe);;Todos (*.*)",
        )
        if path:
            self.engine_path_edit.setText(path)
            self.engine_enabled_checkbox.setChecked(True)
            self.save_user_settings()

    def get_engine_options(self):
        enabled = self.engine_enabled_checkbox.isChecked() if hasattr(self, "engine_enabled_checkbox") else False
        engine_path = self.engine_path_edit.text().strip() if hasattr(self, "engine_path_edit") else ""
        engine_depth = self.engine_depth_spin.value() if hasattr(self, "engine_depth_spin") else 12
        return {
            "include_engine_analysis": bool(enabled and engine_path),
            "engine_path": engine_path,
            "engine_depth": engine_depth,
        }

    def build_selected_preset_css(self):
        return self.backend.load_css_preset(
            self.get_selected_css_preset(),
            diagram_style=self.get_selected_diagram_style(),
        )

    def get_current_css_text(self):
        css_text = self.txt_css.toPlainText()
        return css_text if css_text.strip() else self.build_selected_preset_css()

    def get_effective_diagram_style(self):
        if self.conversion_result is not None:
            return self.conversion_result.diagram_style
        return self.get_selected_diagram_style()

    def set_css_text(self, css_text):
        self.suspend_css_modified = True
        try:
            self.txt_css.setPlainText(css_text or "")
        finally:
            self.suspend_css_modified = False

    def on_css_preset_changed(self, _index):
        if not hasattr(self, "txt_css"):
            return
        self.set_css_text(self.build_selected_preset_css())
        self.css_user_modified = self.get_selected_css_preset() != "classic"
        self.apply_css_changes()

    def on_diagram_style_changed(self, _index):
        if not hasattr(self, "txt_css") or self.css_user_modified:
            return
        self.set_css_text(self.build_selected_preset_css())

    def get_current_html_text(self):
        return self.merge_css_into_html(self.txt_html.toPlainText(), self.get_current_css_text())

    def set_html_text(self, html_text):
        css_text = self.extract_css_from_html(html_text)
        if css_text:
            self.set_css_text(css_text)

        formatted_html = self.format_html_for_editor(html_text)

        self.suspend_html_modified = True
        try:
            self.txt_html.setPlainText(formatted_html or "")
        finally:
            self.suspend_html_modified = False

        self.html_viewer_dirty = True
        if not formatted_html.strip():
            self.html_view.setHtml("<!DOCTYPE html><html><body></body></html>", QUrl())
            self.viewer_status.setText("Preview aguardando HTML...")
            self.populate_game_navigation([])
            return

        self.update_viewer_pending_status()
        self.schedule_html_viewer_update(350)

    def extract_css_from_html(self, html_text):
        match = re.search(r"<style\b[^>]*>(.*?)</style>", html_text, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else ""

    def merge_css_into_html(self, html_text, css_text):
        css_text = css_text or ""
        style_block = f"<style>{css_text}</style>"
        if re.search(r"<style\b[^>]*>.*?</style>", html_text, re.IGNORECASE | re.DOTALL):
            return re.sub(
                r"<style\b[^>]*>.*?</style>",
                style_block,
                html_text,
                count=1,
                flags=re.IGNORECASE | re.DOTALL,
            )
        if re.search(r"</head>", html_text, re.IGNORECASE):
            return re.sub(r"</head>", style_block + "</head>", html_text, count=1, flags=re.IGNORECASE)
        return style_block + html_text

    def format_html_for_editor(self, html_text):
        if not html_text.strip():
            return html_text

        lines = html_text.splitlines()
        formatted_lines = []
        previous_nonempty = ""
        in_style_block = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if formatted_lines and formatted_lines[-1] != "":
                    formatted_lines.append("")
                continue

            lower_stripped = stripped.lower()
            starts_style = "<style" in lower_stripped
            ends_style = "</style>" in lower_stripped

            if (
                formatted_lines
                and formatted_lines[-1] != ""
                and not in_style_block
                and stripped.startswith("<")
                and previous_nonempty.endswith(">")
            ):
                formatted_lines.append("")

            formatted_lines.append(line)

            if starts_style and not ends_style:
                in_style_block = True
            elif in_style_block and ends_style:
                in_style_block = False

            previous_nonempty = stripped

        return "\n".join(formatted_lines)

    def on_html_modified(self):
        if self.suspend_html_modified:
            return
        self.html_viewer_dirty = True
        self.update_viewer_pending_status()
        self.schedule_html_viewer_update()

    def on_html_editor_clicked(self):
        self.txt_html.setExtraSelections([])
        self.pending_scroll_line = self.get_current_html_line_number()
        self.html_viewer_dirty = True
        if self.is_viewer_tab_active():
            self.refresh_html_viewer_now()
        else:
            self.update_viewer_pending_status()

    def on_css_modified(self):
        if self.suspend_css_modified:
            return
        self.css_user_modified = True
        self.css_apply_timer.start(300)

    def on_left_tab_changed(self, _index):
        if self.is_viewer_tab_active() and self.html_viewer_dirty:
            self.update_viewer_pending_status()
            self.schedule_html_viewer_update(250)

    def populate_game_navigation(self, summaries=None):
        if not hasattr(self, "game_nav_combo"):
            return

        current_anchor = self.game_nav_combo.currentData() if self.game_nav_combo.count() else ""
        self.suspend_game_nav_change = True
        try:
            self.game_nav_combo.clear()
            self.game_nav_combo.addItem("Todas", "")
            for summary in summaries or []:
                label = f"{summary.index}. {summary.title}"
                self.game_nav_combo.addItem(label, summary.anchor)
            if current_anchor:
                index = self.game_nav_combo.findData(current_anchor)
                if index >= 0:
                    self.game_nav_combo.setCurrentIndex(index)
        finally:
            self.suspend_game_nav_change = False

    def on_game_nav_changed(self, _index):
        if self.suspend_game_nav_change:
            return
        anchor = self.game_nav_combo.currentData()
        if not anchor:
            self.pending_scroll_anchor = None
            return

        self.pending_scroll_anchor = anchor
        line_number = self.find_html_line_for_anchor(anchor)
        if line_number is not None:
            block = self.txt_html.document().findBlockByNumber(line_number - 1)
            if block.isValid():
                cursor = QTextCursor(block)
                self.txt_html.setTextCursor(cursor)
        if self.is_viewer_tab_active():
            self.refresh_html_viewer_now()

    def on_viewer_mode_changed(self, _index):
        self.html_viewer_dirty = True
        self.update_viewer_pending_status()
        if self.is_viewer_tab_active():
            self.refresh_html_viewer_now()

    def on_viewer_zoom_changed(self, _index):
        factor = self.viewer_zoom_combo.currentData()
        try:
            self.html_view.setZoomFactor(float(factor))
        except (TypeError, ValueError):
            self.html_view.setZoomFactor(1.0)

    def on_auto_viewer_toggle(self, _checked):
        self.update_viewer_pending_status()
        self.html_viewer_timer.stop()
        if self.auto_viewer_checkbox.isChecked() and self.html_viewer_dirty and self.is_viewer_tab_active():
            self.schedule_html_viewer_update(250)

    def schedule_html_viewer_update(self, delay_ms=900):
        if not self.should_auto_refresh_viewer():
            return
        self.html_viewer_timer.start(delay_ms)

    def refresh_html_viewer_now(self):
        self.html_viewer_timer.stop()
        self.refresh_html_viewer()

    def refresh_full_html_viewer(self):
        self.html_viewer_timer.stop()
        self.force_full_viewer_load = True
        self.refresh_html_viewer()

    def apply_css_changes(self):
        html_text = self.txt_html.toPlainText()
        if not html_text.strip():
            return

        merged_html = self.format_html_for_editor(
            self.merge_css_into_html(html_text, self.get_current_css_text())
        )
        if merged_html != html_text:
            cursor_pos = self.txt_html.textCursor().position()
            vscroll = self.txt_html.verticalScrollBar().value()
            hscroll = self.txt_html.horizontalScrollBar().value()

            self.suspend_html_modified = True
            try:
                self.txt_html.setPlainText(merged_html)
            finally:
                self.suspend_html_modified = False

            cursor = self.txt_html.textCursor()
            cursor.setPosition(min(cursor_pos, len(merged_html)))
            self.txt_html.setTextCursor(cursor)
            self.txt_html.verticalScrollBar().setValue(vscroll)
            self.txt_html.horizontalScrollBar().setValue(hscroll)

        self.html_viewer_dirty = True
        self.update_viewer_pending_status()
        self.schedule_html_viewer_update(400)

    def is_viewer_tab_active(self):
        if not hasattr(self, "viewer_tab"):
            return False
        return self.left_tabs.currentWidget() is self.viewer_tab

    def is_large_html_document(self):
        html_text = self.txt_html.toPlainText()
        return len(html_text) > 45000 or self.txt_html.document().blockCount() > 900

    def should_auto_refresh_viewer(self):
        return self.auto_viewer_checkbox.isChecked() and self.is_viewer_tab_active() and not self.is_large_html_document()

    def update_viewer_pending_status(self):
        if self.is_large_html_document():
            self.viewer_status.setText(
                "Preview pendente. HTML grande: 'Atualizar Viewer' carrega a secao atual; "
                "'Documento completo' carrega tudo."
            )
        elif not self.auto_viewer_checkbox.isChecked():
            self.viewer_status.setText("Preview pendente. Auto desligado; use 'Atualizar Viewer'.")
        else:
            self.viewer_status.setText("Preview pendente...")

    def get_html_insert_offset(self):
        return self.txt_html.textCursor().position()

    def get_current_html_line_number(self):
        return self.txt_html.textCursor().blockNumber() + 1

    def _inject_viewer_helper_style(self, html_text):
        mode = self.viewer_mode_combo.currentData() if hasattr(self, "viewer_mode_combo") else "normal"
        mode_css = ""
        if mode == "a4":
            mode_css = (
                "html{background:#9aa5b1;}"
                "body{background:#fff;max-width:794px;min-height:1123px;"
                "margin:28px auto;padding:56px;box-shadow:0 3px 18px rgba(0,0,0,.24);}"
            )
        elif mode == "ereader":
            mode_css = (
                "body{max-width:620px;margin:28px auto;padding:0 18px;"
                "font-size:20px;line-height:1.9;background:#fffdf7;}"
                "p.mainline{text-align:left;}"
            )
        helper_style = (
            '<style id="codex-viewer-helper-style">'
            '[data-source-selected="1"]{outline:2px solid #eab308;'
            'background:rgba(255,243,163,0.25);}'
            f'{mode_css}'
            '</style>'
        )
        if "codex-viewer-helper-style" in html_text:
            return html_text
        if re.search(r"</head>", html_text, re.IGNORECASE):
            return re.sub(r"</head>", helper_style + "</head>", html_text, count=1, flags=re.IGNORECASE)
        return helper_style + html_text

    def _inject_source_line_markers(self, html_text):
        marked_lines = []
        tag_pattern = re.compile(r"<([A-Za-z][\w:-]*)(?=[\s>/])")
        for line_number, line in enumerate(html_text.splitlines(), start=1):
            def add_marker(match):
                tag_name = match.group(1).lower()
                if tag_name in {"html", "head", "body", "meta", "link", "style", "script", "title"}:
                    return match.group(0)
                return f'<{match.group(1)} data-source-line="{line_number}"'

            marked_lines.append(tag_pattern.sub(add_marker, line))
        return "\n".join(marked_lines)

    def find_html_line_for_anchor(self, anchor):
        if not anchor:
            return None
        pattern = re.compile(rf'\bid=(["\']){re.escape(anchor)}\1')
        for block_number, line in enumerate(self.txt_html.toPlainText().splitlines(), start=1):
            if pattern.search(line):
                return block_number
        return None

    def _rewrite_viewer_font_urls(self, html_text):
        font_dir = os.path.join(self.project_dir, self.backend.chess_diagrams.FONT_OUTPUT_DIRNAME)

        def replace_font_url(match):
            quote = match.group(1) or '"'
            file_name = match.group(2)
            font_path = os.path.join(font_dir, file_name)
            extension = os.path.splitext(file_name)[1].lower()
            media_type = self.backend.chess_diagrams.get_support_file_media_type(file_name)
            font_format = "opentype" if extension == ".otf" else "truetype"

            if os.path.isfile(font_path):
                try:
                    with open(font_path, "rb") as file_obj:
                        encoded = base64.b64encode(file_obj.read()).decode("ascii")
                    return f'url({quote}data:{media_type};base64,{encoded}{quote}) format("{font_format}")'
                except Exception:
                    pass

            font_uri = Path(font_path).as_uri()
            return f'url({quote}{font_uri}{quote}) format("{font_format}")'

        return re.sub(
            r'url\((["\']?)Fonts/([^"\')]+)\1\)',
            replace_font_url,
            html_text,
            flags=re.IGNORECASE,
        )

    def _split_html_body(self, html_text):
        body_match = re.search(r"(<body\b[^>]*>)(.*?)(</body>)", html_text, re.IGNORECASE | re.DOTALL)
        if not body_match:
            return None

        prefix = html_text[:body_match.start(2)]
        body_content = body_match.group(2)
        suffix = html_text[body_match.end(2):]
        parts = []
        separators = []
        part_starts = []
        last_end = 0

        for match in re.finditer(r"<hr\b[^>]*>", body_content, re.IGNORECASE):
            part_starts.append(last_end)
            parts.append(body_content[last_end:match.start()])
            separators.append(match.group(0))
            last_end = match.end()

        part_starts.append(last_end)
        parts.append(body_content[last_end:])
        return {
            "prefix": prefix,
            "suffix": suffix,
            "parts": parts,
            "separators": separators,
            "part_starts": part_starts,
            "body_start": body_match.start(2),
        }

    def build_viewer_html(self, html_text, force_full_document=False):
        marked_html = self._inject_viewer_helper_style(self._inject_source_line_markers(html_text))
        if force_full_document or not self.is_large_html_document():
            return self._rewrite_viewer_font_urls(marked_html), "completo"

        original_split = self._split_html_body(html_text)
        marked_split = self._split_html_body(marked_html)
        if not original_split or not marked_split:
            return self._rewrite_viewer_font_urls(marked_html), "completo"
        if len(original_split["parts"]) != len(marked_split["parts"]):
            return self._rewrite_viewer_font_urls(marked_html), "completo"

        cursor_offset = max(0, self.get_html_insert_offset() - original_split["body_start"])
        current_part_index = 0
        for idx, part_start in enumerate(original_split["part_starts"]):
            if part_start <= cursor_offset:
                current_part_index = idx
            else:
                break

        target_chars = 6000
        start_part = current_part_index
        end_part = current_part_index
        current_size = len(original_split["parts"][current_part_index].strip())

        def left_addition_size(index):
            return len(original_split["separators"][index]) + len(original_split["parts"][index].strip())

        def right_addition_size(index):
            return len(original_split["separators"][index - 1]) + len(original_split["parts"][index].strip())

        while current_size < target_chars and (start_part > 0 or end_part < len(original_split["parts"]) - 1):
            candidates = []
            if start_part > 0:
                left_size = left_addition_size(start_part - 1)
                candidates.append((abs(target_chars - (current_size + left_size)), left_size, "left"))
            if end_part < len(original_split["parts"]) - 1:
                right_size = right_addition_size(end_part + 1)
                candidates.append((abs(target_chars - (current_size + right_size)), right_size, "right"))
            if not candidates:
                break
            _, added_size, side = min(candidates, key=lambda item: (item[0], item[1]))
            current_size += added_size
            if side == "left":
                start_part -= 1
            else:
                end_part += 1

        selected_parts = []
        for idx in range(start_part, end_part + 1):
            if selected_parts and idx - 1 < len(marked_split["separators"]):
                selected_parts.append(marked_split["separators"][idx - 1])
            selected_parts.append(marked_split["parts"][idx])

        partial_body = "".join(selected_parts).strip() or marked_split["parts"][current_part_index]
        partial_html = marked_split["prefix"] + partial_body + marked_split["suffix"]
        return self._rewrite_viewer_font_urls(partial_html), "parcial"

    def refresh_html_viewer(self):
        html_text = self.txt_html.toPlainText().strip()
        if not html_text:
            self.html_view.setHtml("<!DOCTYPE html><html><body></body></html>", QUrl())
            self.html_viewer_dirty = False
            self.viewer_status.setText("Preview aguardando HTML...")
            return

        if self.force_full_viewer_load:
            self.viewer_status.setText("Carregando documento completo...")
        else:
            self.viewer_status.setText("Atualizando preview...")
        try:
            viewer_html, viewer_mode = self.build_viewer_html(
                html_text,
                force_full_document=self.force_full_viewer_load,
            )
            self.viewer_last_mode = viewer_mode
            base_url = QUrl.fromLocalFile(os.path.join(os.path.abspath(self.pgn_dir or "."), ""))
            self.on_viewer_zoom_changed(self.viewer_zoom_combo.currentIndex())
            self.html_view.setHtml(viewer_html, base_url)
        except Exception as exc:
            self.viewer_status.setText(f"Falha no preview: {exc}")
        finally:
            self.force_full_viewer_load = False

    def on_html_viewer_load_finished(self, ok):
        if not ok:
            self.viewer_status.setText("Falha ao carregar o HTML no viewer.")
            return
        self.html_view.install_click_bridge()
        self.html_viewer_dirty = False
        mode_label = "parcial" if self.viewer_last_mode == "parcial" else "completo"
        status = f"Preview {mode_label} atualizado em {datetime.now().strftime('%H:%M:%S')}"
        if self.viewer_last_mode == "parcial":
            status += " | use 'Documento completo' para carregar tudo"
        self.viewer_status.setText(status)
        if self.pending_scroll_line is not None:
            self.scroll_viewer_to_source_line(self.pending_scroll_line)
        if self.pending_scroll_anchor is not None:
            self.scroll_viewer_to_anchor(self.pending_scroll_anchor)

    def on_html_viewer_line_click(self, line_number):
        self.highlight_html_line(line_number)
        self.txt_html.setFocus()

    def scroll_viewer_to_source_line(self, line_number):
        script = f"""
(() => {{
    const wanted = {int(line_number)};
    let target = document.querySelector(`[data-source-line="${int(line_number)}"]`);
    if (!target) {{
        const elements = Array.from(document.querySelectorAll('[data-source-line]'));
        let best = null;
        let bestDistance = Infinity;
        for (const candidate of elements) {{
            const value = parseInt(candidate.getAttribute('data-source-line'), 10);
            if (!Number.isFinite(value)) continue;
            const distance = Math.abs(value - wanted);
            if (distance < bestDistance) {{
                best = candidate;
                bestDistance = distance;
            }}
        }}
        target = best;
    }}
    const previous = document.querySelector('[data-source-selected="1"]');
    if (previous) previous.removeAttribute('data-source-selected');
    if (!target) return null;
    target.setAttribute('data-source-selected', '1');
    target.scrollIntoView({{ block: 'center', inline: 'nearest', behavior: 'auto' }});
    return parseInt(target.getAttribute('data-source-line'), 10) || null;
}})();
"""
        self.html_view.page().runJavaScript(script, self._on_scroll_viewer_result)

    def scroll_viewer_to_anchor(self, anchor):
        safe_anchor = re.sub(r"[^A-Za-z0-9_:\\-.]", "", anchor or "")
        if not safe_anchor:
            return
        script = f"""
(() => {{
    const target = document.getElementById("{safe_anchor}");
    if (!target) return false;
    const previous = document.querySelector('[data-source-selected="1"]');
    if (previous) previous.removeAttribute('data-source-selected');
    target.setAttribute('data-source-selected', '1');
    target.scrollIntoView({{ block: 'start', inline: 'nearest', behavior: 'auto' }});
    return true;
}})();
"""
        self.html_view.page().runJavaScript(script)

    def _on_scroll_viewer_result(self, result):
        if result is None:
            return
        try:
            self.pending_scroll_line = int(result)
        except (TypeError, ValueError):
            return

    def highlight_html_line(self, line_number):
        total_lines = self.txt_html.document().blockCount()
        line_number = max(1, min(line_number, total_lines))
        block = self.txt_html.document().findBlockByNumber(line_number - 1)
        if not block.isValid():
            return

        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format.setBackground(QColor("#fff3a3"))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        self.txt_html.setExtraSelections([selection])
        self.txt_html.setTextCursor(cursor)
        self.txt_html.centerCursor()
        self.pending_scroll_line = line_number
        self.viewer_status.setText(
            f"Preview atualizado em {datetime.now().strftime('%H:%M:%S')} | linha {line_number}"
        )

    def copy_current_support_files(self, output_dir):
        if self.conversion_result is None:
            return

        if self.backend.chess_diagrams.uses_merida_style(self.conversion_result.diagram_style):
            self.backend.chess_diagrams.copy_support_files(self.conversion_result.diagram_style, output_dir)

        if not self.conversion_result.diagram_assets:
            return

        diagram_dir = os.path.join(output_dir, "Diagrams")
        os.makedirs(diagram_dir, exist_ok=True)
        for asset in self.conversion_result.diagram_assets:
            for asset_path in (asset.svg_path, asset.png_path):
                if not asset_path or not os.path.isfile(asset_path):
                    continue
                target_path = os.path.join(diagram_dir, os.path.basename(asset_path))
                if os.path.abspath(asset_path) == os.path.abspath(target_path):
                    continue
                shutil.copyfile(asset_path, target_path)

    def write_current_html_bundle(self, html_path):
        html_text = self.get_current_html_text().strip()
        if not html_text:
            raise RuntimeError("Nao ha HTML para salvar.")

        output_dir = os.path.dirname(html_path)
        os.makedirs(output_dir, exist_ok=True)
        self.copy_current_support_files(output_dir)

        with open(html_path, "w", encoding="utf-8") as file_obj:
            file_obj.write(html_text)

        with open(os.path.join(output_dir, "style.css"), "w", encoding="utf-8") as file_obj:
            file_obj.write(self.get_current_css_text())

    def gerar_diagrama_no_html(self):
        pgn_text = self.txt_pgn.toPlainText().strip()
        html_text = self.txt_html.toPlainText()
        if not pgn_text or not html_text.strip():
            QMessageBox.warning(self.window, "Gerar Diagrama", "Processe o PGN antes de gerar um diagrama.")
            return

        cursor = self.txt_html.textCursor()
        insert_pos = cursor.position()
        try:
            fen = self.backend.infer_fen_from_html_cursor(pgn_text, html_text, insert_pos)
            diagram_dir = os.path.join(os.path.abspath(self.pgn_dir or "."), "Diagrams")
            diagram_result = self.backend.chess_diagrams.render_diagram_html(
                fen,
                output_dir=diagram_dir,
                base_name="manual_diagram",
                idx=insert_pos,
                size=360,
                style=self.get_effective_diagram_style(),
                web_root=os.path.abspath(self.pgn_dir or "."),
            )
            snippet = "\n\n" + diagram_result["html"] + "\n" + self.backend._generate_analysis_links(fen) + "\n"
            cursor.insertText(snippet)
            self.txt_html.setTextCursor(cursor)

            asset = diagram_result.get("asset")
            if asset and self.conversion_result is not None:
                self.conversion_result.diagram_assets.append(
                    self.backend.DiagramAsset(
                        fen=fen,
                        svg_path=asset["svg_path"],
                        png_path=asset["png_path"],
                        web_path=asset["web_path"],
                    )
                )
            self.html_viewer_dirty = True
            self.update_viewer_pending_status()
            self.schedule_html_viewer_update(250)
            self.status_lbl.setText("Diagrama inserido no HTML.")
        except Exception as exc:
            QMessageBox.warning(self.window, "Gerar Diagrama", str(exc))

    def abrir(self):
        arq, _ = QFileDialog.getOpenFileName(self.window, "Abrir PGN", self.last_dir, "PGN (*.pgn)")
        if not arq:
            return
        self.remember_file_dir(arq)
        try:
            with open(arq, "r", encoding="utf-8", errors="ignore") as file_obj:
                self.txt_pgn.setPlainText(file_obj.read())
            self.status_lbl.setText(f"Arquivo carregado: {os.path.basename(arq)}")
        except Exception as exc:
            QMessageBox.critical(self.window, "Erro", f"Nao foi possivel ler o arquivo: {exc}")

    def validar_pgn(self):
        texto = self.txt_pgn.toPlainText().strip()
        if not texto:
            QMessageBox.warning(self.window, "Aviso", "Cole ou abra um arquivo PGN primeiro!")
            return

        issues = self.backend.validate_pgn(texto)
        report = self.backend.format_validation_report(issues)
        if issues:
            QMessageBox.warning(self.window, "Validação PGN", report)
            error_count = sum(1 for issue in issues if issue.severity == "error")
            warning_count = len(issues) - error_count
            self.status_lbl.setText(f"Validacao: {error_count} erro(s), {warning_count} aviso(s).")
        else:
            QMessageBox.information(self.window, "Validação PGN", report)
            self.status_lbl.setText("Validacao: nenhum problema encontrado.")

    def selecionar_partidas(self):
        texto = self.txt_pgn.toPlainText().strip()
        if not texto:
            QMessageBox.warning(self.window, "Aviso", "Cole ou abra um arquivo PGN primeiro!")
            return

        summaries = self.backend.scan_pgn_headers(texto)
        if not summaries:
            QMessageBox.warning(self.window, "Selecionar Partidas", "Nenhuma partida PGN foi encontrada.")
            return

        dialog = QDialog(self.window)
        dialog.setWindowTitle("Selecionar Partidas")
        dialog.resize(860, 520)
        layout = QVBoxLayout(dialog)

        filter_row = QHBoxLayout()
        player_input = QLineEdit()
        player_input.setPlaceholderText("Jogador")
        eco_input = QLineEdit()
        eco_input.setPlaceholderText("ECO")
        result_input = QLineEdit()
        result_input.setPlaceholderText("Resultado")
        filter_row.addWidget(QLabel("Filtros:"))
        filter_row.addWidget(player_input)
        filter_row.addWidget(eco_input)
        filter_row.addWidget(result_input)
        layout.addLayout(filter_row)

        table = QTableWidget(0, 7)
        table.setHorizontalHeaderLabels(["Usar", "#", "Brancas", "Pretas", "ECO", "Resultado", "Evento"])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(table, 1)

        selected = set(self.selected_game_indexes or [summary.index for summary in summaries])
        visible_summaries = []

        def populate():
            nonlocal visible_summaries
            visible_summaries = self.backend.filter_game_summaries(
                summaries,
                player=player_input.text(),
                eco=eco_input.text(),
                result=result_input.text(),
            )
            table.setRowCount(len(visible_summaries))
            for row, summary in enumerate(visible_summaries):
                check_item = QTableWidgetItem()
                check_item.setFlags(
                    Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                check_item.setCheckState(
                    Qt.CheckState.Checked if summary.index in selected else Qt.CheckState.Unchecked
                )
                table.setItem(row, 0, check_item)
                values = [
                    str(summary.index),
                    summary.white,
                    summary.black,
                    summary.eco,
                    summary.result,
                    summary.event,
                ]
                for col, value in enumerate(values, start=1):
                    table.setItem(row, col, QTableWidgetItem(value or ""))
            table.resizeColumnsToContents()

        def sync_visible_selection():
            for row, summary in enumerate(visible_summaries):
                item = table.item(row, 0)
                if item and item.checkState() == Qt.CheckState.Checked:
                    selected.add(summary.index)
                else:
                    selected.discard(summary.index)

        def apply_filters():
            sync_visible_selection()
            populate()

        player_input.textChanged.connect(lambda _text: apply_filters())
        eco_input.textChanged.connect(lambda _text: apply_filters())
        result_input.textChanged.connect(lambda _text: apply_filters())

        action_row = QHBoxLayout()
        select_visible_button = QPushButton("Marcar visíveis")
        clear_visible_button = QPushButton("Desmarcar visíveis")
        all_button = QPushButton("Marcar todas")
        none_button = QPushButton("Desmarcar todas")
        action_row.addWidget(select_visible_button)
        action_row.addWidget(clear_visible_button)
        action_row.addWidget(all_button)
        action_row.addWidget(none_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        def set_visible_checked(checked):
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item:
                    item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            sync_visible_selection()

        select_visible_button.clicked.connect(lambda: set_visible_checked(True))
        clear_visible_button.clicked.connect(lambda: set_visible_checked(False))
        all_button.clicked.connect(lambda: (selected.update(summary.index for summary in summaries), populate()))
        none_button.clicked.connect(lambda: (selected.clear(), populate()))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        populate()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        sync_visible_selection()
        self.selected_game_indexes = sorted(selected)
        total = len(summaries)
        chosen = len(self.selected_game_indexes)
        if chosen == total:
            self.selected_game_indexes = None
            self.status_lbl.setText(f"Selecao: todas as {total} partida(s).")
        else:
            self.status_lbl.setText(f"Selecao: {chosen}/{total} partida(s).")

    def limpar_cache_diagramas(self):
        diagram_dir = os.path.join(os.path.abspath(self.pgn_dir or "."), "Diagrams")
        removed = self.backend.chess_diagrams.clear_diagram_cache(diagram_dir)
        QMessageBox.information(
            self.window,
            "Cache de Diagramas",
            f"{removed} arquivo(s) de cache removido(s) em:\n{diagram_dir}",
        )
        self.status_lbl.setText(f"Cache de diagramas limpo: {removed} arquivo(s).")

    def iniciar_processamento(self):
        texto = self.txt_pgn.toPlainText().strip()
        if not texto:
            QMessageBox.warning(self.window, "Aviso", "Cole ou abra um arquivo PGN primeiro!")
            return

        if self.processing_active:
            QMessageBox.information(self.window, "Processamento", "Ja existe um processamento em andamento.")
            return

        self.blocks = None
        self.conversion_result = None
        self.set_html_text("")
        self.cancel_event.clear()
        self.processing_active = True
        self.cancel_button.setEnabled(True)
        self.progress_bar.setRange(0, 0)
        self.status_lbl.setText("Processando...")
        diagram_style = self.get_selected_diagram_style()
        engine_options = self.get_engine_options()
        self.save_user_settings()

        threading.Thread(
            target=self.backend.processar_pgn_worker,
            args=(
                texto,
                self.queue,
                self.pgn_dir,
                diagram_style,
                self.selected_game_indexes,
                self.get_selected_exercise_mode(),
                engine_options["engine_path"],
                engine_options["engine_depth"],
                engine_options["include_engine_analysis"],
                self.cancel_event,
            ),
            daemon=True,
        ).start()
        self.queue_timer.start(100)

    def cancelar_processamento(self):
        if not self.processing_active:
            return
        self.cancel_event.set()
        self.cancel_button.setEnabled(False)
        self.status_lbl.setText("Cancelando ao fim da etapa atual...")

    def check_queue(self):
        try:
            while True:
                msg_type, data = self.queue.get_nowait()
                if msg_type == "status":
                    self.status_lbl.setText(data)
                elif msg_type == "error":
                    self.queue_timer.stop()
                    self.processing_active = False
                    self.cancel_button.setEnabled(False)
                    self.progress_bar.setRange(0, 1)
                    self.progress_bar.setValue(0)
                    self.status_lbl.setText("Falha no processamento.")
                    QMessageBox.critical(self.window, "Erro no Processamento", data)
                    return
                elif msg_type == "done":
                    self.queue_timer.stop()
                    self.processing_active = False
                    self.cancel_button.setEnabled(False)
                    self.conversion_result = data
                    self.blocks = data.blocks
                    self.populate_game_navigation(data.summaries)
                    self.progress_bar.setRange(0, 1)
                    self.progress_bar.setValue(1)
                    warning_suffix = f" ({len(data.warnings)} aviso(s))" if data.warnings else ""
                    self.status_lbl.setText(
                        f"Pronto! {len(self.blocks)} partidas convertidas.{warning_suffix}"
                    )
                    css_text = self.get_current_css_text() if self.css_user_modified else None
                    full_html = self.backend.gerar_html_final(
                        self.blocks,
                        diagram_style=data.diagram_style,
                        css_text=css_text,
                        summaries=data.summaries,
                    )
                    self.set_html_text(full_html)
                    if data.warnings:
                        QMessageBox.warning(
                            self.window,
                            "Processamento concluido com avisos",
                            "\n".join(data.warnings[:10]),
                        )
                    else:
                        QMessageBox.information(self.window, "Sucesso", "Processamento concluido com sucesso!")
                    return
        except queue.Empty:
            return
        except Exception as exc:
            self.queue_timer.stop()
            self.processing_active = False
            self.cancel_button.setEnabled(False)
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            self.status_lbl.setText("Falha no processamento.")
            QMessageBox.critical(self.window, "Erro no Processamento", str(exc))

    def preview(self):
        if not self.txt_html.toPlainText().strip():
            QMessageBox.warning(self.window, "Aviso", "Processe o PGN primeiro.")
            return

        try:
            self.preview_dir = tempfile.mkdtemp(prefix="pgn_preview_")
            html_path = os.path.join(self.preview_dir, "preview.html")
            self.write_current_html_bundle(html_path)
            webbrowser.open("file://" + html_path)
        except Exception as exc:
            QMessageBox.critical(self.window, "Erro no Preview", str(exc))

    def salvar_html(self):
        if not self.txt_html.toPlainText().strip():
            QMessageBox.warning(self.window, "Aviso", "Processe o PGN primeiro.")
            return

        arq, _ = QFileDialog.getSaveFileName(
            self.window,
            "Salvar HTML",
            self.initial_file_path("livro.html"),
            "HTML (*.html)",
        )
        if not arq:
            return
        self.remember_file_dir(arq)
        try:
            self.write_current_html_bundle(arq)
            QMessageBox.information(self.window, "OK!", "HTML + CSS salvos com sucesso!")
        except Exception as exc:
            QMessageBox.critical(self.window, "Erro ao Salvar", str(exc))

    def salvar_epub(self):
        texto = self.txt_pgn.toPlainText().strip()
        if not texto:
            QMessageBox.warning(self.window, "Aviso", "Cole ou abra um arquivo PGN primeiro!")
            return
        arq, _ = QFileDialog.getSaveFileName(
            self.window,
            "Salvar EPUB",
            self.initial_file_path("livro.epub"),
            "EPUB (*.epub)",
        )
        if not arq:
            return
        self.remember_file_dir(arq)

        try:
            with tempfile.TemporaryDirectory(prefix="pgn_epub_") as temp_dir:
                engine_options = self.get_engine_options()
                result = self.backend.convert_pgn(
                    texto,
                    output_dir=temp_dir,
                    diagram_style=self.get_selected_diagram_style(),
                    selected_game_indexes=self.selected_game_indexes,
                    exercise_mode=self.get_selected_exercise_mode(),
                    **engine_options,
                )
                book = self.backend.epub.EpubBook()
                book.set_title("Livro de Xadrez - PGN")
                book.set_language("pt")

                style = self.backend.epub.EpubItem(
                    uid="style",
                    file_name="style/style.css",
                    media_type="text/css",
                    content=self.backend.ensure_diagram_font_css(
                        self.get_current_css_text(),
                        result.diagram_style,
                    ).encode(),
                )
                book.add_item(style)

                if self.backend.chess_diagrams.uses_merida_style(result.diagram_style):
                    support_files = self.backend.chess_diagrams.get_support_file_bytes(result.diagram_style)
                    for file_name, file_bytes in support_files.items():
                        book.add_item(
                            self.backend.epub.EpubItem(
                                uid=f"style_{os.path.splitext(file_name)[0]}",
                                file_name=f"style/Fonts/{file_name}",
                                media_type=self.backend.chess_diagrams.get_support_file_media_type(file_name),
                                content=file_bytes,
                            )
                        )

                chapters = []
                for index, content in enumerate(result.blocks, 1):
                    summary = result.summaries[index - 1] if index - 1 < len(result.summaries) else None
                    chapter_title = summary.title if summary else f"Partida {index}"
                    chapter = self.backend.epub.EpubHtml(title=chapter_title, file_name=f"p{index}.xhtml")
                    chapter.content = (
                        '<html><head><link rel="stylesheet" href="style/style.css"/>'
                        f"</head><body>{content}</body></html>"
                    ).encode()
                    book.add_item(chapter)
                    chapters.append(chapter)

                added_assets = set()
                for asset in result.diagram_assets:
                    for asset_path, media_type in ((asset.svg_path, "image/svg+xml"), (asset.png_path, "image/png")):
                        file_name = os.path.join("Diagrams", os.path.basename(asset_path)).replace("\\", "/")
                        if file_name in added_assets or not os.path.isfile(asset_path):
                            continue
                        added_assets.add(file_name)
                        with open(asset_path, "rb") as file_obj:
                            book.add_item(
                                self.backend.epub.EpubItem(
                                    uid=file_name,
                                    file_name=file_name,
                                    media_type=media_type,
                                    content=file_obj.read(),
                                )
                            )

                book.toc = chapters
                book.spine = ["nav"] + chapters
                book.add_item(self.backend.epub.EpubNcx())
                book.add_item(self.backend.epub.EpubNav())
                self.backend.epub.write_epub(arq, book)
                self.conversion_result = result
                self.blocks = result.blocks
            QMessageBox.information(self.window, "Sucesso", f"EPUB criado: {arq}")
        except Exception as exc:
            QMessageBox.critical(self.window, "Erro EPUB", str(exc))

    def salvar_docx(self):
        if not self.backend.HAS_DOCX:
            python_exe = sys.executable or "python"
            QMessageBox.critical(
                self.window,
                "DOCX indisponivel",
                "A exportacao DOCX exige o pacote 'python-docx' no mesmo Python que executa o programa.\n\n"
                f"Python em uso:\n{python_exe}\n\n"
                "Instale com:\n"
                f"\"{python_exe}\" -m pip install python-docx",
            )
            return

        texto = self.txt_pgn.toPlainText().strip()
        if not texto:
            QMessageBox.warning(self.window, "Aviso", "Cole ou abra um arquivo PGN primeiro!")
            return

        arq, _ = QFileDialog.getSaveFileName(
            self.window,
            "Salvar DOCX",
            self.initial_file_path("livro.docx"),
            "DOCX (*.docx)",
        )
        if not arq:
            return
        self.remember_file_dir(arq)
        try:
            engine_options = self.get_engine_options()
            result = self.backend.convert_pgn(
                texto,
                output_dir=os.path.dirname(arq),
                diagram_style=self.get_selected_diagram_style(),
                selected_game_indexes=self.selected_game_indexes,
                exercise_mode=self.get_selected_exercise_mode(),
                **engine_options,
            )
            self.backend.write_docx_file(arq, result)
            self.conversion_result = result
            self.blocks = result.blocks
            QMessageBox.information(self.window, "Sucesso", f"DOCX criado: {arq}")
        except Exception as exc:
            QMessageBox.critical(self.window, "Erro DOCX", str(exc))

    def salvar_pdf(self):
        texto = self.txt_pgn.toPlainText().strip()
        if not texto:
            QMessageBox.warning(self.window, "Aviso", "Cole ou abra um arquivo PGN primeiro!")
            return

        arq, _ = QFileDialog.getSaveFileName(
            self.window,
            "Salvar PDF",
            self.initial_file_path("livro.pdf"),
            "PDF (*.pdf)",
        )
        if not arq:
            return
        self.remember_file_dir(arq)
        try:
            with tempfile.TemporaryDirectory(prefix="pgn_pdf_source_") as temp_dir:
                engine_options = self.get_engine_options()
                result = self.backend.convert_pgn(
                    texto,
                    output_dir=temp_dir,
                    diagram_style=self.get_selected_diagram_style(),
                    selected_game_indexes=self.selected_game_indexes,
                    exercise_mode=self.get_selected_exercise_mode(),
                    **engine_options,
                )
                css_text = self.get_current_css_text() if self.css_user_modified else None
                self.backend.write_pdf_file(arq, result, css_text=css_text)
            QMessageBox.information(self.window, "Sucesso", f"PDF criado: {arq}")
        except Exception as exc:
            QMessageBox.critical(self.window, "Erro PDF", str(exc))

    def load_css_file(self):
        arq, _ = QFileDialog.getOpenFileName(
            self.window,
            "Carregar CSS",
            self.last_dir,
            "CSS (*.css);;Todos (*.*)",
        )
        if not arq:
            return
        self.remember_file_dir(arq)
        try:
            with open(arq, "r", encoding="utf-8", errors="ignore") as file_obj:
                css_text = file_obj.read()
            self.set_css_text(css_text)
            self.css_user_modified = True
            self.apply_css_changes()
            self.status_lbl.setText(f"CSS carregado: {os.path.basename(arq)}")
        except Exception as exc:
            QMessageBox.critical(self.window, "Erro CSS", str(exc))

    def save_css_file(self):
        css_text = self.get_current_css_text()
        if not css_text.strip():
            QMessageBox.warning(self.window, "Aviso", "Nao ha CSS para salvar.")
            return
        arq, _ = QFileDialog.getSaveFileName(
            self.window,
            "Salvar CSS",
            self.initial_file_path("style.css"),
            "CSS (*.css)",
        )
        if not arq:
            return
        self.remember_file_dir(arq)
        try:
            with open(arq, "w", encoding="utf-8") as file_obj:
                file_obj.write(css_text)
            self.status_lbl.setText(f"CSS salvo: {os.path.basename(arq)}")
        except Exception as exc:
            QMessageBox.critical(self.window, "Erro CSS", str(exc))

    def run(self):
        self.window.show()
        return self.qt_app.exec()
