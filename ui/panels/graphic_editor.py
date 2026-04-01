# ui/panels/graphic_editor.py
# HBCE — Hybrid Controls Editor
# Program Editor (Graphic Editor) — Full Implementation V0.1.6-alpha
#
# Graphical FBD / node-based programming editor.
# Supports both Function Block Diagram (FBD) style (Metasys / Niagara)
# and a node-canvas approach compatible with TGP2 controller logic.
#
# Layout:
#   Left   — Block Palette (tree: categories + Ctrl+Space search popup)
#   Centre — FBD Canvas   (QGraphicsView: pan, zoom, wire drawing)
#   Right  — Properties   (selected-block parameter editor)
#
# Features:
#   - Drag blocks from palette onto canvas
#   - Click output port → drag → release on input port to wire
#   - Bezier wire rendering; wire z-value BELOW block z-value (GOTCHA-008)
#   - Block categories: Logic, Math, Compare, Control, Timer, I/O, Misc
#   - Per-block parameter editor in right panel
#   - Save program to SQLite (programs table)
#   - Load existing programs from DB
#   - Upload to device: diff preview → confirm → ProgramUploadThread (GOTCHA-013)
#   - Read from device: ProgramReadThread (GOTCHA-013)
#   - Undo / Redo stack (Ctrl+Z / Ctrl+Y)
#   - Multi-select (rubber-band), group move, delete key
#   - Ctrl+Space block-search popup
#   - JSON serialization: {blocks:[…], wires:[…]}
#   - Export program as JSON file
#   - Zoom: Ctrl+scroll, Ctrl+= / Ctrl+-, Fit All button
#   - Status bar: block count, wire count, selection info

from __future__ import annotations

