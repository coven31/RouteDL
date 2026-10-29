"""RouteDL GUI (S4.2): окно поверх консольного ядра routedl_cli.py.

Ядро запускается отдельными процессами, окно читает их вывод. Сначала `--info` узнаёт,
что реально доступно у ролика (качества, исходное аудио, плейлист), потом идёт загрузка.
"""
import json
import math
import os
import re
import subprocess
import sys

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)

BASE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(BASE, "routedl_cli.py")

BUCKETS = [(2160, "4K"), (1440, "2K"), (1080, "1080"), (720, "720"), (480, "480"), (360, "360"), (240, "240")]
AUDIO_FORMATS = [
    ("MP3 (для плееров и техники)", "mp3"),
    ("Оригинал (без перекодирования)", "best"),
    ("FLAC", "flac"),
    ("WAV", "wav"),
]
CODEC_NAMES = {"mp4a": "AAC", "aac": "AAC", "opus": "Opus", "mp3": "MP3", "vorbis": "Vorbis",
               "flac": "FLAC", "alac": "ALAC", "ac-3": "AC3", "ec-3": "E-AC3"}
INFO_PREFIX = "[RouteDL-INFO] "
ROUTE_RE = re.compile(r"\[RouteDL[^\]]*\]\s*маршрут:\s*(.+?)\s*$")
PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)%")
BADGES = [
    ("напрямую", "Напрямую", "#2e7d32"),
    ("локальный DPI", "Обход DPI", "#1565c0"),
    ("через узлы", "Резервные узлы", "#ef6c00"),
]
GREY = "#555555"
HINT_COLOR = "#ffa726"
NODES_WARNING = ("Резервные узлы это публичные анонимные серверы.\n\n"
                 "Через них не передаются логины и cookies, но не вводите там пароли и личные данные.\n\n"
                 "Повторить загрузку через них один раз?")


def nearest_bucket(h):
    return min(BUCKETS, key=lambda b: abs(math.log(h / b[0])))[0]


def fmt_duration(sec):
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return ""
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def valid_url(text):
    t = (text or "").strip().lower()
    return t.startswith(("http://", "https://")) and "\n" not in t


