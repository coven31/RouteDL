"""Иконка RouteDL: несколько маршрутов сходятся в одну стрелку загрузки.

`python routedl_icon.py` сохраняет routedl.ico и routedl.png рядом со скриптом (для ярлыка и README).
"""
import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen


def draw_icon(size=256):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256
    g = QLinearGradient(0, 0, 0, size)
    g.setColorAt(0, QColor("#1e88e5"))
    g.setColorAt(1, QColor("#0d47a1"))
    p.setBrush(g)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 52 * s, 52 * s)
    p.setPen(QPen(QColor("white"), 18 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    for a, b in [((66, 48), (128, 98)), ((190, 48), (128, 98)), ((128, 98), (128, 160)),
                 ((92, 126), (128, 162)), ((164, 126), (128, 162)),
                 ((64, 186), (64, 212)), ((64, 212), (192, 212)), ((192, 212), (192, 186))]:
        p.drawLine(QPointF(a[0] * s, a[1] * s), QPointF(b[0] * s, b[1] * s))
    p.end()
    return img


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    img = draw_icon(256)
    for name in ("routedl.ico", "routedl.png"):
        path = os.path.join(here, name)
        print(name, "OK" if img.save(path) else "ОШИБКА", os.path.getsize(path) if os.path.exists(path) else 0)