import json
import os
import random
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import (
    QPointF, QRectF, Qt, QThread, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QCursor, QFont,
    QPainter, QPainterPath, QPen, QAction,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QFrame, QGraphicsEllipseItem, QGraphicsItem,
    QGraphicsPathItem, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QSplitter, QStatusBar, QTextEdit, QToolBar,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.logger import get_logger

logger = get_logger(__name__)

# ── Z-value constants (GOTCHA-008: wires BELOW blocks) ───────────────────────
Z_WIRE         = 0
Z_BLOCK        = 10
Z_PORT         = 15
Z_WIRE_PREVIEW = 5

# ── Canvas geometry ───────────────────────────────────────────────────────────
BLOCK_W      = 120
BLOCK_H_BASE = 60
PORT_RADIUS  = 6
PORT_SPACING = 22
HEADER_H     = 24

# ── Colors ────────────────────────────────────────────────────────────────────
COL_HDR = {
    "logic":   "#2A4A7F",
    "math":    "#2A6B3F",
    "compare": "#5A3A7F",
    "control": "#7F3A2A",
    "timer":   "#5A5A1A",
    "io":      "#1A5A5A",
    "misc":    "#404050",
}
COL_BODY     = "#1E2230"
COL_SEL      = "#F0A020"
COL_WIRE     = "#4FC3F7"
COL_WIRE_PRV = "#F0A020"
COL_PORT_IN  = "#66BB6A"
COL_PORT_OUT = "#EF5350"
COL_PORT_HOV = "#FFFFFF"
COL_TEXT     = "#E0E0E0"
COL_DIM      = "#909090"
COL_GRID     = "#1C1D2C"
COL_GRID_DOT = "#252535"

# ═══════════════════════════════════════════════════════════════════════════════
#  Block registry
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PortDef:
    name:  str
    label: str
    kind:  str   # "in" | "out"
    dtype: str   # "analog" | "binary" | "any"

@dataclass
class BlockDef:
    type_id:     str
    category:    str
    label:       str
    description: str
    inputs:      List[PortDef]
    outputs:     List[PortDef]
    params:      Dict = field(default_factory=dict)


def _i(name, label, dtype="any") -> PortDef:
    return PortDef(name, label, "in", dtype)

def _o(name, label, dtype="any") -> PortDef:
    return PortDef(name, label, "out", dtype)


BLOCK_REGISTRY: List[BlockDef] = [
    # Logic
    BlockDef("AND",  "logic","AND",  "All inputs TRUE → output TRUE",
             [_i("in1","IN1","binary"),_i("in2","IN2","binary")],[_o("out","OUT","binary")]),
    BlockDef("OR",   "logic","OR",   "Any input TRUE → output TRUE",
             [_i("in1","IN1","binary"),_i("in2","IN2","binary")],[_o("out","OUT","binary")]),
    BlockDef("NOT",  "logic","NOT",  "Invert binary input",
             [_i("in","IN","binary")],[_o("out","OUT","binary")]),
    BlockDef("NAND", "logic","NAND", "Logical NAND",
             [_i("in1","IN1","binary"),_i("in2","IN2","binary")],[_o("out","OUT","binary")]),
    BlockDef("NOR",  "logic","NOR",  "Logical NOR",
             [_i("in1","IN1","binary"),_i("in2","IN2","binary")],[_o("out","OUT","binary")]),
    BlockDef("XOR",  "logic","XOR",  "Logical exclusive OR",
             [_i("in1","IN1","binary"),_i("in2","IN2","binary")],[_o("out","OUT","binary")]),
    # Math
    BlockDef("ADD",  "math","ADD",  "IN1 + IN2",
             [_i("in1","IN1","analog"),_i("in2","IN2","analog")],[_o("out","OUT","analog")]),
    BlockDef("SUB",  "math","SUB",  "IN1 − IN2",
             [_i("in1","IN1","analog"),_i("in2","IN2","analog")],[_o("out","OUT","analog")]),
    BlockDef("MUL",  "math","MUL",  "IN1 × IN2",
             [_i("in1","IN1","analog"),_i("in2","IN2","analog")],[_o("out","OUT","analog")]),
    BlockDef("DIV",  "math","DIV",  "IN1 ÷ IN2",
             [_i("in1","IN1","analog"),_i("in2","IN2","analog")],[_o("out","OUT","analog")]),
    BlockDef("ABS",  "math","ABS",  "Absolute value",
             [_i("in","IN","analog")],[_o("out","OUT","analog")]),
    BlockDef("CLAMP","math","CLAMP","Clamp between Min and Max",
             [_i("in","IN","analog"),_i("mn","MIN","analog"),_i("mx","MAX","analog")],
             [_o("out","OUT","analog")],{"min":0.0,"max":100.0}),
    BlockDef("AVG",  "math","AVG",  "Moving average",
             [_i("in","IN","analog")],[_o("out","OUT","analog")],{"samples":10}),
    # Compare
    BlockDef("GT",  "compare","GT",  "IN1 > IN2",
             [_i("in1","IN1","analog"),_i("in2","IN2","analog")],[_o("out","OUT","binary")]),
    BlockDef("GE",  "compare","GE",  "IN1 >= IN2",
             [_i("in1","IN1","analog"),_i("in2","IN2","analog")],[_o("out","OUT","binary")]),
    BlockDef("LT",  "compare","LT",  "IN1 < IN2",
             [_i("in1","IN1","analog"),_i("in2","IN2","analog")],[_o("out","OUT","binary")]),
    BlockDef("LE",  "compare","LE",  "IN1 <= IN2",
             [_i("in1","IN1","analog"),_i("in2","IN2","analog")],[_o("out","OUT","binary")]),
    BlockDef("EQ",  "compare","EQ",  "IN1 = IN2",
             [_i("in1","IN1","analog"),_i("in2","IN2","analog")],[_o("out","OUT","binary")]),
    BlockDef("NEQ", "compare","NEQ", "IN1 != IN2",
             [_i("in1","IN1","analog"),_i("in2","IN2","analog")],[_o("out","OUT","binary")]),
    # Control
    BlockDef("PID","control","PID","PID controller",
             [_i("sp","SP","analog"),_i("pv","PV","analog"),_i("en","ENABLE","binary")],
             [_o("out","OUT","analog"),_o("err","ERR","analog")],
             {"Kp":1.0,"Ki":0.1,"Kd":0.0,"output_min":0.0,"output_max":100.0}),
    BlockDef("ONOFF","control","ON/OFF","Bang-bang controller with deadband",
             [_i("sp","SP","analog"),_i("pv","PV","analog")],
             [_o("out","OUT","binary")],{"deadband":1.0,"action":"heating"}),
    BlockDef("SETPT","control","SETPOINT","Setpoint override with limit clamp",
             [_i("in","IN","analog"),_i("ovr","OVR","binary")],
             [_o("out","OUT","analog")],
             {"override_val":0.0,"lo_limit":0.0,"hi_limit":100.0}),
    BlockDef("SEL","control","SELECT","Select IN1 or IN2 based on SEL",
             [_i("in1","IN1"),_i("in2","IN2"),_i("sel","SEL","binary")],
             [_o("out","OUT")]),
    # Timer
    BlockDef("TON","timer","TON","On-Delay timer",
             [_i("in","IN","binary"),_i("en","ENABLE","binary")],
             [_o("out","Q","binary"),_o("et","ET","analog")],{"delay_s":60}),
    BlockDef("TOF","timer","TOF","Off-Delay timer",
             [_i("in","IN","binary")],
             [_o("out","Q","binary"),_o("et","ET","analog")],{"delay_s":60}),
    BlockDef("PULSE","timer","PULSE","Pulse generator on rising edge",
             [_i("in","IN","binary")],[_o("out","Q","binary")],{"pulse_s":5}),
    BlockDef("CTU","timer","CTU","Count-Up counter",
             [_i("cu","CU","binary"),_i("rst","RESET","binary")],
             [_o("cv","CV","analog"),_o("q","Q","binary")],{"preset":10}),
    # I/O
    BlockDef("AI","io","Analog Input","BACnet AI object read",
             [],[_o("out","PV","analog")],{"object_instance":0,"label":"AI-1"}),
    BlockDef("AO","io","Analog Output","BACnet AO object write",
             [_i("in","CV","analog")],[],{"object_instance":0,"priority":8,"label":"AO-1"}),
    BlockDef("BI","io","Binary Input","BACnet BI object read",
             [],[_o("out","PV","binary")],{"object_instance":0,"label":"BI-1"}),
    BlockDef("BO","io","Binary Output","BACnet BO object write",
             [_i("in","CV","binary")],[],{"object_instance":0,"priority":8,"label":"BO-1"}),
    BlockDef("AV","io","Analog Variable","BACnet AV read/write",
             [_i("in","SET","analog")],[_o("out","GET","analog")],
             {"object_instance":0,"label":"AV-1"}),
    BlockDef("CONST","io","Constant","Fixed constant value",
             [],[_o("out","K","analog")],{"value":0.0}),
    # Misc
    BlockDef("COMMENT","misc","Comment","Text annotation — no logic",
             [],[],{"text":"Add note here…"}),
    BlockDef("JUNCTION","misc","Junction","Fan-out: 1 in → 3 out",
             [_i("in","IN")],
             [_o("out1","OUT1"),_o("out2","OUT2"),_o("out3","OUT3")]),
]

BLOCK_MAP: Dict[str, BlockDef] = {b.type_id: b for b in BLOCK_REGISTRY}

CAT_ORDER = ["logic","math","compare","control","timer","io","misc"]
CAT_LABELS = {
    "logic":   "⚡ Logic",
    "math":    "➕ Math",
    "compare": "⚖  Compare",
    "control": "🎛  Control",
    "timer":   "⏱  Timer",
    "io":      "📡  I/O",
    "misc":    "📝  Misc",
}

# ═══════════════════════════════════════════════════════════════════════════════
#  Data model
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class BlockData:
    block_id: str
    type_id:  str
    x:        float
    y:        float
    label:    str
    params:   Dict = field(default_factory=dict)

@dataclass
class WireData:
    wire_id:       str
    from_block_id: str
    from_port:     str
    to_block_id:   str
    to_port:       str

# ═══════════════════════════════════════════════════════════════════════════════
#  Graphics items
# ═══════════════════════════════════════════════════════════════════════════════

class PortItem(QGraphicsEllipseItem):
    """Small circle representing a port on a block."""

    def __init__(self, port_def: PortDef, parent_block: "BlockItem"):
        r = PORT_RADIUS
        super().__init__(-r, -r, 2*r, 2*r, parent=parent_block)
        self.port_def   = port_def
        self.block_item = parent_block
        self._hov = False
        self.setZValue(Z_PORT)
        self.setAcceptHoverEvents(True)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self._refresh()

    def _refresh(self):
        if self._hov:
            col = QColor(COL_PORT_HOV)
        elif self.port_def.kind == "out":
            col = QColor(COL_PORT_OUT)
        else:
            col = QColor(COL_PORT_IN)
        self.setBrush(QBrush(col))
        self.setPen(QPen(col.lighter(140), 1))

    def hoverEnterEvent(self, e):
        self._hov = True; self._refresh(); super().hoverEnterEvent(e)

    def hoverLeaveEvent(self, e):
        self._hov = False; self._refresh(); super().hoverLeaveEvent(e)

    def center_scene(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))


