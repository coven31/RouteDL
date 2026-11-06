"""Проверка переводов: каждая русская строка, которую окно или ядро показывает пользователю, должна переводиться."""
import ast
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import routedl_i18n as i18n

CYR = re.compile("[А-Яа-яЁё]")
SINKS = {"setText", "set_status", "set_badge", "setToolTip", "TLabel", "TButton", "TCheck", "append", "addAction", "log"}


def render(n):
    """Все возможные значения выражения из литералов (None, если в нём есть что-то кроме литералов)."""
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return [n.value]
    if isinstance(n, ast.JoinedStr):
        outs = [""]
        for v in n.values:
            if isinstance(v, ast.Constant):
                part = [v.value]
            elif isinstance(v.value, ast.IfExp):  # f"{'a' if x else 'b'}": оба варианта
                a, b = render(v.value.body), render(v.value.orelse)
                part = a + b if a is not None and b is not None else ["0"]
            else:
                part = ["0"]
            outs = [a + b for a in outs for b in part]
        return outs
    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
        left, right = render(n.left), render(n.right)
        return None if left is None or right is None else [a + b for a in left for b in right]
    if isinstance(n, ast.IfExp):
        a, b = render(n.body), render(n.orelse)
        return None if a is None or b is None else a + b
    return None


def parse(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return ast.parse(f.read())


def sink_strings(tree, only=None):
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name == "append" and not (isinstance(f, ast.Attribute) and getattr(f.value, "id", "") == "self"):
            continue  # list.append не показывается пользователю
        if name in SINKS and (only is None or name in only):
            out += [s for s in (render(node.args[0]) or []) if CYR.search(s)]
    return out


def literal(tree, var):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == var for t in node.targets):
            return ast.literal_eval(node.value)
    return None


class I18n(unittest.TestCase):
    def setUp(self):
        i18n.set_lang("en")

    def tearDown(self):
        i18n.set_lang("ru")

    def test_basic(self):
        self.assertEqual(i18n.tr("Скачать"), "Download")
        self.assertEqual(i18n.tr(" Напрямую "), " Direct ")
        self.assertEqual(i18n.tr("Название видео"), "Название видео")  # чужой текст не трогается
        self.assertEqual(i18n.tr_line("[RouteDL +5с] маршрут: напрямую"), "[RouteDL +5s] route: direct")
        self.assertEqual(i18n.tr_title("Мой ролик (плейлист, аудио)"), "Мой ролик (playlist, audio)")
        self.assertEqual(i18n.tr("Видео удалено или недоступно. Подробности в логе."),
                         "The video was removed or is unavailable. See the log for details.")
        i18n.set_lang("ru")
        self.assertEqual(i18n.tr("Скачать"), "Скачать")

    def test_gui_strings(self):
        tree = parse("routedl_gui.py")
        bad = [s for s in sink_strings(tree) if CYR.search(i18n.tr_line(s))]
        self.assertEqual(sorted(set(bad)), [])

    def test_gui_tables(self):
        tree = parse("routedl_gui.py")
        texts = [m for _, m in literal(tree, "EXPLAIN")] + [b[1] for b in literal(tree, "BADGES")]
        bad = [s for s in texts if CYR.search(i18n.tr(s))]
        self.assertEqual(bad, [])

    def test_cli_log(self):
        tree = parse("routedl_cli.py")
        msgs = sink_strings(tree, only={"log"}) + ["маршрут: " + v for v in literal(tree, "LABEL").values()]
        msgs = [s for s in msgs if s != "маршрут: 0"]  # f"маршрут: {LABEL[step]}": значения проверены выше
        bad = [s for s in msgs if CYR.search(i18n.tr_line("[RouteDL +0с] " + s))]
        self.assertEqual(sorted(set(bad)), [])


if __name__ == "__main__":
    unittest.main()
