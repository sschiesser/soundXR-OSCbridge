"""Interactive transfer-curve view with editable breakpoints."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..mapping import Curve

HIT_RADIUS = 8.0


class CurveEditor(QWidget):
    """Draws the 0..1 -> 0..1 transfer function.

    In ``breakpoints`` mode points can be dragged, double-click adds one and
    right-click removes one.
    """

    curveChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._curve = Curve()
        self._drag: int | None = None
        self._live: float | None = None      # last normalised input, for the cursor
        self.setMinimumSize(220, 180)
        self.setMouseTracking(True)
        self.setToolTip("Breakpoint mode: click empty space to add a point, "
                        "drag to move it, right-click to remove.")

    # -- data ------------------------------------------------------------
    def curve(self) -> Curve:
        return self._curve

    def set_curve(self, curve: Curve) -> None:
        self._curve = curve
        if curve.kind == "breakpoints" and len(curve.points) < 2:
            curve.points = [(0.0, 0.0), (0.35, 0.15), (1.0, 1.0)]
        self.update()

    def set_live_input(self, u: float | None) -> None:
        self._live = None if u is None else min(1.0, max(0.0, u))
        self.update()

    # -- geometry --------------------------------------------------------
    def _plot_rect(self) -> QRectF:
        m = 10.0
        return QRectF(m, m, max(10.0, self.width() - 2 * m),
                      max(10.0, self.height() - 2 * m))

    def _to_px(self, x: float, y: float) -> QPointF:
        r = self._plot_rect()
        return QPointF(r.left() + x * r.width(), r.bottom() - y * r.height())

    def _to_unit(self, p: QPointF) -> tuple[float, float]:
        r = self._plot_rect()
        x = (p.x() - r.left()) / r.width()
        y = (r.bottom() - p.y()) / r.height()
        return (min(1.0, max(0.0, x)), min(1.0, max(0.0, y)))

    # -- painting --------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self._plot_rect()

        p.fillRect(self.rect(), self.palette().base())
        p.setPen(QPen(QColor(140, 140, 140, 90), 1))
        for i in range(1, 4):
            x = r.left() + r.width() * i / 4.0
            y = r.top() + r.height() * i / 4.0
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        p.setPen(QPen(QColor(120, 120, 120), 1))
        p.drawRect(r)
        p.setPen(QPen(QColor(140, 140, 140, 120), 1, Qt.DashLine))
        p.drawLine(self._to_px(0, 0), self._to_px(1, 1))

        path = QPainterPath()
        samples = self._curve.sample(160)
        path.moveTo(self._to_px(*samples[0]))
        for x, y in samples[1:]:
            path.lineTo(self._to_px(x, y))
        p.setPen(QPen(QColor(0, 122, 204), 2))
        p.drawPath(path)

        if self._curve.kind == "breakpoints":
            p.setPen(QPen(QColor(0, 90, 160), 1))
            p.setBrush(QColor(255, 255, 255))
            for x, y in self._curve.normalised_points():
                p.drawEllipse(self._to_px(x, y), 4.0, 4.0)

        if self._live is not None:
            y = self._curve.apply(self._live)
            p.setPen(QPen(QColor(220, 90, 60), 1, Qt.DashLine))
            p.drawLine(self._to_px(self._live, 0), self._to_px(self._live, y))
            p.drawLine(self._to_px(0, y), self._to_px(self._live, y))
            p.setBrush(QColor(220, 90, 60))
            p.setPen(Qt.NoPen)
            p.drawEllipse(self._to_px(self._live, y), 3.5, 3.5)
        p.end()

    # -- interaction -----------------------------------------------------
    def _nearest_point(self, pos: QPointF) -> int | None:
        if self._curve.kind != "breakpoints":
            return None
        best, best_d = None, HIT_RADIUS
        for n, (x, y) in enumerate(self._curve.points):
            d = (self._to_px(x, y) - pos).manhattanLength()
            if d < best_d:
                best, best_d = n, d
        return best

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if self._curve.kind != "breakpoints":
            return
        idx = self._nearest_point(e.position())
        if e.button() == Qt.RightButton:
            if idx is not None and len(self._curve.points) > 2:
                self._curve.points.pop(idx)
                self.curveChanged.emit()
                self.update()
            return
        if idx is None:
            x, y = self._to_unit(e.position())
            self._curve.points.append((x, y))
            self._curve.points.sort()
            idx = self._curve.points.index((x, y))
            self.curveChanged.emit()
        self._drag = idx
        self.update()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag is None or self._curve.kind != "breakpoints":
            return
        x, y = self._to_unit(e.position())
        pts = self._curve.points
        moving = (x, y)
        pts[self._drag] = moving
        pts.sort()
        self._drag = pts.index(moving)
        self.curveChanged.emit()
        self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._drag = None

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        # The press that precedes every double click has already added the
        # point; adding another here would stack two on the same spot.
        e.accept()