class BlockItem(QGraphicsItem):
    """Draggable FBD block."""

    def __init__(self, bd: BlockData, bdef: BlockDef):
        super().__init__()
        self.block_data = bd
        self.block_def  = bdef
        n = max(len(bdef.inputs), len(bdef.outputs), 1)
        self._w = BLOCK_W
        self._h = HEADER_H + n * PORT_SPACING + 8
        if bdef.type_id == "COMMENT":
            self._w, self._h = 160, 64
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setZValue(Z_BLOCK)
        self.setPos(bd.x, bd.y)
        self._ports: Dict[str, PortItem] = {}
        self._build_ports()

    def _build_ports(self):
        top = HEADER_H + 4
        for i, p in enumerate(self.block_def.inputs):
            it = PortItem(p, self)
            it.setPos(0, top + i * PORT_SPACING + PORT_SPACING // 2)
            self._ports[p.name] = it
        for i, p in enumerate(self.block_def.outputs):
            it = PortItem(p, self)
            it.setPos(self._w, top + i * PORT_SPACING + PORT_SPACING // 2)
            self._ports[p.name] = it

    def port_item(self, name: str) -> Optional[PortItem]:
        return self._ports.get(name)

    def boundingRect(self) -> QRectF:
        r = PORT_RADIUS
        return QRectF(-r, -r, self._w + 2*r, self._h + 2*r)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h   = self._w, self._h
        bdef   = self.block_def
        sel    = self.isSelected()

        # Shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 60)))
        painter.drawRoundedRect(QRectF(3, 3, w, h), 6, 6)

        # Body
        painter.setPen(QPen(QColor(COL_SEL if sel else "#3A3D50"), 2 if sel else 1))
        painter.setBrush(QBrush(QColor(COL_BODY)))
        painter.drawRoundedRect(QRectF(0, 0, w, h), 6, 6)

        if bdef.type_id == "COMMENT":
            painter.setPen(QPen(QColor("#C0B020")))
            f = QFont("Segoe UI", 8, QFont.Weight.Normal, True)
            painter.setFont(f)
            painter.drawText(QRectF(6, 4, w-12, h-8),
                             Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft |
                             Qt.TextFlag.TextWordWrap,
                             self.block_data.params.get("text",""))
            return

        # Header
        hcol = QColor(COL_HDR.get(bdef.category, "#333345"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(hcol))
        hp = QPainterPath()
        hp.addRoundedRect(QRectF(0, 0, w, HEADER_H), 6, 6)
        hp.addRect(QRectF(0, HEADER_H//2, w, HEADER_H//2))
        painter.drawPath(hp)

        painter.setPen(QPen(QColor(COL_TEXT)))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(QRectF(4, 0, w-8, HEADER_H),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         bdef.label)

        # User label
        ulbl = self.block_data.label
        if ulbl and ulbl != bdef.label:
            painter.setPen(QPen(QColor(COL_DIM)))
            painter.setFont(QFont("Segoe UI", 7))
            painter.drawText(QRectF(4, HEADER_H+2, w-8, PORT_SPACING-2),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             ulbl)

        # Port labels
        painter.setFont(QFont("Segoe UI", 7))
        top = HEADER_H + 4
        for i, p in enumerate(bdef.inputs):
            y = top + i * PORT_SPACING + PORT_SPACING//2
            painter.setPen(QPen(QColor(COL_DIM)))
            painter.drawText(QRectF(8, y-8, w//2-8, 16),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             p.label)
        for i, p in enumerate(bdef.outputs):
            y = top + i * PORT_SPACING + PORT_SPACING//2
            painter.setPen(QPen(QColor(COL_DIM)))
            painter.drawText(QRectF(w//2, y-8, w//2-8, 16),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                             p.label)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.block_data.x = self.x()
            self.block_data.y = self.y()
            if self.scene():
                self.scene().notify_block_moved(self)
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        if self.scene():
            self.scene().edit_block_req.emit(self)
        super().mouseDoubleClickEvent(event)


class WireItem(QGraphicsPathItem):
    """Bezier wire. Z below blocks — GOTCHA-008."""

    def __init__(self, fp: PortItem, tp: PortItem, wd: WireData):
        super().__init__()
        self.from_port = fp
        self.to_port   = tp
        self.wire_data = wd
        self.setZValue(Z_WIRE)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.refresh()

    def refresh(self):
        p1 = self.from_port.center_scene()
        p2 = self.to_port.center_scene()
        dx = abs(p2.x() - p1.x()) * 0.5
        path = QPainterPath(p1)
        path.cubicTo(QPointF(p1.x()+dx, p1.y()),
                     QPointF(p2.x()-dx, p2.y()), p2)
        self.setPath(path)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(COL_SEL if self.isSelected() else COL_WIRE)
        pen = QPen(col, 3 if self.isSelected() else 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPath(self.path())


class PreviewWire(QGraphicsPathItem):
    def __init__(self):
        super().__init__()
        pen = QPen(QColor(COL_WIRE_PRV), 2, Qt.PenStyle.DashLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(pen)
        self.setZValue(Z_WIRE_PREVIEW)

    def update_path(self, p1: QPointF, p2: QPointF):
        dx = abs(p2.x()-p1.x())*0.5
        path = QPainterPath(p1)
        path.cubicTo(QPointF(p1.x()+dx,p1.y()), QPointF(p2.x()-dx,p2.y()), p2)
        self.setPath(path)

# ═══════════════════════════════════════════════════════════════════════════════
#  FBD Scene
# ═══════════════════════════════════════════════════════════════════════════════

class FBDScene(QGraphicsScene):

    block_selected    = pyqtSignal(object)
    scene_changed_sig = pyqtSignal()
    edit_block_req    = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(-2000, -2000, 8000, 6000)
        self._blocks: Dict[str, BlockItem] = {}
        self._wires:  Dict[str, WireItem]  = {}
        self._prev_wire: Optional[PreviewWire] = None
        self._drag_port: Optional[PortItem]    = None
        self._dirty = False
        self.selectionChanged.connect(self._on_sel)

    # ── Blocks ────────────────────────────────────────────────────────────

    def add_block(self, bd: BlockData) -> BlockItem:
        bdef = BLOCK_MAP.get(bd.type_id)
        if not bdef:
            raise ValueError(f"Unknown block type: {bd.type_id}")
        item = BlockItem(bd, bdef)
        self.addItem(item)
        self._blocks[bd.block_id] = item
        self._dirty = True
        self.scene_changed_sig.emit()
        return item

    def remove_block(self, block_id: str):
        item = self._blocks.pop(block_id, None)
        if not item:
            return
        dead = [wid for wid, w in self._wires.items()
                if w.from_port.block_item is item or w.to_port.block_item is item]
        for wid in dead:
            self._remove_wire_internal(wid)
        self.removeItem(item)
        self._dirty = True
        self.scene_changed_sig.emit()

    # ── Wires ─────────────────────────────────────────────────────────────

    def add_wire(self, wd: WireData) -> Optional[WireItem]:
        fb = self._blocks.get(wd.from_block_id)
        tb = self._blocks.get(wd.to_block_id)
        if not fb or not tb:
            return None
        fp = fb.port_item(wd.from_port)
        tp = tb.port_item(wd.to_port)
        if not fp or not tp:
            return None
        # no duplicate wires to same input
        for w in self._wires.values():
            if w.to_port is tp:
                return None
        item = WireItem(fp, tp, wd)
        self.addItem(item)
        self._wires[wd.wire_id] = item
        self._dirty = True
        self.scene_changed_sig.emit()
        return item

    def _remove_wire_internal(self, wire_id: str):
        item = self._wires.pop(wire_id, None)
        if item:
            self.removeItem(item)

    def remove_wire(self, wire_id: str):
        self._remove_wire_internal(wire_id)
        self._dirty = True
        self.scene_changed_sig.emit()

    def notify_block_moved(self, bi: BlockItem):
        for w in self._wires.values():
            if w.from_port.block_item is bi or w.to_port.block_item is bi:
                w.refresh()

    # ── Mouse events ──────────────────────────────────────────────────────

    def _port_at(self, pos: QPointF) -> Optional[PortItem]:
        for it in self.items(pos):
            if isinstance(it, PortItem):
                return it
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            port = self._port_at(event.scenePos())
            if port and port.port_def.kind == "out":
                self._drag_port = port
                self._prev_wire = PreviewWire()
                self.addItem(self._prev_wire)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._prev_wire and self._drag_port:
            self._prev_wire.update_path(
                self._drag_port.center_scene(), event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._prev_wire and self._drag_port:
            if self._prev_wire.scene():
                self.removeItem(self._prev_wire)
            self._prev_wire = None
            tp = self._port_at(event.scenePos())
            if (tp and tp is not self._drag_port and
                    tp.port_def.kind == "in" and
                    tp.block_item is not self._drag_port.block_item):
                wd = WireData(
                    wire_id       = str(uuid.uuid4()),
                    from_block_id = self._drag_port.block_item.block_data.block_id,
                    from_port     = self._drag_port.port_def.name,
                    to_block_id   = tp.block_item.block_data.block_id,
                    to_port       = tp.port_def.name,
                )
                self.add_wire(wd)
            self._drag_port = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            self._delete_selected()
            return
        super().keyPressEvent(event)

    def _delete_selected(self):
        for it in list(self.selectedItems()):
            if isinstance(it, WireItem):
                self.remove_wire(it.wire_data.wire_id)
            elif isinstance(it, BlockItem):
                self.remove_block(it.block_data.block_id)

    def _on_sel(self):
        sel = [it for it in self.selectedItems() if isinstance(it, BlockItem)]
        self.block_selected.emit(sel[0] if len(sel) == 1 else None)

    # ── Serialization ─────────────────────────────────────────────────────

    def to_json(self) -> dict:
        return {
            "blocks": [
                {"block_id":b.block_data.block_id,"type_id":b.block_data.type_id,
                 "x":b.block_data.x,"y":b.block_data.y,
                 "label":b.block_data.label,"params":b.block_data.params}
                for b in self._blocks.values()
            ],
            "wires": [
                {"wire_id":w.wire_data.wire_id,
                 "from_block_id":w.wire_data.from_block_id,"from_port":w.wire_data.from_port,
                 "to_block_id":w.wire_data.to_block_id,"to_port":w.wire_data.to_port}
                for w in self._wires.values()
            ],
        }

    def from_json(self, data: dict):
        self.clear_all()
        for b in data.get("blocks", []):
            bd = BlockData(b["block_id"],b["type_id"],
                           b.get("x",0),b.get("y",0),
                           b.get("label",b["type_id"]),b.get("params",{}))
            try:
                self.add_block(bd)
            except ValueError as e:
                logger.warning(f"Skip unknown block: {e}")
        for w in data.get("wires", []):
            self.add_wire(WireData(w["wire_id"],
                                   w["from_block_id"],w["from_port"],
                                   w["to_block_id"],w["to_port"]))
        self._dirty = False

    def clear_all(self):
        for wid in list(self._wires.keys()):
            self._remove_wire_internal(wid)
        self._wires.clear()
        for bid in list(self._blocks.keys()):
            item = self._blocks.pop(bid)
            self.removeItem(item)
        self._blocks.clear()
        self.clear()

    @property
    def block_count(self): return len(self._blocks)
    @property
    def wire_count(self):  return len(self._wires)
    @property
    def is_dirty(self): return self._dirty
    def mark_clean(self): self._dirty = False

    def draw_grid(self, painter: QPainter, rect: QRectF):
        step = 40
        painter.setPen(QPen(QColor(COL_GRID_DOT), 1))
        x = int(rect.left()/step)*step
        while x < rect.right():
            y = int(rect.top()/step)*step
            while y < rect.bottom():
                painter.drawPoint(QPointF(x,y))
                y += step
            x += step

# ═══════════════════════════════════════════════════════════════════════════════
#  FBD View
# ═══════════════════════════════════════════════════════════════════════════════

class FBDView(QGraphicsView):

    def __init__(self, scene: FBDScene, parent=None):
        super().__init__(scene, parent)
        self._fbd = scene
        self._panning = False
        self._pan_last = QPointF()
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(COL_GRID)))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        self._fbd.draw_grid(painter, rect)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            f = 1.15 if event.angleDelta().y() > 0 else 1/1.15
            self.scale(f, f)
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_last = event.position()
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            d = event.position() - self._pan_last
            self._pan_last = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(d.y()))
            event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            event.accept(); return
        super().mouseReleaseEvent(event)

    def zoom_in(self):   self.scale(1.2, 1.2)
    def zoom_out(self):  self.scale(1/1.2, 1/1.2)
    def zoom_reset(self): self.resetTransform()
    def fit_all(self):
        if self._fbd.block_count:
            self.fitInView(self._fbd.itemsBoundingRect().adjusted(-40,-40,40,40),
                           Qt.AspectRatioMode.KeepAspectRatio)
        else:
            self.zoom_reset()

# ═══════════════════════════════════════════════════════════════════════════════
#  Block Palette
# ═══════════════════════════════════════════════════════════════════════════════

class BlockPalette(QWidget):
    drop_block = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(4,4,4,4); v.setSpacing(4)
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Search… (Ctrl+Space)")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._filter)
        v.addWidget(self._search)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(14)
        self._tree.itemDoubleClicked.connect(self._on_dbl)
        self._tree.setToolTip("Double-click to add block to canvas")
        v.addWidget(self._tree)
        self._populate()

    def _populate(self):
        self._tree.clear()
        by_cat: Dict[str, List[BlockDef]] = {}
        for b in BLOCK_REGISTRY:
            by_cat.setdefault(b.category, []).append(b)
        for cat in CAT_ORDER:
            blocks = by_cat.get(cat, [])
            if not blocks: continue
            ci = QTreeWidgetItem([CAT_LABELS.get(cat, cat)])
            ci.setExpanded(True)
            ci.setData(0, Qt.ItemDataRole.UserRole, None)
            for b in blocks:
                ch = QTreeWidgetItem([b.label])
                ch.setToolTip(0, b.description)
                ch.setData(0, Qt.ItemDataRole.UserRole, b.type_id)
                ci.addChild(ch)
            self._tree.addTopLevelItem(ci)

    def _filter(self, text: str):
        text = text.strip().lower()
        for i in range(self._tree.topLevelItemCount()):
            cat = self._tree.topLevelItem(i)
            any_vis = False
            for j in range(cat.childCount()):
                ch = cat.child(j)
                m = not text or text in ch.text(0).lower()
                ch.setHidden(not m)
                if m: any_vis = True
            cat.setHidden(not any_vis)
            if any_vis: cat.setExpanded(True)

    def _on_dbl(self, item: QTreeWidgetItem, col: int):
        tid = item.data(0, Qt.ItemDataRole.UserRole)
        if tid: self.drop_block.emit(tid)

    def focus_search(self):
        self._search.setFocus()
        self._search.selectAll()

# ═══════════════════════════════════════════════════════════════════════════════
#  Block Properties
# ═══════════════════════════════════════════════════════════════════════════════

class BlockPropertiesPanel(QWidget):
    props_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._block: Optional[BlockItem] = None
        self._editors: Dict[str, QWidget] = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(6,6,6,6); v.setSpacing(6)
        ttl = QLabel("Properties")
        ttl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        v.addWidget(ttl)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        v.addWidget(sep)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._fw = QWidget()
        self._fl = QFormLayout(self._fw)
        self._fl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        scroll.setWidget(self._fw)
        v.addWidget(scroll)
        self._empty = QLabel("Select a block\nto view its properties.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet("color:#606070;font-size:9pt;")
        v.addWidget(self._empty)
        self._fw.hide()

    def show_block(self, item: Optional[BlockItem]):
        self._block = item
        self._editors.clear()
        while self._fl.rowCount():
            self._fl.removeRow(0)
        if item is None:
            self._fw.hide(); self._empty.show(); return
        self._empty.hide(); self._fw.show()
        bd = item.block_def; bdata = item.block_data
        # ID
        il = QLabel(bdata.block_id[:8]+"…")
        il.setStyleSheet("color:#606070;font-size:8pt;")
        self._fl.addRow("ID:", il)
        self._fl.addRow("Type:", QLabel(f"{bd.label} [{bd.category}]"))
        # Label
        le = QLineEdit(bdata.label)
        le.textChanged.connect(self._set_label)
        self._fl.addRow("Label:", le)
        self._editors["__label__"] = le
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        self._fl.addRow(sep)
        # Params
        for pn, pdef in bd.params.items():
            cur = bdata.params.get(pn, pdef)
            w = self._make_widget(pn, cur, pdef)
            if w:
                self._editors[pn] = w
                self._fl.addRow(pn.replace("_"," ").title()+":", w)
        # Port info
        if bd.inputs or bd.outputs:
            sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
            self._fl.addRow(sep2)
            for p in bd.inputs:
                self._fl.addRow(f"▷ {p.label}:", QLabel(f"[{p.dtype}]"))
            for p in bd.outputs:
                self._fl.addRow(f"◁ {p.label}:", QLabel(f"[{p.dtype}]"))

    def _make_widget(self, name, value, default) -> Optional[QWidget]:
        if isinstance(default, bool):
            cb = QCheckBox(); cb.setChecked(bool(value))
            cb.stateChanged.connect(lambda s,n=name: self._set_param(n, s==2))
            return cb
        if isinstance(default, int):
            sb = QSpinBox(); sb.setRange(-999999,999999); sb.setValue(int(value))
            sb.valueChanged.connect(lambda v,n=name: self._set_param(n,v))
            return sb
        if isinstance(default, float):
            sb = QDoubleSpinBox(); sb.setRange(-1e9,1e9); sb.setDecimals(3)
            sb.setValue(float(value))
            sb.valueChanged.connect(lambda v,n=name: self._set_param(n,v))
            return sb
        if isinstance(default, str):
            if name == "action":
                cb = QComboBox(); cb.addItems(["heating","cooling"])
                cb.setCurrentText(str(value))
                cb.currentTextChanged.connect(lambda t,n=name: self._set_param(n,t))
                return cb
            ed = QLineEdit(str(value))
            ed.textChanged.connect(lambda t,n=name: self._set_param(n,t))
            return ed
        return None

    def _set_label(self, text: str):
        if self._block:
            self._block.block_data.label = text
            self._block.update()
            self.props_changed.emit()

    def _set_param(self, name: str, value):
        if self._block:
            self._block.block_data.params[name] = value
            self._block.update()
            self.props_changed.emit()

# ═══════════════════════════════════════════════════════════════════════════════
#  Threads (GOTCHA-013)
# ═══════════════════════════════════════════════════════════════════════════════

class ProgramReadThread(QThread):
    done   = pyqtSignal(dict)
    failed = pyqtSignal(str)
    def __init__(self, adapter, device_instance, parent=None):
        super().__init__(parent)
        self.adapter = adapter; self.device_instance = device_instance
    def run(self):
        try:
            if self.adapter and hasattr(self.adapter,"read_program"):
                self.done.emit(self.adapter.read_program(self.device_instance))
            else:
                self.failed.emit("Adapter does not support read_program.")
        except Exception as e:
            self.failed.emit(str(e))

class ProgramUploadThread(QThread):
    progress = pyqtSignal(int)
    done     = pyqtSignal()
    failed   = pyqtSignal(str)
    def __init__(self, adapter, device_instance, program_json, parent=None):
        super().__init__(parent)
        self.adapter = adapter; self.device_instance = device_instance
        self.program_json = program_json
    def run(self):
        try:
            if self.adapter and hasattr(self.adapter,"write_program"):
                self.progress.emit(30)
                self.adapter.write_program(self.device_instance, self.program_json)
                self.progress.emit(100)
                self.done.emit()
            else:
                self.failed.emit("Adapter does not support write_program.")
        except Exception as e:
            self.failed.emit(str(e))

# ═══════════════════════════════════════════════════════════════════════════════
#  Dialogs
# ═══════════════════════════════════════════════════════════════════════════════

class NewProgramDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Program"); self.setMinimumWidth(340)
        v = QVBoxLayout(self)
        fl = QFormLayout()
        self._name = QLineEdit("New Program")
        self._desc = QLineEdit(); self._desc.setPlaceholderText("Optional…")
        fl.addRow("Name:", self._name); fl.addRow("Description:", self._desc)
        v.addLayout(fl)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        v.addWidget(bb)

    @property
    def program_name(self) -> str:
        return self._name.text().strip() or "Untitled"

class UploadDiffDialog(QDialog):
    def __init__(self, old: dict, new: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Upload to Device — Confirm")
        self.setMinimumSize(480, 360)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("<b>Review changes before uploading to device:</b>"))
        ob = {b["block_id"]:b for b in old.get("blocks",[])}
        nb = {b["block_id"]:b for b in new.get("blocks",[])}
        added   = [b for bid,b in nb.items() if bid not in ob]
        removed = [b for bid,b in ob.items() if bid not in nb]
        lines = [f"Blocks: {len(ob)} → {len(nb)}"]
        if added:   lines.append(f"  + {len(added)} block(s) added")
        if removed: lines.append(f"  - {len(removed)} block(s) removed")
        lines.append(f"Wires:  {len(old.get('wires',[]))} → {len(new.get('wires',[]))}")
        te = QTextEdit(); te.setReadOnly(True); te.setPlainText("\n".join(lines))
        v.addWidget(te)
        warn = QLabel("⚠  This will overwrite the program on the connected device.")
        warn.setStyleSheet("color:#F0A020;font-weight:bold;")
        v.addWidget(warn)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Upload")
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        v.addWidget(bb)

# ═══════════════════════════════════════════════════════════════════════════════
#  Main Panel
# ═══════════════════════════════════════════════════════════════════════════════

class GraphicEditorPanel(QWidget):
    """
    🧠 Program Editor — FBD / Node-based graphical programming panel.
    Full Implementation V0.1.6-alpha.
    """

    def __init__(self, config=None, db=None, current_user=None, parent=None):
        super().__init__(parent)
        self.config       = config
        self.db           = db
        self.current_user = current_user
        self.adapter      = None
        self._prog_name   = "Untitled"
        self._prog_id     = None
        self._dev_inst    = 0
        self._undo: List[dict] = []
        self._redo: List[dict] = []
        self._last_save: Optional[dict] = None
        self._upload_thread: Optional[ProgramUploadThread] = None
        self._read_thread:   Optional[ProgramReadThread]   = None

        self._ensure_db_table()
        self._build_ui()
        self._connect_signals()
        self._new_program(silent=True)
        logger.debug("GraphicEditorPanel initialized — V0.1.6-alpha")

    # ── DB ────────────────────────────────────────────────────────────────

    def _ensure_db_table(self):
        if not self.db:
            return
        try:
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS programs (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    program_name TEXT NOT NULL,
                    description  TEXT DEFAULT '',
                    program_json TEXT NOT NULL,
                    device_name  TEXT DEFAULT 'Local',
                    created_at   TEXT,
                    updated_at   TEXT,
                    created_by   TEXT DEFAULT ''
                )
            """)
        except Exception as e:
            logger.warning(f"programs table: {e}")

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # Header bar
        hdr = QWidget()
        hdr.setFixedHeight(42)
        hdr.setStyleSheet("background:#1A1B28;border-bottom:1px solid #2A2D40;")
        hb = QHBoxLayout(hdr); hb.setContentsMargins(12,0,12,0)
        ttl = QLabel("🧠  Program Editor")
        ttl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        hb.addWidget(ttl)
        self._name_lbl = QLabel("— Untitled")
        self._name_lbl.setStyleSheet("color:#8090A0;font-size:10pt;")
        hb.addWidget(self._name_lbl)
        self._dirty_lbl = QLabel("")
        self._dirty_lbl.setStyleSheet("color:#F0A020;font-size:10pt;")
        hb.addWidget(self._dirty_lbl)
        hb.addStretch()
        root.addWidget(hdr)

        # Toolbar
        tb = self._build_toolbar()
        root.addWidget(tb)

        # Splitter: palette | canvas | props
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._palette = BlockPalette()
        self._palette.setMinimumWidth(155); self._palette.setMaximumWidth(220)
        self._splitter.addWidget(self._palette)

        self._scene = FBDScene()
        self._view  = FBDView(self._scene)
        self._splitter.addWidget(self._view)

        self._props = BlockPropertiesPanel()
        self._props.setMinimumWidth(180); self._props.setMaximumWidth(240)
        self._splitter.addWidget(self._props)

        self._splitter.setStretchFactor(0,0)
        self._splitter.setStretchFactor(1,1)
        self._splitter.setStretchFactor(2,0)
        self._splitter.setSizes([180, 900, 200])
        root.addWidget(self._splitter)

        # Status bar
        self._sb = QStatusBar()
        self._sb.setFixedHeight(22)
        self._sb.setStyleSheet("font-size:8pt;")
        self._sb_blocks = QLabel("  Blocks: 0  ")
        self._sb_wires  = QLabel("Wires: 0  ")
        self._sb_sel    = QLabel("")
        self._sb.addWidget(self._sb_blocks)
        self._sb.addWidget(self._sb_wires)
        self._sb.addWidget(self._sb_sel)
        root.addWidget(self._sb)

    def _build_toolbar(self) -> QToolBar:
        tb = QToolBar()
        tb.setMovable(False)
        tb.setStyleSheet(
            "QToolBar{background:#1E2030;border-bottom:1px solid #2A2D40;spacing:2px;}"
        )

        def _a(label, tip, slot, shortcut=None):
            a = QAction(label, self)
            a.setToolTip(tip)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(shortcut)
            tb.addAction(a)

        _a("📄 New",    "New program",            self._new_program,       "Ctrl+N")
        _a("📂 Open",   "Open saved program",      self._open_program,      "Ctrl+O")
        _a("💾 Save",   "Save program (Ctrl+S)",   self._save_program,      "Ctrl+S")
        _a("📤 Export", "Export as JSON",           self._export_json)
        _a("📥 Import", "Import from JSON",         self._import_json)
        tb.addSeparator()
        _a("⬆ Upload", "Upload to device",         self._upload_to_device)
        _a("⬇ Read",   "Read program from device", self._read_from_device)
        tb.addSeparator()
        _a("↩ Undo",   "Undo (Ctrl+Z)",            self._undo_action,       "Ctrl+Z")
        _a("↪ Redo",   "Redo (Ctrl+Y)",            self._redo_action,       "Ctrl+Y")
        tb.addSeparator()
        _a("🗑 Delete", "Delete selected",          self._delete_sel)
        _a("☐ All",    "Select all",               self._select_all,        "Ctrl+A")
        tb.addSeparator()
        _a("🔍+","Zoom in",              self._view.zoom_in,   "Ctrl+=")
        _a("🔍-","Zoom out",             self._view.zoom_out,  "Ctrl+-")
        _a("⊡ Fit","Fit all",           self._view.fit_all)
        _a("1:1","Reset zoom",           self._view.zoom_reset,"Ctrl+0")
        tb.addSeparator()
        _a("🔎 Search","Search blocks (Ctrl+Space)", self._palette.focus_search,"Ctrl+Space")
        return tb

    def _connect_signals(self):
        self._palette.drop_block.connect(self._add_block_center)
        self._scene.block_selected.connect(self._props.show_block)
        self._scene.block_selected.connect(self._on_sel_changed)
        self._scene.scene_changed_sig.connect(self._on_scene_changed)
        self._scene.edit_block_req.connect(self._on_edit_req)
        self._props.props_changed.connect(self._on_scene_changed)

    # ── Scene events ──────────────────────────────────────────────────────

    def _on_scene_changed(self):
        self._dirty_lbl.setText("●")
        self._update_status()

    def _update_status(self):
        self._sb_blocks.setText(f"  Blocks: {self._scene.block_count}  ")
        self._sb_wires.setText(f"Wires: {self._scene.wire_count}  ")

    def _on_sel_changed(self, item: Optional[BlockItem]):
        if item:
            self._sb_sel.setText(
                f"Selected: {item.block_def.label}  [{item.block_data.block_id[:8]}]"
            )
        else:
            self._sb_sel.setText("")

    def _on_edit_req(self, item: BlockItem):
        self._props.show_block(item)
        self._sb.showMessage(
            f"Editing: {item.block_def.label} [{item.block_data.block_id[:8]}]", 3000)

    # ── Undo/Redo ─────────────────────────────────────────────────────────

    def _push_undo(self):
        self._undo.append(self._scene.to_json())
        if len(self._undo) > 50:
            self._undo.pop(0)
        self._redo.clear()

    def _undo_action(self):
        if not self._undo:
            self._sb.showMessage("Nothing to undo.", 2000); return
        self._redo.append(self._scene.to_json())
        self._scene.from_json(self._undo.pop())
        self._dirty_lbl.setText("●"); self._update_status()

    def _redo_action(self):
        if not self._redo:
            self._sb.showMessage("Nothing to redo.", 2000); return
        self._undo.append(self._scene.to_json())
        self._scene.from_json(self._redo.pop())
        self._dirty_lbl.setText("●"); self._update_status()

    # ── Block ops ─────────────────────────────────────────────────────────

    def _add_block_center(self, type_id: str):
        self._push_undo()
        ctr = self._view.mapToScene(self._view.viewport().rect().center())
        ox, oy = random.uniform(-40,40), random.uniform(-40,40)
        bdef = BLOCK_MAP.get(type_id)
        if not bdef:
            return
        bd = BlockData(str(uuid.uuid4()), type_id,
                       ctr.x()+ox, ctr.y()+oy,
                       bdef.label, deepcopy(bdef.params))
        item = self._scene.add_block(bd)
        self._scene.clearSelection(); item.setSelected(True)
        self._update_status()

    def _delete_sel(self):
        self._push_undo()
        self._scene._delete_selected()

    def _select_all(self):
        for it in self._scene.items():
            if isinstance(it, (BlockItem, WireItem)):
                it.setSelected(True)

    # ── Program management ────────────────────────────────────────────────

    def _check_dirty(self) -> bool:
        if not self._scene.is_dirty:
            return True
        r = QMessageBox.question(self, "Unsaved Changes",
                                 "Discard unsaved changes?",
                                 QMessageBox.StandardButton.Yes |
                                 QMessageBox.StandardButton.No)
        return r == QMessageBox.StandardButton.Yes

    def _new_program(self, silent=False):
        if not silent and not self._check_dirty():
            return
        if not silent:
            dlg = NewProgramDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            self._prog_name = dlg.program_name
        else:
            self._prog_name = "Untitled"
        self._scene.clear_all()
        self._undo.clear(); self._redo.clear()
        self._prog_id = None
        self._last_save = self._scene.to_json()
        self._dirty_lbl.setText("")
        self._name_lbl.setText(f"— {self._prog_name}")
        self._update_status()
        if not silent:
            self._sb.showMessage(f"New program: {self._prog_name}", 3000)

    def _save_program(self):
        if not self.db:
            self._sb.showMessage("No database — cannot save.", 3000); return
        pj  = json.dumps(self._scene.to_json())
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        usr = (self.current_user or {}).get("username", "")
        try:
            if self._prog_id:
                self.db.execute(
                    "UPDATE programs SET program_json=?,updated_at=?,program_name=? WHERE id=?",
                    (pj, now, self._prog_name, self._prog_id))
            else:
                self._prog_id = self.db.insert(
                    "INSERT INTO programs (program_name,description,program_json,"
                    "device_name,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?,?)",
                    (self._prog_name,"",pj,"Local",now,now,usr))
            self._scene.mark_clean()
            self._last_save = self._scene.to_json()
            self._dirty_lbl.setText("")
            self._sb.showMessage(f"💾  Saved: {self._prog_name}", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def _open_program(self):
        if not self._check_dirty():
            return
        if not self.db:
            self._sb.showMessage("No database.", 3000); return
        try:
            rows = self.db.fetchall(
                "SELECT id,program_name,updated_at FROM programs ORDER BY updated_at DESC")
        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e)); return
        if not rows:
            QMessageBox.information(self,"Open Program","No saved programs found."); return

        dlg = QDialog(self); dlg.setWindowTitle("Open Program")
        dlg.setMinimumSize(420, 280)
        lay = QVBoxLayout(dlg)
        lst = QListWidget()
        for row in rows:
            it = QListWidgetItem(f"{row['program_name']}  —  {row.get('updated_at','')}")
            it.setData(Qt.ItemDataRole.UserRole, row["id"])
            lst.addItem(it)
        lay.addWidget(lst)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Open |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        sel = lst.currentItem()
        if not sel: return

        try:
            row  = self.db.fetchone("SELECT * FROM programs WHERE id=?",
                                    (sel.data(Qt.ItemDataRole.UserRole),))
            data = json.loads(row["program_json"])
            self._scene.from_json(data)
            self._prog_name = row["program_name"]
            self._prog_id   = row["id"]
            self._last_save = data
            self._dirty_lbl.setText("")
            self._undo.clear(); self._redo.clear()
            self._name_lbl.setText(f"— {self._prog_name}")
            self._update_status()
            self._view.fit_all()
            self._sb.showMessage(f"Loaded: {self._prog_name}", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e))

    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Program as JSON",
            f"{self._prog_name}.json",
            "JSON (*.json);;All (*)")
        if not path: return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._scene.to_json(), f, indent=2)
            self._sb.showMessage(f"Exported: {path}", 4000)
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _import_json(self):
        if not self._check_dirty(): return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Program", "", "JSON (*.json);;All (*)")
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._scene.from_json(data)
            self._prog_name = os.path.splitext(os.path.basename(path))[0]
            self._prog_id   = None
            self._last_save = data
            self._dirty_lbl.setText("")
            self._undo.clear(); self._redo.clear()
            self._name_lbl.setText(f"— {self._prog_name}")
            self._update_status()
            self._view.fit_all()
            self._sb.showMessage(f"Imported: {path}", 4000)
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))

    # ── Device upload / read (GOTCHA-013) ─────────────────────────────────

    def _upload_to_device(self):
        if not self.adapter:
            QMessageBox.warning(self,"No Device","Connect to a device first."); return
        cur = self._scene.to_json()
        dlg = UploadDiffDialog(self._last_save or {}, cur, self)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        self._upload_thread = ProgramUploadThread(
            self.adapter, self._dev_inst, cur, self)
        self._upload_thread.progress.connect(
            lambda p: self._sb.showMessage(f"Uploading… {p}%"))
        self._upload_thread.done.connect(self._on_upload_done)
        self._upload_thread.failed.connect(
            lambda e: QMessageBox.critical(self,"Upload Failed", e))
        self._upload_thread.start()

    def _on_upload_done(self):
        self._last_save = self._scene.to_json()
        self._sb.showMessage("✅  Upload complete.", 4000)

    def _read_from_device(self):
        if not self.adapter:
            QMessageBox.warning(self,"No Device","Connect to a device first."); return
        if not self._check_dirty(): return
        self._read_thread = ProgramReadThread(self.adapter, self._dev_inst, self)
        self._read_thread.done.connect(self._on_read_done)
        self._read_thread.failed.connect(
            lambda e: QMessageBox.critical(self,"Read Failed", e))
        self._sb.showMessage("Reading program from device…")
        self._read_thread.start()

    def _on_read_done(self, data: dict):
        self._scene.from_json(data)
        self._undo.clear(); self._redo.clear()
        self._last_save = data
        self._dirty_lbl.setText("")
        self._update_status()
        self._view.fit_all()
        self._sb.showMessage("Program read from device.", 4000)

    # ── External API ──────────────────────────────────────────────────────

    def set_adapter(self, adapter, device_instance: int = 0,
                    device_name: str = ""):
        """Called by main_window when a device connects."""
        self.adapter    = adapter
        self._dev_inst  = device_instance
        self._sb.showMessage(
            f"Device: {device_name} (instance {device_instance})", 5000)
