def sub(path, pairs):
    raw = open(path, encoding="utf-8", newline="").read()
    crlf = "\r\n" in raw
    s = raw.replace("\r\n", "\n")
    for old, new in pairs:
        assert s.count(old) == 1, f"{path}: якорь не найден: {old[:60]!r}"
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8", newline="").write(s.replace("\n", "\r\n") if crlf else s)
    print("OK", path, len(pairs))


sub("routedl_cli.py", [
('DISK_RE = re.compile(r"Errno 28|No space left", re.I)\n',
 'DISK_RE = re.compile(r"Errno 28|No space left", re.I)\n'
 '# ошибки самого ролика: смена маршрута не поможет, а повтор только тратит время и портит кэш маршрутов\n'
 'PERM_RE = re.compile(r"Video unavailable|video is unavailable|has been removed|no longer available|Private video|"\n'
 '                     r"members.only|Join this channel|age.restricted|confirm your age|Premieres in|live event will begin", re.I)\n'),
("""        if HTTP_RE.search(errs):
            ctx["want_foreign"] = True
""", """        if PERM_RE.search(errs):
            ctx["perm"] = True
            log("ролик недоступен на самом сайте: смена маршрута не поможет")
            return rc, step, False
        if HTTP_RE.search(errs):
            ctx["want_foreign"] = True
"""),
("    if rc not in (0, 5) and start > 0:\n",
 '    if rc not in (0, 5) and start > 0 and not ctx.get("perm"):\n'),
])

sub("routedl_gui.py", [
("        btns.addWidget(self.upd_btn)\n", """        btns.addWidget(self.upd_btn)
        self.st = None
        self.st_btn = QPushButton("Тест сети")
        self.st_btn.setToolTip("Проверить, какие сайты открываются напрямую и где помогает обход. Результат копируется в буфер")
        self.st_btn.clicked.connect(self.run_selftest)
        btns.addWidget(self.st_btn)
"""),
("    def after_info(self):\n", '''    def run_selftest(self):
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
'''),
("        self.kill_tree(self.dl)\n        event.accept()\n",
 "        self.kill_tree(self.dl)\n        self.kill_tree(self.st)\n        event.accept()\n"),
])
