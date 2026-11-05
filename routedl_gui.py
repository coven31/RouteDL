"""RouteDL GUI (S4.4): окно с очередью загрузок поверх консольного ядра routedl_cli.py.

Ядро запускается отдельными процессами, окно читает их вывод. Сначала `--info` узнаёт, что реально
доступно (качества, исходное аудио, плейлист, число файлов галереи), потом ссылка добавляется в очередь.
Очередь идёт строго по одной загрузке (порты и маршрут общие). Сведения о новой ссылке запрашиваются
параллельно с загрузкой, на сдвинутых портах (ROUTEDL_PORT_OFFSET), чтобы не мешать идущей загрузке.
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QToolButton, QVBoxLayout, QWidget)

from routedl_icon import draw_icon

BASE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(BASE, "routedl_cli.py")


def hide_console(a):
    """Дочерние процессы без мигающего окна консоли (CREATE_NO_WINDOW)."""
    try:
        a.flags |= 0x08000000
    except Exception:
        pass


def child_python():
    """Для дочерних процессов нужен консольный python.exe: у pythonw нет stdio."""
    cand = os.path.join(os.path.dirname(sys.executable), "python.exe")
    return cand if os.name == "nt" and os.path.exists(cand) else sys.executable


PY = child_python()
QUEUE = os.environ.get("ROUTEDL_QUEUE") or os.path.join(BASE, "queue.json")  # переменная нужна автотестам

BUCKETS = [(2160, "4K"), (1440, "2K"), (1080, "1080"), (720, "720"), (480, "480"), (360, "360"), (240, "240")]
CODEC_NAMES = {"mp4a": "AAC", "aac": "AAC", "opus": "Opus", "mp3": "MP3", "vorbis": "Vorbis",
               "flac": "FLAC", "alac": "ALAC", "ac-3": "AC3", "ec-3": "E-AC3"}
INFO_PREFIX = "[RouteDL-INFO] "
INFO_PORT_OFFSET = "300"  # запрос сведений живёт на портах +300 от рабочих
ROUTE_RE = re.compile(r"\[RouteDL[^\]]*\]\s*маршрут:\s*(.+?)\s*$")
PERCENT_RE = re.compile(r"^\[download\]\s+(\d+(?:\.\d+)?)%")
ITEM_RE = re.compile(r"^\[download\]\s+Downloading item (\d+) of (\d+)")
FILE_RE = re.compile(r"^[A-Za-z]:\\")
BADGES = [
    ("напрямую", "Напрямую", "#2e7d32"),
    ("локальный DPI", "Обход DPI", "#1565c0"),
    ("через узлы", "Резервные узлы", "#ef6c00"),
]
MARK = {"wait": "⏳", "run": "▶", "ok": "✔", "fail": "✖", "cancel": "■"}
GREY = "#555555"
HINT_COLOR = "#ffa726"
GREEN_BAR = ("QProgressBar {border:1px solid #444; border-radius:3px; text-align:center; background:#1e1e1e;}"
             "QProgressBar::chunk {background:#2e7d32;}")
NODES_WARNING = ("Резервные узлы это публичные анонимные серверы.\n\n"
                 "Через них не передаются логины и cookies, но не вводите там пароли и личные данные.\n\n"
                 "Повторить загрузку через них один раз?")


EXPLAIN = [
    (r"not a bot|Sign in to confirm you", "Сайт просит подтвердить, что вы не бот. Подождите несколько минут или смените сеть: вход в аккаунт RouteDL не поддерживает."),
    (r"age.restricted|confirm your age", "Ролик с ограничением по возрасту: без входа в аккаунт его не скачать, а RouteDL логины и cookies не использует."),
    (r"Private video", "Приватное видео: доступно только владельцу или по приглашению."),
    (r"members.only|Join this channel", "Видео только для участников канала."),
    (r"Video unavailable|video is unavailable|has been removed|no longer available", "Видео удалено или недоступно."),
    (r"not available in your country|blocked it in your country|geo.restrict", "Видео недоступно в вашем регионе."),
    (r"HTTP Error 429|Too Many Requests", "Сайт ограничил частоту запросов (429): подождите и повторите."),
    (r"requested format is not available", "Выбранное качество недоступно: выберите «Авто»."),
    (r"Premieres in|live event will begin|is upcoming", "Трансляция или премьера ещё не началась."),
    (r"ffmpeg.{0,40}not found|ffmpeg is not installed", "Не найден ffmpeg: запустите install.bat."),
    (r"DRM", "Поток защищён DRM: скачать его нельзя."),
]


def explain(text):
    """Понятная причина сбоя по тексту ошибки yt-dlp (None, если не распознана)."""
    for pat, msg in EXPLAIN:
        if re.search(pat, text, re.I):
            return msg
    return None


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
        self.setWindowIcon(QIcon(QPixmap.fromImage(draw_icon(256))))
        self.resize(900, 760)
        self.dl = None            # процесс текущей загрузки
        self.cur = None           # задание, которое сейчас качается
        self.run = {}             # состояние текущей загрузки: gallery, total, done, item
        self.jobs = []            # очередь: {url, args, title, sub, gallery, total, state}
        self.retry_job = None     # задание, которое можно повторить через резервные узлы
        self.info = None          # процесс получения сведений
        self.info_data = None
        self.info_url = ""        # ссылка, для которой запрошены сведения
        self.info_for = ""        # ссылка запущенного запроса
        self.info_done_url = ""   # ссылка, по которой запрос завершён (успешно или нет)
        self.bufs = {}
        self.lines = []
        self.cancelled = False
        self.type_forced = False  # «Видео» заблокировано, т.к. у ссылки нет видеодорожки
        self.gallery = False      # текущая ссылка в поле это галерея изображений
        self.total = 0            # сколько файлов в галерее (0 = неизвестно)
        self.last_sub = ""        # video / audio / gallery: что открывать кнопкой «Открыть папку»
        self.last_clip = ""
        self.saved_q = None       # что записано в queue.json
        self.hold_until = 0.0     # до этого момента важное сообщение статуса не затирается прогрессом

        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)

        self.url = QLineEdit()
        self.url.setPlaceholderText("Вставьте ссылку на видео, аудио или галерею")
        self.url.returnPressed.connect(self.add_job)
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
        self.type_row = QWidget()
        row = QHBoxLayout(self.type_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Скачать как:"))
        self.type = QComboBox()
        self.type.addItems(["Видео", "Аудио"])
        self.type.currentIndexChanged.connect(self.on_type_changed)
        row.addWidget(self.type)
        row.addStretch(1)
        lay.addWidget(self.type_row)

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

        # аудио: формат выбирается сам (MP3, а если источник без потерь, то как в источнике)
        self.audio_panel = QWidget()
        ap = QVBoxLayout(self.audio_panel)
        ap.setContentsMargins(0, 0, 0, 0)
        self.audio_src = QLabel("")
        self.audio_src.setWordWrap(True)
        ap.addWidget(self.audio_src)
        self.audio_hint = QLabel("")
        self.audio_hint.setWordWrap(True)
        ap.addWidget(self.audio_hint)
        self.cover = QCheckBox("Встроить обложку (только MP3)")
        ap.addWidget(self.cover)
        lay.addWidget(self.audio_panel)
        self.audio_panel.setVisible(False)

        # кнопки
        btns = QHBoxLayout()
        self.go = QPushButton("Скачать")
        self.go.setToolTip("Скачать. Несколько ссылок встанут в очередь и пойдут по одной")
        self.go.clicked.connect(self.add_job)
        self.cancel = QPushButton("Отмена")
        self.cancel.setToolTip("Отменить текущую загрузку (очередь продолжится)")
        self.cancel.clicked.connect(self.stop)
        self.cancel.setEnabled(False)
        self.open_btn = QToolButton()
        self.open_btn.setText("Открыть папку")
        self.open_btn.setPopupMode(QToolButton.MenuButtonPopup)
        self.open_btn.clicked.connect(self.open_folder)
        menu = QMenu(self.open_btn)
        menu.addAction("Изменить папку загрузок…", self.choose_folder)
        self.open_btn.setMenu(menu)
        self.rep_btn = QPushButton("Отчёт")
        self.rep_btn.setToolTip("Скопировать анонимный отчёт о последних запусках (для issue)")
        self.rep_btn.clicked.connect(self.copy_report)
        self.nodes = QCheckBox("Резервные узлы (по умолчанию выключено)")
        self.nodes.setToolTip("Публичные анонимные узлы. Нужны, только если сайт отказывает по IP или стране.")
        btns.addWidget(self.go)
        btns.addWidget(self.cancel)
        btns.addWidget(self.open_btn)
        btns.addWidget(self.rep_btn)
        self.upd = None
        self.upd_btn = QPushButton("Обновить движки")
        self.upd_btn.setToolTip("Обновить yt-dlp и gallery-dl: сайты ломают их раз в 1-3 недели")
        self.upd_btn.clicked.connect(self.update_engines)
        btns.addWidget(self.upd_btn)
        self.st = None
        self.st_btn = QPushButton("Тест сети")
        self.st_btn.setToolTip("Проверить, какие сайты открываются напрямую и где помогает обход. Результат копируется в буфер")
        self.st_btn.clicked.connect(self.run_selftest)
        btns.addWidget(self.st_btn)
        btns.addSpacing(12)
        btns.addWidget(self.nodes)
        btns.addStretch(1)
        lay.addLayout(btns)

        self.retry = QPushButton("Повторить через резервные узлы…")
        self.retry.clicked.connect(self.retry_with_nodes)
        self.retry.setVisible(False)
        lay.addWidget(self.retry)
        self.resume = QPushButton("Продолжить восстановленную очередь")
        self.resume.clicked.connect(self.resume_queue)
        self.resume.setVisible(False)
        lay.addWidget(self.resume)

        # очередь
        self.q_box = QWidget()
        qv = QVBoxLayout(self.q_box)
        qv.setContentsMargins(0, 0, 0, 0)
        self.qlist = QListWidget()
        self.qlist.setMaximumHeight(110)
        qv.addWidget(self.qlist)
        qrow = QHBoxLayout()
        self.rm_btn = QPushButton("Убрать выбранное")
        self.rm_btn.setToolTip("Ожидающее убирается из очереди, текущая загрузка отменяется")
        self.rm_btn.clicked.connect(self.remove_selected)
        self.clear_btn = QPushButton("Очистить завершённые")
        self.clear_btn.clicked.connect(self.clear_done)
        qrow.addWidget(self.rm_btn)
        qrow.addWidget(self.clear_btn)
        qrow.addStretch(1)
        qv.addLayout(qrow)
        lay.addWidget(self.q_box)
        self.q_box.setVisible(False)

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

        self.update_audio_hint()
        self.clip = QGuiApplication.clipboard()
        self.clip.dataChanged.connect(self.on_clipboard)
        self.on_clipboard()
        self.check_env()
        self.load_queue()

    # ---------- оформление ----------
    def set_badge(self, text, color):
        self.badge.setText(f" {text} ")
        self.badge.setStyleSheet(
            f"background:{color}; color:white; border-radius:8px; padding:3px 8px; font-weight:bold;")

    def set_status(self, text, color=None, hold=False):
        if hold:
            self.hold_until = time.monotonic() + 4
        elif time.monotonic() < self.hold_until:
            return
        self.status.setText(text)
        self.status.setStyleSheet(f"color:{color};" if color else "")

    def append(self, line):
        self.log.appendPlainText(line)

    def update_go(self, *_):
        blocked = not self.pl_row.isHidden() and not self.pl_check.isChecked()
        self.go.setEnabled(not blocked)

    # ---------- полоса прогресса ----------
    def bar_plain(self):
        self.bar.setStyleSheet("")
        self.bar.setFormat("%p%")
        self.bar.setRange(0, 100)

    def bar_scale(self, n):
        """Зелёная шкала «выполнено / всего» (галерея)."""
        self.bar.setStyleSheet(GREEN_BAR)
        self.bar.setFormat("%v / %m")
        self.bar.setRange(0, max(n, 1))

    def bar_overall(self, i, n, frac):
        """Общий прогресс плейлиста: трек i из n, внутри трека доля frac."""
        self.bar.setStyleSheet(GREEN_BAR)
        self.bar.setFormat(f"трек {i} из {n}")
        self.bar.setRange(0, 1000)
        self.bar.setValue(int(((i - 1) + max(0.0, min(frac, 1.0))) / max(n, 1) * 1000))

    def bar_idle(self):
        """Полоса вне загрузки: у галереи с известным числом файлов зелёная шкала 0 / N."""
        if self.dl is not None:
            return  # полоса принадлежит идущей загрузке
        if self.gallery and self.total:
            self.bar_scale(self.total)
        else:
            self.bar_plain()
        self.bar.setValue(0)

    def finish_bar(self, full):
        r = self.run
        if r.get("gallery") and r.get("total"):
            self.bar_scale(max(r["total"], r["done"]))
            self.bar.setValue(self.bar.maximum() if full else r["done"])
        elif r.get("item"):
            i, n = r["item"]
            if full:
                self.bar_overall(n, n, 1.0)
                self.bar.setFormat(f"треков: {n} из {n}")
        else:
            self.bar_plain()
            self.bar.setValue(100 if full else 0)

    # ---------- очередь ----------
    def refresh_list(self):
        row = self.qlist.currentRow()
        self.qlist.clear()
        for j in self.jobs:
            t = f'{MARK[j["state"]]} {j["title"]}'
            if j["state"] == "run":
                if self.run.get("item"):
                    t += "  ·  трек {} из {}".format(*self.run["item"])
                elif self.run.get("gallery") and self.run.get("total"):
                    t += f'  ·  файлов {self.run["done"]} из {self.run["total"]}'
            self.qlist.addItem(t)
        if 0 <= row < len(self.jobs):
            self.qlist.setCurrentRow(row)
        self.q_box.setVisible(bool(self.jobs))
        self.save_queue()

    def save_queue(self):
        """Ожидающие и идущее задания пишутся в queue.json: после сбоя или закрытия очередь не теряется."""
        keys = ("url", "args", "title", "sub", "gallery", "total")
        items = [{k: j[k] for k in keys} for j in self.jobs if j["state"] in ("wait", "run")]
        if items == self.saved_q:
            return
        self.saved_q = items
        try:
            with open(QUEUE + ".tmp", "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=1)
            os.replace(QUEUE + ".tmp", QUEUE)
        except OSError:
            pass

    def load_queue(self):
        try:
            with open(QUEUE, encoding="utf-8") as f:
                data = json.load(f)
            for d in data:
                if isinstance(d, dict) and isinstance(d.get("args"), list) and len(d["args"]) >= 3:
                    d["args"][1] = CLI  # папка программы могла измениться
                    self.jobs.append({"url": str(d.get("url") or ""), "args": [str(x) for x in d["args"]],
                                      "title": str(d.get("title") or d.get("url") or ""),
                                      "sub": str(d.get("sub") or "video"), "gallery": bool(d.get("gallery")),
                                      "total": int(d.get("total") or 0), "state": "wait"})
        except (OSError, ValueError, TypeError):
            return
        if self.jobs:
            self.refresh_list()
            self.resume.setVisible(True)
            self.set_status(f"Восстановлена очередь: заданий {len(self.jobs)}. Продолжить или убрать лишнее.",
                            HINT_COLOR, hold=True)

    def resume_queue(self, *_):
        self.resume.setVisible(False)
        self.pump()

    def build_job(self):
        url = self.url.text().strip()
        if not valid_url(url):
            self.set_status("Вставьте ссылку, начинающуюся с http:// или https://", "#ef5350")
            return None
        if not os.path.exists(CLI):
            self.set_status(f"Не найден {CLI}", "#ef5350")
            return None
        args = ["-u", CLI, url]
        audio = not self.gallery and self.type.currentIndex() == 1
        if audio:
            fmt, _ = self.audio_choice()
            args += ["--audio", fmt]
            if self.cover.isChecked() and fmt == "mp3":
                args.append("--cover")
        elif not self.gallery:
            q = self.selected_quality()
            if q:
                args += ["--quality", str(q)]
        playlist = not self.pl_row.isHidden() and self.pl_check.isChecked()
        if playlist:
            args.append("--playlist")
        if self.nodes.isChecked():
            args.append("--nodes")
        title = (self.info_data or {}).get("title") or url
        if self.gallery:
            title = "Галерея" + (f" ({self.total} файлов)" if self.total else "") + ": " + url.split("//", 1)[-1][:60]
        if playlist:
            title += " (плейлист, " + ("аудио)" if audio else "видео)")
        elif audio:
            title += " (аудио)"
        return {"url": url, "args": args, "title": title, "state": "wait",
                "sub": "gallery" if self.gallery else "audio" if audio else "video",
                "gallery": self.gallery, "total": self.total}

    def add_job(self, *_):
        if not self.go.isEnabled():
            return
        url = self.url.text().strip()
        if valid_url(url) and url != self.info_done_url:
            self.want_add = True  # клик не теряется: задание добавится, когда придут сведения
            self.set_status("Получаю сведения о ссылке…", HINT_COLOR, hold=True)
            self.info_timer.start(0)
            return
        job = self.build_job()
        if job is None:
            return
        dup = next((k for k, j in enumerate(self.jobs)
                    if j["args"] == job["args"] and j["state"] in ("wait", "run")), None)
        if dup is not None:
            self.qlist.setCurrentRow(dup)
            self.set_status("Эта ссылка с такими же настройками уже в очереди (строка выделена)", HINT_COLOR, hold=True)
            return
        self.jobs.append(job)
        self.refresh_list()
        self.pump()

    def pump(self):
        """Запускает следующее ожидающее задание, если ничего не качается."""
        if self.dl is not None:
            return
        job = next((j for j in self.jobs if j["state"] == "wait"), None)
        if job is not None:
            self.launch(job)

    def launch(self, job):
        self.cur = job
        job["state"] = "run"
        self.resume.setVisible(False)
        self.last_sub = job["sub"]
        self.lines = []
        self.cancelled = False
        self.run = {"gallery": job["gallery"], "total": job["total"], "done": 0, "item": None}
        self.log.clear()
        self.set_badge("подбор маршрута", GREY)
        self.set_status("Загрузка…")
        if job["gallery"] and job["total"]:
            self.bar_scale(job["total"])
            self.bar.setValue(0)
        else:
            self.bar_plain()
            self.bar.setRange(0, 0)  # «занято», пока нет процентов
        self.cancel.setEnabled(True)
        self.dl = self.make_proc(job["args"])
        self.refresh_list()
        self.append("> routedl_cli.py " + " ".join(job["args"][2:]))
        self.dl.start(PY, job["args"])

    def stop(self):
        if self.dl is not None:
            self.cancelled = True
            self.set_status("Отмена…")
            self.kill_tree(self.dl)

    def remove_selected(self, *_):
        row = self.qlist.currentRow()
        if not 0 <= row < len(self.jobs):
            return
        if self.jobs[row]["state"] == "run":
            self.stop()
            return
        del self.jobs[row]
        self.refresh_list()

    def clear_done(self, *_):
        self.jobs = [j for j in self.jobs if j["state"] in ("wait", "run")]
        self.refresh_list()

    def retry_with_nodes(self):
        j = self.retry_job
        if j is None:
            return
        if QMessageBox.question(self, "Резервные узлы", NODES_WARNING) == QMessageBox.StandardButton.Yes:
            nj = dict(j, args=j["args"] + ["--nodes"], state="wait", title=j["title"] + " (через узлы)")
            self.retry.setVisible(False)
            self.retry_job = None
            self.jobs.append(nj)
            self.refresh_list()
            self.pump()

    # ---------- буфер обмена и ссылка ----------
    def on_clipboard(self):
        text = (self.clip.text() or "").strip()
        if not valid_url(text):
            return
        cur = self.url.text().strip()
        if not cur or cur == self.last_clip:
            self.url.setText(text)
        self.last_clip = text

    def on_url_changed(self, _text):
        self.want_add = False
        self.info_timer.start(800)

    # ---------- сведения о ссылке ----------
    def reset_info(self):
        self.info_data = None
        self.gallery = False
        self.total = 0
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
        self.type_row.setVisible(True)
        self.video_panel.setVisible(self.type.currentIndex() == 0)
        self.audio_panel.setVisible(self.type.currentIndex() == 1)
        self.audio_src.setText("")
        self.update_audio_hint()
        self.bar_idle()
        self.update_go()

    def set_type_enabled(self, video, audio):
        model = self.type.model()
        model.item(0).setEnabled(video)
        model.item(1).setEnabled(audio)

    def fetch_info(self):
        url = self.url.text().strip()
        if not valid_url(url):
            stale, self.info = self.info, None
            self.kill_tree(stale)
            self.info_url = self.info_done_url = ""
            self.reset_info()
            return
        if url == self.info_url:
            return
        stale, self.info = self.info, None
        self.kill_tree(stale)
        self.info_url = self.info_for = url
        self.info_done_url = ""
        self.reset_info()
        self.title_lbl.setText("Получаю информацию о ссылке…")
        args = ["-u", CLI, url, "--info"]
        if self.nodes.isChecked():
            args.append("--nodes")
        self.info = self.make_proc(args, info=True)
        self.info.start(PY, args)

    def apply_info(self, d):
        self.info_data = d
        self.info_done_url = self.info_for  # сведения получены: не ждём завершения процесса
        if d.get("tool") != "yt":
            self.gallery = True
            self.total = int(d.get("count") or 0)
            self.title_lbl.setText(f"Галерея изображений: {self.total} файлов" if self.total
                                   else "Галерея изображений: считаю файлы…")
            self.type_row.setVisible(False)
            self.video_panel.setVisible(False)
            self.audio_panel.setVisible(False)
            self.pl_row.setVisible(False)
            self.bar_idle()
            self.update_go()
            return
        self.type_row.setVisible(True)
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

    def audio_choice(self):
        """(значение для --audio, подпись): MP3 по умолчанию, если у источника есть lossless, то он."""
        codec = ((self.info_data or {}).get("audio") or {}).get("codec") or ""
        if codec == "alac":
            return "flac", "FLAC (без потерь)"
        if codec == "flac":
            return "best", "FLAC (без потерь, как в источнике)"
        if codec.startswith("pcm"):
            return "best", "WAV (без потерь, как в источнике)"
        return "mp3", "MP3"

    def update_audio_hint(self, *_):
        fmt, label = self.audio_choice()
        self.audio_hint.setText("Сохранится как: " + label)
        self.cover.setEnabled(fmt == "mp3")

    def on_type_changed(self, idx):
        if self.gallery:
            return
        self.video_panel.setVisible(idx == 0)
        self.audio_panel.setVisible(idx == 1)

    def selected_quality(self):
        for val, b in self.q_buttons.items():
            if b.isChecked():
                return val or None
        return None

    # ---------- процессы ----------
    def make_proc(self, args, info=False):
        p = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PATH", os.path.join(BASE, "bin") + os.pathsep + env.value("PATH"))
        if info:
            env.insert("ROUTEDL_PORT_OFFSET", INFO_PORT_OFFSET)
        p.setProcessEnvironment(env)
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.setWorkingDirectory(BASE)
        modifier = getattr(p, "setCreateProcessArgumentsModifier", None)
        if os.name == "nt" and modifier:
            modifier(hide_console)
        self.bufs[p] = ""
        p.readyReadStandardOutput.connect(lambda pr=p: self.on_output(pr))
        p.finished.connect(lambda code, _st, pr=p: self.on_finished(pr, code))
        p.errorOccurred.connect(lambda err, pr=p: self.on_error(pr, err))
        p.finished.connect(p.deleteLater)
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
        if m and kind == "dl":
            route = m.group(1)
            for key, label, color in BADGES:
                if route.startswith(key):
                    self.set_badge(label, color)
                    break
        r = self.run
        if kind == "dl" and r.get("gallery") and (FILE_RE.match(line) or line.startswith("# ")):
            r["done"] += 1  # скачанный файл или уже существующий («# путь»)
            if r["total"]:
                if r["done"] > self.bar.maximum():
                    self.bar.setMaximum(r["done"])
                self.bar.setValue(r["done"])
            self.set_status(f"Файлов: {r['done']}" + (f" из {r['total']}" if r["total"] else ""))
            self.refresh_list()
        if kind == "dl":
            im = ITEM_RE.match(line)
            if im:
                r["item"] = (int(im.group(1)), int(im.group(2)))
                self.bar_overall(r["item"][0], r["item"][1], 0.0)
                self.refresh_list()
        if kind == "dl":
            if line.startswith("[ExtractAudio] Destination"):
                self.set_status("Конвертация в MP3: у длинных записей занимает несколько минут…")
            elif line.startswith("[Merger]"):
                self.set_status("Склейка видео и звука…")
            elif "30-секундный фрагмент" in line:
                self.set_status("Внимание: сайт отдаёт только 30-секундный фрагмент (трек платный или закрытый)",
                                HINT_COLOR, hold=True)
        pm = PERCENT_RE.match(line) if kind == "dl" else None
        if pm:
            pct = float(pm.group(1))
            item = r.get("item")
            if item:
                self.bar_overall(item[0], item[1], pct / 100)
            else:
                if self.bar.maximum() == 0:
                    self.bar.setRange(0, 100)
                self.bar.setValue(int(pct))
            prefix = f"Трек {item[0]} из {item[1]} · " if item else ""
            self.set_status(prefix + line[len("[download]"):].strip())
            return  # строки прогресса не засоряют лог
        self.append(line)

    def on_error(self, p, err):
        if err == QProcess.FailedToStart and (p is self.dl or p is self.info):
            self.append(f"Не удалось запустить {PY}: {p.errorString()}")
            self.on_finished(p, 1)  # при FailedToStart сигнал finished не приходит: сбрасываем состояние сами

    def on_finished(self, p, code):
        kind = "dl" if p is self.dl else "info" if p is self.info else None
        rest = self.bufs.pop(p, "")
        if kind is None:
            return
        if rest.strip():
            self.handle_line(kind, rest)
        if kind == "info":
            self.info = None
            self.info_done_url = self.info_for
            QTimer.singleShot(0, self.after_info)
            if self.info_data is None:
                self.info_url = ""
                self.title_lbl.setText("")
                if self.dl is None:
                    self.set_status("Не удалось получить сведения: будут настройки по умолчанию", HINT_COLOR)
            elif self.gallery and not self.total:
                self.title_lbl.setText("Галерея изображений (число файлов узнать не удалось)")
            return
        text = "\n".join(self.lines)
        job, self.cur, self.dl = self.cur, None, None
        self.cancel.setEnabled(False)
        if self.cancelled:
            self.finish_bar(False)
            self.set_badge("отменено", GREY)
            self.set_status("Отменено")
            state = "cancel"
        elif code == 0:
            self.finish_bar(True)
            self.set_status("Готово: файлы в папке загрузок", "#66bb6a")
            state = "ok"
        else:
            state = "fail"
            self.finish_bar(False)
            if "резервные узлы выключены" in text:
                self.set_status("Сайт отказал по IP или стране. Можно попробовать резервные узлы.", HINT_COLOR)
                self.retry_job = job
                self.retry.setText("Повторить через резервные узлы: " + (job["title"][:50] if job else ""))
                self.retry.setVisible(True)
            elif code == 5:
                self.set_status("Не хватает места на диске: освободите место и повторите", "#ef5350")
            elif code == 3:
                self.set_status("Нет интернета или не работает сеть: проверьте подключение", "#ef5350")
            elif code == 2 and "ни один движок" in text:
                self.set_status("Эта ссылка не поддерживается", "#ef5350")
            elif "stalled" in text and "нет прогресса" in text:
                self.set_status("Нет прогресса, загрузка прервана", "#ef5350")
            elif explain(text):
                self.set_status(explain(text) + " Подробности в логе.", "#ef5350")
            else:
                self.set_status(f"Ошибка (код {code}), подробности в логе", "#ef5350")
        if job is not None:
            job["state"] = state
        self.refresh_list()
        self.update_go()
        self.pump()

    # ---------- папка, отчёт, окружение ----------
    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Папка загрузок", downloads_dir())
        if not d:
            return
        path = os.path.join(BASE, "routedl.json")
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = {}
        if not isinstance(cfg, dict):
            cfg = {}
        cfg["downloads"] = os.path.normpath(d)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
        self.set_status("Папка загрузок: " + cfg["downloads"])

    def copy_report(self):
        r = subprocess.run([PY, CLI, "--report", "--redact"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=BASE,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                           env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1"))
        QGuiApplication.clipboard().setText(r.stdout.strip() or "отчёт пуст")
        self.set_status("Отчёт скопирован в буфер обмена: вставьте его в issue")

    def update_engines(self):
        if self.dl is not None or self.upd is not None:
            self.set_status("Идёт загрузка или обновление: подождите", HINT_COLOR, hold=True)
            return
        p = self.upd = QProcess(self)
        p.setProcessChannelMode(QProcess.MergedChannels)
        modifier = getattr(p, "setCreateProcessArgumentsModifier", None)
        if os.name == "nt" and modifier:
            modifier(hide_console)
        p.finished.connect(lambda code, _s: self.engines_done(code))
        p.errorOccurred.connect(lambda e: self.engines_done(1) if e == QProcess.FailedToStart else None)
        p.finished.connect(p.deleteLater)
        self.upd_btn.setEnabled(False)
        self.set_status("Обновляю yt-dlp и gallery-dl…")
        p.start(PY, ["-m", "pip", "install", "-U", "yt-dlp[default]", "yt-dlp-ejs", "gallery-dl"])

    def engines_done(self, code):
        self.upd = None
        self.upd_btn.setEnabled(True)
        try:
            from importlib.metadata import version
            v = f"yt-dlp {version('yt-dlp')}, gallery-dl {version('gallery-dl')}"
        except Exception:
            v = ""
        msg = ("Движки обновлены: " + v) if code == 0 else "Не удалось обновить движки (сеть или pip)"
        self.append(msg)
        self.set_status(msg, "#66bb6a" if code == 0 else "#ef5350", hold=True)

    def run_selftest(self):
        if self.dl is not None or self.st is not None:
            self.set_status("Идёт загрузка или проверка: подождите", HINT_COLOR, hold=True)
            return
        p = self.st = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")
        p.setProcessEnvironment(env)
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.setWorkingDirectory(BASE)
        modifier = getattr(p, "setCreateProcessArgumentsModifier", None)
        if os.name == "nt" and modifier:
            modifier(hide_console)
        p.finished.connect(lambda code, _s, pr=p: self.selftest_done(pr))
        p.errorOccurred.connect(lambda e, pr=p: self.selftest_done(pr) if e == QProcess.FailedToStart else None)
        p.finished.connect(p.deleteLater)
        self.log.clear()
        self.st_btn.setEnabled(False)
        self.set_status("Проверяю сеть: до минуты…")
        p.start(PY, ["-u", CLI, "--selftest"])

    def selftest_done(self, p):
        if p is not self.st:
            return
        self.st = None
        self.st_btn.setEnabled(True)
        out = bytes(p.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
        if not out:
            self.set_status("Не удалось выполнить проверку сети", "#ef5350", hold=True)
            return
        self.append(out)
        QGuiApplication.clipboard().setText(out)
        self.set_status("Результат скопирован в буфер обмена: вставьте его в issue", "#66bb6a", hold=True)

    def after_info(self):
        if getattr(self, "want_add", False):
            self.want_add = False
            if self.info_done_url == self.url.text().strip():
                self.add_job()

    def check_env(self):
        miss = [n for n in ("ffmpeg.exe", "ffprobe.exe", "ciadpi.exe")
                if not os.path.exists(os.path.join(BASE, "bin", n))]
        notes = []
        if miss:
            notes.append("нет в bin: " + ", ".join(miss))
        if not (shutil.which("deno") or os.path.exists(os.path.join(BASE, "bin", "deno.exe"))):
            notes.append("не найден Deno (нужен для YouTube)")
        if notes:
            self.set_status("Внимание: " + "; ".join(notes), HINT_COLOR)

    def open_folder(self):
        base = downloads_dir()
        d = os.path.join(base, self.last_sub) if self.last_sub else base
        if not os.path.isdir(d):
            d = base
        os.makedirs(d, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def closeEvent(self, event):
        self.info_timer.stop()
        self.kill_tree(self.info)
        self.kill_tree(self.dl)
        self.kill_tree(self.st)
        event.accept()


def main():
    if os.name == "nt":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RouteDL.App")  # иконка в панели задач
    app = QApplication(sys.argv)
    apply_dark(app)
    w = Window()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
