"""Selection list of the available Sound xR OSC addresses."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QLineEdit,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from ..catalog import Catalog, Target

ID_ROLE = Qt.UserRole + 1


class TargetPickerDialog(QDialog):
    def __init__(self, catalog: Catalog, current: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sound xR OSC addresses")
        self.resize(760, 520)
        self.catalog = catalog
        self.selected: str | None = current

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter… (name, address, group)")
        self.search.textChanged.connect(self._populate)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Parameter", "Address template", "Arguments"])
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 320)
        self.tree.itemSelectionChanged.connect(self._on_select)
        self.tree.itemDoubleClicked.connect(lambda *_: self.accept())

        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color: palette(mid);")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.detail)
        layout.addWidget(buttons)

        self._populate()

    def _populate(self) -> None:
        text = self.search.text()
        matches = {t.id for t in self.catalog.search(text)}
        self.tree.clear()
        for group, targets in self.catalog.groups().items():
            visible = [t for t in targets if t.id in matches]
            if not visible:
                continue
            head = QTreeWidgetItem([group, "", ""])
            head.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(head)
            for t in visible:
                args = ", ".join(f"{a.name}:{a.type}" for a in t.args)
                item = QTreeWidgetItem([t.display, t.address, args])
                item.setData(0, ID_ROLE, t.id)
                if not t.verified:
                    item.setToolTip(0, "Reconstructed from the spec summary — "
                                       "verify against your firmware.")
                head.addChild(item)
                if t.id == self.selected:
                    self.tree.setCurrentItem(item)
            head.setExpanded(True)

    def _on_select(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        tid = item.data(0, ID_ROLE)
        if not tid:
            return
        self.selected = tid
        t: Target = self.catalog.get(tid)
        args = " | ".join(f"{a.name} ({a.type}) {a.describe_range()}" for a in t.args)
        proto = self.catalog.protocol_label(t.protocol)
        note = "" if t.verified else "  ⚠ unverified entry"
        self.detail.setText(f"{proto} · {t.address}\n{args}{note}")

    def result_target(self) -> str | None:
        return self.selected