def downloads_dir():
    try:
        with open(os.path.join(BASE, "routedl.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        if isinstance(cfg, dict) and cfg.get("downloads"):
            return cfg["downloads"]
    except (OSError, ValueError):
        pass
    return os.path.join(BASE, "downloads")


def apply_dark(app):
    app.setStyle("Fusion")
    p = QPalette()
    p.setColor(QPalette.Window, QColor(37, 37, 38))
    p.setColor(QPalette.WindowText, QColor(230, 230, 230))
    p.setColor(QPalette.Base, QColor(30, 30, 30))
    p.setColor(QPalette.AlternateBase, QColor(45, 45, 48))
    p.setColor(QPalette.Text, QColor(230, 230, 230))
    p.setColor(QPalette.Button, QColor(55, 55, 60))
    p.setColor(QPalette.ButtonText, QColor(230, 230, 230))
    p.setColor(QPalette.Highlight, QColor(21, 101, 192))
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.PlaceholderText, QColor(140, 140, 140))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(120, 120, 120))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(105, 105, 105))
    app.setPalette(p)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RouteDL")
        self.resize(900, 700)
        self.dl = None          # процесс загрузки
        self.info = None        # процесс получения сведений
        self.info_data = None
        self.info_url = ""
        self.bufs = {}
        self.lines = []
        self.cancelled = False
        self.type_forced = False  # «Видео» заблокировано, т.к. у ссылки нет видеодорожки
        self.last_clip = ""

        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)

        self.url = QLineEdit()
        self.url.setPlaceholderText("Вставьте ссылку на видео, аудио или галерею")
        self.url.returnPressed.connect(self.start)
        self.url.textChanged.connect(self.on_url_changed)
        lay.addWidget(self.url)

        self.title_lbl = QLabel("")
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setStyleSheet("font-weight:bold;")
        lay.addWidget(self.title_lbl)

        # плейлист
        self.pl_row = QWidget()
        pl = QHBoxLayout(self.pl_row)
        pl.setContentsMargins(0, 0, 0, 0)
        self.pl_label = QLabel("")
        self.pl_label.setStyleSheet(f"color:{HINT_COLOR};")
        self.pl_check = QCheckBox("Скачать весь плейлист")
        self.pl_check.toggled.connect(self.update_go)
        pl.addWidget(self.pl_label, 1)
        pl.addWidget(self.pl_check)
        lay.addWidget(self.pl_row)
        self.pl_row.setVisible(False)

        # тип
        row = QHBoxLayout()
        row.addWidget(QLabel("Скачать как:"))
        self.type = QComboBox()
        self.type.addItems(["Видео", "Аудио"])
        self.type.currentIndexChanged.connect(self.on_type_changed)
        row.addWidget(self.type)
        row.addStretch(1)
        lay.addLayout(row)

        # видео: качества
        self.video_panel = QWidget()
        vp = QHBoxLayout(self.video_panel)
        vp.setContentsMargins(0, 0, 0, 0)
        vp.addWidget(QLabel("Качество:"))
        self.q_group = QButtonGroup(self)
        self.q_group.setExclusive(True)
        self.q_buttons = {}
        auto = QPushButton("Авто")
        auto.setToolTip("Лучшее до 1080p")
        self.q_buttons[0] = auto
        for val, label in BUCKETS:
            b = QPushButton(label)
            b.setEnabled(False)
            self.q_buttons[val] = b
        for b in self.q_buttons.values():
            b.setCheckable(True)
            b.setStyleSheet("QPushButton:checked {background:#1565c0; color:white; font-weight:bold;}")
            self.q_group.addButton(b)
            vp.addWidget(b)
        auto.setChecked(True)
        vp.addStretch(1)
        lay.addWidget(self.video_panel)

        # аудио: формат
        self.audio_panel = QWidget()
        ap = QVBoxLayout(self.audio_panel)
        ap.setContentsMargins(0, 0, 0, 0)
        arow = QHBoxLayout()
        arow.addWidget(QLabel("Формат:"))
        self.audio_fmt = QComboBox()
        for name, _ in AUDIO_FORMATS:
            self.audio_fmt.addItem(name)
        self.audio_fmt.currentIndexChanged.connect(self.update_audio_hint)
        self.cover = QCheckBox("Встроить обложку (MP3)")
        arow.addWidget(self.audio_fmt)
        arow.addWidget(self.cover)
        arow.addStretch(1)
        ap.addLayout(arow)
        self.audio_src = QLabel("")
        self.audio_src.setWordWrap(True)
        ap.addWidget(self.audio_src)
        self.audio_hint = QLabel("")
        self.audio_hint.setWordWrap(True)
        self.audio_hint.setStyleSheet(f"color:{HINT_COLOR};")
        ap.addWidget(self.audio_hint)
        lay.addWidget(self.audio_panel)
        self.audio_panel.setVisible(False)

        # кнопки
        btns = QHBoxLayout()
        self.go = QPushButton("Скачать")
        self.go.clicked.connect(self.start)
        self.cancel = QPushButton("Отмена")
        self.cancel.clicked.connect(self.stop)
        self.cancel.setEnabled(False)
        self.open_btn = QPushButton("Открыть папку")
        self.open_btn.clicked.connect(self.open_folder)
        self.nodes = QCheckBox("Резервные узлы (по умолчанию выключено)")
        self.nodes.setToolTip("Публичные анонимные узлы. Нужны, только если сайт отказывает по IP или стране.")
        btns.addWidget(self.go)
        btns.addWidget(self.cancel)
        btns.addWidget(self.open_btn)
        btns.addSpacing(12)
        btns.addWidget(self.nodes)
        btns.addStretch(1)
        lay.addLayout(btns)

        self.retry = QPushButton("Повторить через резервные узлы…")
        self.retry.clicked.connect(self.retry_with_nodes)
        self.retry.setVisible(False)
        lay.addWidget(self.retry)

        info = QHBoxLayout()
        self.badge = QLabel()
        self.set_badge("маршрут не выбран", GREY)
        self.status = QLabel("Готов к работе")
        self.status.setWordWrap(True)
        info.addWidget(self.badge)
        info.addWidget(self.status, 1)
        lay.addLayout(info)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        lay.addWidget(self.bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        self.log.setFont(mono)
        lay.addWidget(self.log, 1)

        self.info_timer = QTimer(self)
        self.info_timer.setSingleShot(True)
        self.info_timer.timeout.connect(self.fetch_info)

        self.clip = QGuiApplication.clipboard()
        self.clip.dataChanged.connect(self.on_clipboard)
        self.on_clipboard()

    # ---------- оформление ----------
    def set_badge(self, text, color):
        self.badge.setText(f" {text} ")
        self.badge.setStyleSheet(
            f"background:{color}; color:white; border-radius:8px; padding:3px 8px; font-weight:bold;")

    def set_status(self, text, color=None):
        self.status.setText(text)
        self.status.setStyleSheet(f"color:{color};" if color else "")

    def append(self, line):
        self.log.appendPlainText(line)

    def update_go(self):
        blocked = not self.pl_row.isHidden() and not self.pl_check.isChecked()
        self.go.setEnabled(self.dl is None and not blocked)

    # ---------- буфер обмена и ссылка ----------
    def on_clipboard(self):
        text = (self.clip.text() or "").strip()
        if not valid_url(text):
            return
        if self.dl is None and (not self.url.text().strip() or self.url.text().strip() == self.last_clip):
            self.url.setText(text)
        self.last_clip = text

    def on_url_changed(self, _text):
        if self.dl is None:
            self.info_timer.start(800)

    # ---------- сведения о ролике ----------
    def reset_info(self):
        self.info_data = None
        self.title_lbl.setText("")
        self.pl_row.setVisible(False)
        self.pl_check.setChecked(False)
        for val, b in self.q_buttons.items():
            if val:
                b.setEnabled(False)
        self.q_buttons[0].setChecked(True)
        self.set_type_enabled(True, True)
        if self.type_forced:
            self.type_forced = False
            self.type.setCurrentIndex(0)
        self.video_panel.setVisible(self.type.currentIndex() == 0)
        self.audio_panel.setVisible(self.type.currentIndex() == 1)
        self.audio_src.setText("")
        self.update_audio_hint()
        self.update_go()

    def set_type_enabled(self, video, audio):
        model = self.type.model()
        model.item(0).setEnabled(video)
        model.item(1).setEnabled(audio)

    def fetch_info(self):
        url = self.url.text().strip()
        if self.dl is not None:
            return
        if not valid_url(url):
            stale, self.info = self.info, None
            self.kill_tree(stale)
            self.info_url = ""
            self.reset_info()
            return
        if url == self.info_url:
            return
        stale, self.info = self.info, None
        self.kill_tree(stale)
        self.info_url = url
        self.reset_info()
        self.title_lbl.setText("Получаю информацию о ролике…")
        args = ["-u", CLI, url, "--info"]
        if self.nodes.isChecked():
            args.append("--nodes")
        self.info = self.make_proc(args)
        self.info.start(sys.executable, args)

    def apply_info(self, d):
        self.info_data = d
        if d.get("tool") != "yt":
            self.title_lbl.setText("Галерея изображений: качество выбирать не нужно")
            self.set_type_enabled(False, False)
            self.video_panel.setVisible(False)
            self.audio_panel.setVisible(False)
            return
        self.video_panel.setVisible(self.type.currentIndex() == 0)
        self.audio_panel.setVisible(self.type.currentIndex() == 1)
        parts = [d.get("title") or "", d.get("uploader") or "", fmt_duration(d.get("duration"))]
        self.title_lbl.setText(" · ".join(p for p in parts if p))

        pl = d.get("playlist")
        if pl:
            self.pl_label.setText(f"Это плейлист: {pl.get('count', '?')} элементов. "
                                  f"Отметьте, если нужно скачать все.")
            self.pl_row.setVisible(True)
            self.update_go()
            return

        heights = d.get("heights") or []
        available = {nearest_bucket(h) for h in heights}
        for val, b in self.q_buttons.items():
            if val:
                b.setEnabled(val in available)
        if available:
            if 1080 in available:
                pick = 1080
            else:
                lower = [v for v in available if v < 1080]
                pick = max(lower) if lower else min(available)
            self.q_buttons[pick].setChecked(True)
        audio = d.get("audio")
        if audio:
            codec = CODEC_NAMES.get(audio.get("codec") or "", (audio.get("codec") or "?").upper())
            if (audio.get("codec") or "").startswith("pcm"):
                codec = "WAV"
            kbps = f" {audio['abr']} кбит/с" if audio.get("abr") else ""
            lossless = codec in ("FLAC", "ALAC", "WAV")
            self.audio_src.setText(f"Источник: {codec}{kbps}, {'без потерь' if lossless else 'сжатый (с потерями)'}")
        if not heights:
            if audio:
                self.type_forced = True
                self.type.setCurrentIndex(1)
                self.set_type_enabled(False, True)
            self.video_panel.setVisible(False)
            self.audio_panel.setVisible(True)
        self.update_audio_hint()
        self.update_go()

    def update_audio_hint(self, *_):
        fmt = AUDIO_FORMATS[self.audio_fmt.currentIndex()][1]
        audio = (self.info_data or {}).get("audio") or {}
        codec = audio.get("codec") or ""
        lossless = codec in ("flac", "alac") or codec.startswith("pcm")
        if not self.info_data or not audio:
            self.audio_hint.setText("")
        elif fmt in ("flac", "wav") and not lossless:
            self.audio_hint.setText("Источник уже сжат: FLAC или WAV не улучшат качество, файл станет в разы больше.")
        elif fmt == "mp3" and not lossless:
            self.audio_hint.setText("Источник уже сжат: перекодирование в MP3 сохранит качество не лучше источника.")
        elif fmt == "best":
            self.audio_hint.setText("Файл сохранится в исходном формате источника (без потерь на перекодировании).")
        else:
            self.audio_hint.setText("")

    def on_type_changed(self, idx):
        if self.info_data and self.info_data.get("tool") != "yt":
            return
        self.video_panel.setVisible(idx == 0)
        self.audio_panel.setVisible(idx == 1)

    def selected_quality(self):
        for val, b in self.q_buttons.items():
            if b.isChecked():
                return val or None
        return None

    # ---------- процессы ----------
    def make_proc(self, args):
        p = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONUNBUFFERED", "1")
        p.setProcessEnvironment(env)
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.setWorkingDirectory(BASE)
        self.bufs[p] = ""
        p.readyReadStandardOutput.connect(lambda pr=p: self.on_output(pr))
        p.finished.connect(lambda code, _st, pr=p: self.on_finished(pr, code))
        p.errorOccurred.connect(lambda err, pr=p: self.on_error(pr, err))
        return p

    def kill_tree(self, p):
        """Убивает процесс вместе с дочерними (yt-dlp, ciadpi, xray)."""
        if p is None or p.state() == QProcess.NotRunning:
            return
        pid = int(p.processId())
        if os.name == "nt" and pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            p.kill()

    def start(self, force_nodes=False):
        if self.dl is not None or not self.go.isEnabled():
            return
        url = self.url.text().strip()
        if not valid_url(url):
            self.set_status("Вставьте ссылку, начинающуюся с http:// или https://", "#ef5350")
            return
        if not os.path.exists(CLI):
            self.set_status(f"Не найден {CLI}", "#ef5350")
            return
        self.info_timer.stop()
        stale, self.info = self.info, None  # завершение устаревшего процесса окно проигнорирует
        self.kill_tree(stale)

        args = ["-u", CLI, url]
        if self.type.currentIndex() == 1:
            fmt = AUDIO_FORMATS[self.audio_fmt.currentIndex()][1]
            args += ["--audio", fmt]
            if self.cover.isChecked() and fmt == "mp3":
                args.append("--cover")
        else:
            q = self.selected_quality()
            if q:
                args += ["--quality", str(q)]
        if not self.pl_row.isHidden() and self.pl_check.isChecked():
            args.append("--playlist")
        if force_nodes is True or self.nodes.isChecked():
            args.append("--nodes")

        self.lines = []
        self.cancelled = False
        self.log.clear()
        self.retry.setVisible(False)
        self.set_badge("подбор маршрута", GREY)
        self.set_status("Загрузка…")
        self.bar.setRange(0, 0)  # «занято», пока нет процентов
        self.cancel.setEnabled(True)
        self.dl = self.make_proc(args)
        self.update_go()
        self.append("> routedl_cli.py " + " ".join(args[2:]))
        self.dl.start(sys.executable, args)

    def retry_with_nodes(self):
        answer = QMessageBox.question(self, "Резервные узлы", NODES_WARNING)
        if answer == QMessageBox.StandardButton.Yes:
            self.start(force_nodes=True)

    def stop(self):
        if self.dl is not None:
            self.cancelled = True
            self.set_status("Отмена…")
            self.kill_tree(self.dl)

    # ---------- вывод ядра ----------
    def on_output(self, p):
        kind = "dl" if p is self.dl else "info" if p is self.info else None
        data = bytes(p.readAllStandardOutput()).decode("utf-8", errors="replace")
        if kind is None:
            return
        buf = self.bufs.get(p, "") + data.replace("\r\n", "\n").replace("\r", "\n")
        *done, self.bufs[p] = buf.split("\n")
        for line in done:
            self.handle_line(kind, line)

    def handle_line(self, kind, line):
        if not line.strip():
            return
        if line.startswith(INFO_PREFIX):
            if kind == "info":
                try:
                    self.apply_info(json.loads(line[len(INFO_PREFIX):]))
                except ValueError:
                    pass
            return
        if kind == "dl":
            self.lines.append(line)
        m = ROUTE_RE.search(line)
        if m:
            route = m.group(1)
            for key, label, color in BADGES:
                if route.startswith(key):
                    self.set_badge(label, color)
                    break
        if kind == "dl" and line.startswith("[download]") and "%" in line:
            pm = PERCENT_RE.search(line)
            if pm:
                if self.bar.maximum() == 0:
                    self.bar.setRange(0, 100)
                self.bar.setValue(int(float(pm.group(1))))
                self.set_status(line[len("[download]"):].strip())
            return  # строки прогресса не засоряют лог
        self.append(line)

    def on_error(self, p, err):
        if err == QProcess.FailedToStart and (p is self.dl or p is self.info):
            self.append(f"Не удалось запустить Python: {sys.executable}")

    def on_finished(self, p, code):
        kind = "dl" if p is self.dl else "info" if p is self.info else None
        rest = self.bufs.pop(p, "")
        if kind is None:
            return
        if rest.strip():
            self.handle_line(kind, rest)
        if kind == "info":
            self.info = None
            if self.info_data is None:
                self.title_lbl.setText("")
                self.set_status("Не удалось получить список форматов: будет выбрано «Авто»", HINT_COLOR)
            return
        text = "\n".join(self.lines)
        self.dl = None
        self.cancel.setEnabled(False)
        self.bar.setRange(0, 100)
        if self.cancelled:
            self.bar.setValue(0)
            self.set_badge("отменено", GREY)
            self.set_status("Отменено")
        elif code == 0:
            self.bar.setValue(100)
            self.set_status("Готово: файлы в папке загрузок", "#66bb6a")
        else:
            self.bar.setValue(0)
            if "резервные узлы выключены" in text:
                self.set_status("Сайт отказал по IP или стране. Можно попробовать резервные узлы.", HINT_COLOR)
                self.retry.setVisible(True)
            elif "stalled" in text and "нет прогресса" in text:
                self.set_status("Нет прогресса, загрузка прервана", "#ef5350")
            else:
                self.set_status(f"Ошибка (код {code}), подробности в логе", "#ef5350")
        self.update_go()

    # ---------- папка ----------
    def open_folder(self):
        d = downloads_dir()
        os.makedirs(d, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def closeEvent(self, event):
        self.info_timer.stop()
        self.kill_tree(self.info)
        self.kill_tree(self.dl)
        event.accept()


def main():
    app = QApplication(sys.argv)
    apply_dark(app)
    w = Window()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
