# -*- coding: utf-8 -*-
"""
데스크탑 펫
- 사진을 넣으면 배경을 자동으로 지우고 바탕화면을 돌아다니는 펫으로 만들어 줍니다.
- 움직임/행동 로직은 pet_brain.py, 배경 제거는 bgremove.py
"""
import datetime
import json
import math
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QLockFile, QPoint, QPointF, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, 
    QLabel, QMenu, QMessageBox, QPushButton, QScrollArea, QSlider,
    QComboBox, QSystemTrayIcon, QTextBrowser, QVBoxLayout, QWidget,
)

import random

from help_text import HELP_HTML
import winplat
from pet_brain import PetBrain, Snack, resolve_contacts, start_train

APP_NAME = "데스크탑 펫"
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "DesktopPet"
PET_DIR = DATA_DIR / "pets"
SETTINGS_FILE = DATA_DIR / "settings.json"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".jfif", ".webp", ".bmp", ".gif", ".tif", ".tiff",
              ".heic", ".heif", ".avif", ".ico"}

TRACE = bool(os.environ.get("DESKTOPPET_TRACE"))
BASE_HEIGHT = 110      # 크기 100%일 때 펫 높이(px)
TICK_MS = 33            # 움직일 때 (초당 30번)
IDLE_TICK_MS = 90       # 다들 가만히 있을 때 (초당 11번) → CPU 절약
PAUSE_TICK_MS = 1000    # 전체화면/숨김 중
SCAN_EVERY = 0.4        # 열린 창 목록 전체 검색 간격(초)
FAST_STATES = ("air", "drag", "walk", "run", "chase", "hop", "dance", "to_wall", "climb", "hang",
               "crouch", "meet", "happy", "dizzy", "go_snack", "eat", "train", "stretch")
OFFWORK_LINES = ["퇴근까지 {m}분!", "조금만 더 힘내요!", "하암… 졸려", "오늘 저녁 뭐 먹지?",
                 "칼퇴 가즈아!", "집에 가고 싶다…", "오늘도 고생 많았어요 ♥", "퇴근까지 {m}분 남았어요"]
EMO_SPACE = 56         # 펫 머리 위 이모티콘 공간
PINK = "#f06292"
EMO_COLORS = {}
EMO_FONTS = {}
BUBBLE_FONT = None
FOODS = ["🍪", "🍩", "🍙", "🍓", "🍰", "🍗", "🍦", "🥐"]


def init_emote_style():
    EMO_COLORS.update({"♥": QColor(240, 80, 120), "♪": QColor(90, 120, 230), "★": QColor(250, 190, 30),
                       "!": QColor(235, 70, 60), "?": QColor(80, 140, 230), "z": QColor(120, 120, 160),
                       "콩!": QColor(255, 105, 150), "뿅!": QColor(160, 110, 240)})
    EMO_FONTS["small"] = QFont("Segoe UI Symbol", 11, QFont.Bold)
    global BUBBLE_FONT
    BUBBLE_FONT = QFont("Malgun Gothic", 10, QFont.Bold)
    EMO_COLORS.update({"냠": QColor(240, 130, 60), "하암": QColor(140, 130, 170)})


# ──────────────────────────── 설정 저장 ────────────────────────────
class Settings:
    def __init__(self):
        self.data = {"global_scale": 100, "pets": {}}
        if SETTINGS_FILE.exists():
            try:
                self.data.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
            except Exception:
                pass

    def save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def pet(self, name):
        return self.data["pets"].setdefault(name, {"enabled": True, "scale": 100})


# ──────────────────────────── 배경 제거 작업 ────────────────────────────
class BackgroundRemover(QThread):
    progress = Signal(str)
    finished_one = Signal(str)
    failed = Signal(str, str)

    def __init__(self, paths, split=True):
        super().__init__()
        self.paths = paths
        self.split = split

    def run(self):
        import bgremove
        for i, path in enumerate(self.paths, 1):
            path = Path(path)
            try:
                self.progress.emit(f"{path.name} 배경 지우는 중… ({i}/{len(self.paths)})")
                imgs = bgremove.make_pet_images(path, self.progress.emit, split=self.split)
                PET_DIR.mkdir(parents=True, exist_ok=True)
                stem = "".join(c for c in path.stem if c not in '\\/:*?"<>|')[:30] or "pet"
                for k, img in enumerate(imgs, 1):
                    base = stem if len(imgs) == 1 else f"{stem}_{k}"
                    name, n = base, 2
                    while (PET_DIR / f"{name}.png").exists():
                        name, n = f"{base}_{n}", n + 1
                    img.save(PET_DIR / f"{name}.png")
                    self.finished_one.emit(name)
                if len(imgs) > 1:
                    self.progress.emit(f"{path.name}: {len(imgs)}마리로 나눴어요!")
            except Exception as e:
                msg = str(e)
                if "urlopen" in msg or "Errno" in msg or "timed out" in msg:
                    msg = "배경 제거 모델을 내려받지 못했어요. 인터넷 연결을 확인해 주세요.\n\n" + msg
                self.failed.emit(path.name, msg)


# ──────────────────────────── 펫 창 ────────────────────────────
def screen_area(x, y):
    screen = QGuiApplication.screenAt(QPoint(int(x), int(y))) or QGuiApplication.primaryScreen()
    g = screen.availableGeometry()
    return (g.x(), g.y(), g.x() + g.width(), g.y() + g.height())


class PetWindow(QWidget):
    def __init__(self, name, app_ref):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.name = name
        self.app_ref = app_ref
        self.source = QPixmap(str(PET_DIR / f"{name}.png"))
        self.pix = self.source
        self.drag_offset = None
        self.drag_hist = []
        self.pw = self.ph = 10
        self._pos = None
        self._key = None

        prim = QGuiApplication.primaryScreen().availableGeometry()
        self.update_scale(first=True)
        self.brain = PetBrain(self.pw, self.ph, (prim.x(), prim.y(), prim.x() + prim.width(),
                                                  prim.y() + prim.height()))
        self.place()

    def update_scale(self, first=False):
        s = self.app_ref.settings
        scale = s.pet(self.name)["scale"] / 100 * s.data["global_scale"] / 100
        h = max(24, int(BASE_HEIGHT * scale))
        ratio = self.source.width() / max(1, self.source.height())
        w = max(12, int(h * ratio))
        if w > h * 1.6:                      # 아주 가로로 긴 사진은 너비 기준으로
            w = int(h * 1.6)
            h = int(w / ratio)
        dpr = self.devicePixelRatioF()
        pm = self.source.scaled(QSize(int(w * dpr), int(h * dpr)), Qt.IgnoreAspectRatio,
                                Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        self.pix, self.pw, self.ph = pm, w, h
        side = max(int(math.hypot(w, h) * 1.25) + 16, 176)     # 말풍선 들어갈 너비
        self.setFixedSize(side, side + EMO_SPACE)
        if not first:
            self.brain.set_size(w, h)

    def visual_center(self):
        b = self.brain
        return b.cx, b.cy + b.hop_y - b.bob

    def place(self):
        x, y = self.visual_center()
        pos = (int(x - self.width() / 2), int(y - EMO_SPACE - (self.height() - EMO_SPACE) / 2))
        if pos != self._pos:                 # 위치가 그대로면 창을 건드리지 않음
            self._pos = pos
            self.move(*pos)

    def think(self, now, mouse, others, plats):
        b = self.brain
        area = screen_area(b.cx, b.cy)
        b.update(now, area, mouse, others, plats)

    def render(self):
        """바뀐 게 있을 때만 옮기고, 모양이 바뀌었을 때만 다시 그림 (CPU 절약)"""
        b = self.brain
        self.place()
        em = tuple((e[0], int((b.now - e[1]) * 25)) for e in b.emotes)
        key = (round(b.angle), round(b.squash * 30), round(b.flat_now * 40), b.facing, em, self.pw, self.ph,
               b.bubble[0] if b.bubble else None)
        if key != self._key:
            self._key = key
            self.update()

    # ── 그리기 ──
    def paintEvent(self, _):
        b = self.brain
        p = QPainter(self)
        p.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing | QPainter.TextAntialiasing)
        cx = self.width() / 2
        cy = EMO_SPACE + (self.height() - EMO_SPACE) / 2
        w, h = self.pw, self.ph

        p.save()
        p.translate(cx, cy)
        p.rotate(b.angle)
        sx = 1 + 0.2 * b.squash + 0.6 * b.flat_now
        sy = 1 - 0.2 * b.squash - b.flat_now
        p.translate(0, h / 2)               # 발끝 기준으로 찌그러지게
        p.scale(sx * b.facing, sy)
        p.translate(0, -h / 2)
        p.drawPixmap(QRectF(-w / 2, -h / 2, w, h), self.pix, QRectF(self.pix.rect()))
        p.restore()

        # 머리 위 이모티콘 / 부딪힘 반짝이
        now = b.now
        head_y = cy - h / 2 - 2 if abs(b.angle) < 45 else cy - w / 2 - 2
        for text, t0, dur, dx, style in b.emotes:
            k = (now - t0) / dur
            if not 0 <= k <= 1:
                continue
            if style == "burst":
                alpha = int(255 * (1 - k))
                r = 6 + k * 26
                p.setFont(EMO_FONTS["small"])
                for n in range(6):
                    ang = n * math.pi / 3 + 0.3
                    col = QColor(255, 196, 40, alpha) if n % 2 else QColor(255, 120, 170, alpha)
                    p.setPen(col)
                    p.drawText(QPointF(cx + dx + math.cos(ang) * r - 5, cy + math.sin(ang) * r + 5), "✦")
                continue
            alpha = int(255 * (1 - max(0, k - 0.6) / 0.4))
            pop = 1.0
            if text in ("콩!", "뿅!"):
                pop = 1.0 + 0.5 * max(0.0, 1 - k * 5)          # 처음에 크게 뿅
            y = head_y - 6 - k * 34
            x = cx + dx + (math.sin(k * 9) * 4 if text in ("z", "♪") else 0)
            size = int(12 + k * 8) if text == "z" else int(19 * pop)
            emoji = text in ("💦", "💢")
            font = QFont("Segoe UI Emoji" if emoji else "Malgun Gothic", size, QFont.Bold)
            p.setFont(font)
            half = p.fontMetrics().horizontalAdvance(text) / 2
            color = EMO_COLORS.get(text, QColor(80, 160, 230))
            color = QColor(color)
            # 흰 테두리
            p.setPen(QColor(255, 255, 255, alpha))
            for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                p.drawText(QPointF(x - half + ox, y + oy), text)
            color.setAlpha(alpha)
            p.setPen(color)
            p.drawText(QPointF(x - half, y), text)
        if b.bubble:
            self.draw_bubble(p, b.bubble[0], cx, head_y)
        p.end()

    def draw_bubble(self, p, text, cx, head_y):
        p.setFont(BUBBLE_FONT)
        fm = p.fontMetrics()
        tw = min(fm.horizontalAdvance(text), self.width() - 22)
        text = fm.elidedText(text, Qt.ElideRight, tw + 1)
        bw, bh = tw + 16, fm.height() + 8
        x = max(2, min(self.width() - bw - 2, cx - bw / 2))
        y = max(2, head_y - bh - 12)
        p.setPen(QColor(240, 98, 146))
        p.setBrush(QColor(255, 255, 255, 245))
        p.drawRoundedRect(QRectF(x, y, bw, bh), 10, 10)
        tail_x = max(x + 10, min(x + bw - 10, cx))
        p.setPen(Qt.NoPen)
        p.drawPolygon([QPointF(tail_x - 6, y + bh - 1), QPointF(tail_x + 6, y + bh - 1), QPointF(tail_x, y + bh + 7)])
        p.setPen(QColor(240, 98, 146))
        p.drawLine(QPointF(tail_x - 6, y + bh), QPointF(tail_x, y + bh + 7))
        p.drawLine(QPointF(tail_x + 6, y + bh), QPointF(tail_x, y + bh + 7))
        p.setPen(QColor(70, 60, 70))
        p.drawText(QRectF(x, y, bw, bh), Qt.AlignCenter, text)

    # ── 마우스 ──
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            g = e.globalPosition()
            self.brain.start_drag()
            self.drag_offset = QPointF(g.x() - self.brain.cx, g.y() - self.brain.cy)
            self.drag_hist = [(time.time(), g)]
            self.press_pos = g

    def mouseMoveEvent(self, e):
        g = e.globalPosition()
        if self.drag_offset is not None:
            last = self.drag_hist[-1][1]
            self.drag_hist = (self.drag_hist + [(time.time(), g)])[-6:]
            self.brain.drag_to(g.x() - self.drag_offset.x(), g.y() - self.drag_offset.y(), g.x() - last.x())
            self.place()
        elif not e.buttons():
            self.brain.stroke()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.drag_offset is not None:
            (t0, p0), (t1, p1) = self.drag_hist[0], self.drag_hist[-1]
            if time.time() - t1 > 0.12:        # 멈췄다가 놓으면 그냥 떨어뜨림
                vx = vy = 0.0
            else:
                frames = max((t1 - t0) * 1000 / TICK_MS, 0.5)
                vx = max(-40, min(40, (p1.x() - p0.x()) / frames))
                vy = max(-40, min(40, (p1.y() - p0.y()) / frames))
            self.drag_offset = None
            self.brain.throw(vx, vy)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            b = self.brain
            self.drag_offset = None
            area = screen_area(b.cx, b.cy)
            if b.cy >= b.ground(area) - 2:
                b.state = "idle"
            b.poke()

    def contextMenuEvent(self, e):
        b = self.brain
        menu = QMenu(self)
        free = b.state not in ("air", "drag", "climb", "hang")

        def act(fn):
            return lambda: fn() if b.state not in ("air", "drag", "climb", "hang") else None

        def dance():
            b.angle = 0
            b.set_state("dance", 4, 6)
            b.emote("note")

        def sleep():
            b.angle = 0
            b.flat = 0.22
            b.set_state("sleep", 10, 20)
            b.emote("z", 1.8)

        def climb():
            b.angle = 0
            b.speed = 3
            b.set_state("to_wall", 15, 15)

        for text, fn in (("점프!", b.jump), ("공중제비", lambda: b.jump(flip=True)),
                         ("춤추기 ♪", dance), ("재우기 z", sleep), ("벽 타기", climb)):
            a = menu.addAction(text, act(fn))
            a.setEnabled(free)
        menu.addSeparator()
        menu.addAction("간식 주기 🍪", lambda: self.app_ref.drop_snack(b.cx + random.choice([-1, 1]) * random.uniform(120, 260)))
        menu.addAction("기차놀이 🚂", self.app_ref.start_train)
        menu.addSeparator()
        menu.addAction("이 펫 숨기기", lambda: self.app_ref.set_enabled(self.name, False))
        menu.addAction("설정 열기", self.app_ref.show_settings)
        menu.addAction("사용법", self.app_ref.show_help)
        menu.exec(e.globalPos())


class SnackWindow(QWidget):
    SIZE = 46

    def __init__(self, snack):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.NoDropShadowWindowHint | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.snack = snack
        self.scale = 1.0
        self.setFixedSize(self.SIZE, self.SIZE)
        self._pos = None

    def sync(self, now):
        sn = self.snack
        pos = (int(sn.x - self.SIZE / 2), int(sn.y - self.SIZE / 2 - 4))
        if pos != self._pos:
            self._pos = pos
            self.move(*pos)
        scale = 1.0 if sn.eat_t is None else max(0.0, 1 - (now - sn.eat_t) / 2.4)
        scale = round(scale * 4) / 4                 # 한 입씩 줄어들기
        if scale != self.scale:
            self.scale = scale
            self.update()

    def paintEvent(self, _):
        if self.scale <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setFont(QFont("Segoe UI Emoji", max(6, int(22 * self.scale))))
        p.drawText(self.rect(), Qt.AlignCenter, self.snack.food)
        p.end()


# ──────────────────────────── 설정창 ────────────────────────────
class PetCard(QFrame):
    def __init__(self, name, app_ref):
        super().__init__()
        self.setObjectName("card")
        self.setFixedSize(150, 172)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.addStretch()
        delete = QPushButton("×")
        delete.setObjectName("del")
        delete.setFixedSize(22, 22)
        delete.setToolTip("펫 삭제")
        delete.clicked.connect(lambda: app_ref.delete_pet(name))
        top.addWidget(delete)
        lay.addLayout(top)

        thumb = QLabel()
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setPixmap(QPixmap(str(PET_DIR / f"{name}.png")).scaled(
            QSize(84, 72), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lay.addWidget(thumb, 1)

        cfg = app_ref.settings.pet(name)
        self.check = QCheckBox(name if len(name) <= 10 else name[:9] + "…")
        self.check.setToolTip(name)
        self.check.setChecked(cfg["enabled"])
        self.check.toggled.connect(lambda on: app_ref.set_enabled(name, on))
        lay.addWidget(self.check, 0, Qt.AlignCenter)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(40, 250)
        slider.setValue(cfg["scale"])
        slider.setToolTip("이 펫 크기")
        slider.valueChanged.connect(lambda v: app_ref.set_scale(name, v))
        lay.addWidget(slider)
        self.refresh_style()

    def refresh_style(self):
        self.setProperty("on", self.check.isChecked())
        self.style().unpolish(self)
        self.style().polish(self)


class SettingsWindow(QWidget):
    def __init__(self, app_ref):
        super().__init__()
        self.app_ref = app_ref
        self.cards = {}
        self._cols = 0
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(700, 640)
        self.setStyleSheet(f"""
            QWidget {{ font-family: 'Malgun Gothic', sans-serif; font-size: 13px; color: #333; }}
            SettingsWindow, QScrollArea, #grid {{ background: #ffffff; }}
            #card {{ background: #f4f4f6; border-radius: 14px; }}
            #card[on="true"] {{ background: #fde4ec; }}
            QPushButton {{ background: #efeff2; border: none; border-radius: 8px; padding: 6px 12px; }}
            QPushButton:hover {{ background: #e3e3e8; }}
            #add {{ background: {PINK}; color: white; font-weight: bold; padding: 9px 16px; }}
            #add:hover {{ background: #e04f82; }}
            #del {{ background: transparent; color: #aaa; font-size: 15px; padding: 0; }}
            #del:hover {{ color: #e53935; }}
            QSlider::groove:horizontal {{ height: 4px; background: #ddd; border-radius: 2px; }}
            QSlider::sub-page:horizontal {{ background: {PINK}; border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: white; border: 1px solid #ccc; width: 14px; margin: -6px 0; border-radius: 7px; }}
            QCheckBox::indicator {{ width: 14px; height: 14px; }}
            QCheckBox::indicator:checked {{ background: {PINK}; border: 1px solid {PINK}; border-radius: 3px; }}
            QCheckBox::indicator:unchecked {{ background: white; border: 1px solid #bbb; border-radius: 3px; }}
            #hint {{ color: #999; font-size: 12px; }}
            #status {{ color: {PINK}; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)

        top = QHBoxLayout()
        add = QPushButton("+ 사진 추가")
        add.setObjectName("add")
        add.clicked.connect(self.pick_files)
        top.addWidget(add)
        self.status = QLabel("")
        self.status.setObjectName("status")
        top.addWidget(self.status, 1)
        help_btn = QPushButton("? 사용법")
        help_btn.clicked.connect(app_ref.show_help)
        top.addWidget(help_btn)
        for text, on in (("모두 켜기", True), ("모두 끄기", False)):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _=False, on=on: app_ref.set_all(on))
            top.addWidget(btn)
        root.addLayout(top)

        self.empty = QLabel("아직 펫이 없어요.\n\n사진을 이 창에 끌어다 놓거나 (여러 장·폴더도 OK)\n'+ 사진 추가'를 누르거나, 복사한 그림을 Ctrl+V 하세요.\n배경은 자동으로 지워져요 ✨\n\nPNG · JPG · WEBP · GIF · BMP · TIFF · HEIC(아이폰) · AVIF")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setObjectName("hint")
        self.empty.setStyleSheet("font-size: 16px;")

        self.grid_host = QWidget()
        self.grid_host.setObjectName("grid")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(10)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(self.grid_host)
        root.addWidget(self.empty, 1)
        root.addWidget(self.scroll, 1)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("전체 크기"))
        self.global_slider = QSlider(Qt.Horizontal)
        self.global_slider.setRange(40, 250)
        self.global_slider.setValue(app_ref.settings.data["global_scale"])
        self.global_slider.valueChanged.connect(app_ref.set_global_scale)
        size_row.addWidget(self.global_slider, 1)
        reset = QPushButton("기본값")
        reset.clicked.connect(lambda: self.global_slider.setValue(100))
        size_row.addWidget(reset)
        self.win_check = QCheckBox("열린 창 위에서 놀기")
        self.win_check.setToolTip("새 창이 열리면 펫이 뛰어올라가고, 창을 옮기면 같이 타고 다녀요")
        self.win_check.setChecked(app_ref.settings.data.get("window_play", True))
        self.win_check.toggled.connect(app_ref.set_window_play)
        root.addLayout(size_row)

        opt_row = QHBoxLayout()
        opt_row.addWidget(self.win_check)
        opt_row.addSpacing(16)
        self.fs_check = QCheckBox("전체화면일 때 숨기기")
        self.fs_check.setToolTip("PPT 발표, 영상 전체화면, 게임 중에는 펫이 잠깐 사라졌다가 끝나면 다시 나와요")
        self.fs_check.setChecked(app_ref.settings.data.get("hide_fullscreen", True))
        self.fs_check.toggled.connect(app_ref.set_hide_fullscreen)
        opt_row.addWidget(self.fs_check)
        opt_row.addSpacing(16)
        self.split_check = QCheckBox("여러 마리 사진은 나누기")
        self.split_check.setToolTip("한 사진에 캐릭터가 여러 마리면 한 마리씩 따로 펫으로 만들어요")
        self.split_check.setChecked(app_ref.settings.data.get("split", True))
        self.split_check.toggled.connect(lambda on: app_ref.set_option("split", on))
        opt_row.addWidget(self.split_check)
        opt_row.addStretch()
        root.addLayout(opt_row)

        work_row = QHBoxLayout()
        self.off_check = QCheckBox("퇴근임박 모드")
        self.off_check.setToolTip("퇴근 1시간 전부터 펫들이 졸고, 퇴근까지 남은 시간을 알려 주고, 퇴근하면 축하해요 (평일만)")
        self.off_check.setChecked(app_ref.settings.data.get("offwork", True))
        self.off_check.toggled.connect(lambda on: app_ref.set_option("offwork", on))
        work_row.addWidget(self.off_check)
        work_row.addWidget(QLabel("퇴근 시간"))
        self.end_combo = QComboBox()
        for hh in range(12, 24):
            for mm in (0, 30):
                self.end_combo.addItem(f"{hh:02d}:{mm:02d}")
        self.end_combo.setCurrentText(app_ref.settings.data.get("work_end", "18:00"))
        self.end_combo.currentTextChanged.connect(lambda t: app_ref.set_option("work_end", t))
        work_row.addWidget(self.end_combo)
        work_row.addSpacing(16)
        self.rest_check = QCheckBox("50분마다 쉬는 시간 알림")
        self.rest_check.setToolTip("50분마다 펫이 기지개를 켜며 잠깐 쉬자고 말해요")
        self.rest_check.setChecked(app_ref.settings.data.get("rest_alert", True))
        self.rest_check.toggled.connect(lambda on: app_ref.set_option("rest_alert", on))
        work_row.addWidget(self.rest_check)
        work_row.addStretch()
        root.addLayout(work_row)

        bottom = QHBoxLayout()
        hint = QLabel("창을 닫아도 펫은 계속 놀아요. 작업표시줄 오른쪽 발바닥 아이콘이나 펫 우클릭으로 이 창을 다시 열 수 있어요.\n"
                      "펫을 집어 던지거나, 더블클릭(점프)하거나, 마우스로 문질러(쓰다듬기) 보세요.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        bottom.addWidget(hint, 1)
        quit_btn = QPushButton("프로그램 종료")
        quit_btn.clicked.connect(app_ref.quit)
        bottom.addWidget(quit_btn, 0, Qt.AlignBottom)
        root.addLayout(bottom)

    def cols(self):
        return max(1, (self.scroll.viewport().width() - 10) // 160)

    def rebuild(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.cards.clear()
        names = self.app_ref.pet_names()
        self._cols = self.cols()
        for i, name in enumerate(names):
            card = PetCard(name, self.app_ref)
            self.cards[name] = card
            self.grid.addWidget(card, i // self._cols, i % self._cols)
        self.empty.setVisible(not names)
        self.scroll.setVisible(bool(names))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._cols and self.cols() != self._cols:
            self.rebuild()

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self.rebuild)

    def sync_checks(self):
        for name, card in self.cards.items():
            card.check.blockSignals(True)
            card.check.setChecked(self.app_ref.settings.pet(name)["enabled"])
            card.check.blockSignals(False)
            card.refresh_style()

    def pick_files(self):
        pattern = " ".join("*" + e for e in sorted(IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(
            self, "펫으로 만들 사진 고르기 (여러 장 한꺼번에 골라도 돼요)", str(Path.home() / "Pictures"),
            f"이미지 ({pattern});;모든 파일 (*.*)")
        if files:
            self.app_ref.add_images(files)

    def take_images(self, mime):
        """끌어다 놓기 / 붙여넣기 내용에서 이미지 파일 모으기 (폴더면 안의 이미지 전부)"""
        files = []
        for u in mime.urls() if mime.hasUrls() else []:
            p = Path(u.toLocalFile())
            if not u.isLocalFile():
                continue
            if p.is_dir():
                files += sorted(str(f) for f in p.iterdir() if f.suffix.lower() in IMAGE_EXTS)
            elif p.suffix.lower() in IMAGE_EXTS:
                files.append(str(p))
        if not files and mime.hasImage():
            # 웹 브라우저에서 끌어온 그림, 캡처 도구로 복사한 그림 등
            img = mime.imageData()
            if img is not None and not img.isNull():
                tmp_dir = DATA_DIR / "tmp"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                path = tmp_dir / time.strftime("붙여넣은그림_%H%M%S.png")
                img.save(str(path))
                files.append(str(path))
        return files

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = self.take_images(e.mimeData())
        if files:
            self.app_ref.add_images(files)
        else:
            self.status.setText("지원하는 이미지 파일이 없어요")

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Paste):          # Ctrl+V로 붙여넣기
            files = self.take_images(QGuiApplication.clipboard().mimeData())
            if files:
                self.app_ref.add_images(files)
            else:
                self.status.setText("클립보드에 그림이 없어요")
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        e.ignore()
        self.hide()


class HelpWindow(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Window)
        self.setWindowTitle("데스크탑 펫 사용법")
        self.resize(620, 720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 10)
        view = QTextBrowser()
        view.setOpenExternalLinks(False)
        view.setFrameShape(QFrame.NoFrame)
        view.setStyleSheet("QTextBrowser { background: white; padding: 14px 18px; }")
        view.setHtml(HELP_HTML)
        lay.addWidget(view, 1)
        close = QPushButton("닫기")
        close.setStyleSheet(f"QPushButton {{ background: {PINK}; color: white; font-weight: bold; border: none;"
                            " border-radius: 8px; padding: 8px 28px; }")
        close.clicked.connect(self.hide)
        lay.addWidget(close, 0, Qt.AlignCenter)


# ──────────────────────────── 앱 ────────────────────────────
def make_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(PINK))
    p.setPen(Qt.NoPen)
    p.drawEllipse(18, 28, 28, 26)
    for cx, cy in [(12, 22), (24, 12), (40, 12), (52, 22)]:
        p.drawEllipse(cx - 7, cy - 7, 14, 14)
    p.end()
    return QIcon(pm)


class PetApp:
    def __init__(self, qapp):
        self.qapp = qapp
        qapp.setQuitOnLastWindowClosed(False)
        PET_DIR.mkdir(parents=True, exist_ok=True)
        self.settings = Settings()
        self.pets = {}
        self.workers = []

        self.icon = make_icon()
        qapp.setWindowIcon(self.icon)
        self.window = SettingsWindow(self)
        self.help = None

        self.tray = QSystemTrayIcon(self.icon)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        menu.addAction("설정 열기", self.show_settings)
        menu.addAction("사용법", self.show_help)
        menu.addAction("모두 켜기", lambda: self.set_all(True))
        menu.addAction("모두 끄기", lambda: self.set_all(False))
        menu.addAction("간식 주기 🍪", lambda: self.drop_snack())
        menu.addAction("기차놀이 🚂", self.start_train)
        self.snooze_action = menu.addAction("30분 동안 숨기기", self.toggle_snooze)
        menu.addSeparator()
        menu.addAction("종료", self.quit)
        self.tray.setContextMenu(menu)
        self._menu = menu
        self.tray.activated.connect(self.on_tray)
        self.tray.show()

        for name in self.pet_names():
            if self.settings.pet(name)["enabled"]:
                self.spawn(name)
        self.settings.save()

        self.t0 = time.time()
        self.frame = 0
        self.plats = {}
        self.win_rects = {}          # hwnd -> 마지막으로 본 창 위치 (물리 픽셀)
        self.seen_windows = None
        self.new_windows = {}
        self.last_scan = -1.0
        self.last_fs_check = -1.0
        self.fullscreen = False
        self.snooze_until = 0.0
        self.paused = False
        self.snacks = []                 # [(Snack, SnackWindow)]
        self.next_train = random.uniform(90, 200)
        self.next_rest = 50 * 60
        self.next_chat = 0.0
        self.last_clock_check = -1.0
        self.done_events = {}            # 오늘 이미 한 퇴근 이벤트
        self.clock_offset = datetime.timedelta(0)
        self.timer = QTimer()
        self.timer.setTimerType(Qt.CoarseTimer)    # 정밀 타이머보다 전력/CPU를 덜 씀
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)

        if os.environ.get("DESKTOPPET_DEMO"):          # 시험 녹화용: 신호 파일이 생기면 연출 시작
            self.demo_timer = QTimer()
            self.demo_timer.timeout.connect(self.demo_poll)
            self.demo_timer.start(200)
        if not self.pets or "--settings" in sys.argv:
            self.show_settings()
        if not self.settings.data.get("help_shown"):
            self.settings.data["help_shown"] = True
            self.settings.save()
            QTimer.singleShot(400, self.show_help)

    def on_tray(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_settings()

    def pet_names(self):
        return sorted(p.stem for p in PET_DIR.glob("*.png"))

    def show_help(self):
        if self.help is None:
            self.help = HelpWindow()
        self.help.show()
        self.help.raise_()
        self.help.activateWindow()

    def show_settings(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def spawn(self, name):
        if name not in self.pets:
            pet = PetWindow(name, self)
            self.pets[name] = pet
            if not getattr(self, "paused", False):
                pet.show()

    # ── 열린 창 = 발판 ──
    def to_logical(self, x, y):
        """윈도우 API의 물리 픽셀 → Qt 화면 좌표 (배율 125%, 150% 등 대응)"""
        for s in QGuiApplication.screens():
            g, d = s.geometry(), s.devicePixelRatio()
            if g.x() <= x < g.x() + g.width() * d and g.y() <= y < g.y() + g.height() * d:
                return g.x() + (x - g.x()) / d, g.y() + (y - g.y()) / d
        d = QGuiApplication.primaryScreen().devicePixelRatio()
        return x / d, y / d

    def scan_windows(self, now):
        if not self.settings.data.get("window_play", True):
            self.plats = {}
            return
        try:
            raw = winplat.platforms()
        except Exception:
            raw = {}
        plats = {}
        self.win_rects = {}
        for hwnd, segs in raw.items():
            self.win_rects[hwnd] = (segs[0][3], segs[0][2])      # (창 왼쪽, 창 위) 물리 픽셀
            for i, (x1, x2, y, wl) in enumerate(segs):
                lx1, ly = self.to_logical(x1, y)
                lx2, _ = self.to_logical(x2, y)
                lwl, _ = self.to_logical(wl, y)
                plats[(hwnd, i)] = (lx1, lx2, ly, lwl)

        # 가림 상태가 바뀌어 구간 번호가 달라져도, 같은 창이면 계속 서 있게
        for pet in self.pets.values():
            b = pet.brain
            if b.on is not None and b.on not in plats:
                hwnd = b.on[0]
                for key, (x1, x2, y, wl) in plats.items():
                    if key[0] == hwnd and x1 - b.w * 0.3 <= b.cx <= x2 + b.w * 0.3:
                        b.on = key
                        break

        # 새로 열린 창 (최소화했다 다시 연 창 포함) → 조금 뒤 펫이 뛰어오름
        hwnds = {k[0] for k in plats}
        if self.seen_windows is not None:
            for h in hwnds - self.seen_windows:
                self.new_windows[h] = now + 0.6       # 창 열리는 애니메이션 끝날 때까지 기다림
        self.seen_windows = hwnds
        for h, at in list(self.new_windows.items()):
            if now < at:
                continue
            if now > at + 10:                         # 10초 동안 못 올라가면 포기
                del self.new_windows[h]
                continue
            keys = [k for k in plats if k[0] == h]
            if not keys:
                continue
            key = max(keys, key=lambda k: plats[k][1] - plats[k][0])
            x1, x2, y, _ = plats[key]
            mid = (x1 + x2) / 2
            jumped = 0
            for pet in sorted(self.pets.values(), key=lambda p: abs(p.brain.cx - mid)):
                if pet.brain.notice_platform(key, plats):
                    jumped += 1
                    if jumped >= 2 or random.random() < 0.6:
                        break
            if jumped:                                # 누가 뛰었으면 끝, 아니면 잠시 뒤 다시 시도
                del self.new_windows[h]
        self.plats = plats

    def follow_windows(self):
        """펫이 올라가 있는 창만 매 프레임 위치 확인 (전체 검색보다 훨씬 가벼움)"""
        hwnds = {pet.brain.on[0] for pet in self.pets.values() if pet.brain.on is not None}
        for h in hwnds:
            old = self.win_rects.get(h)
            r = winplat.window_rect(h)
            if r is None:                                    # 닫힘/최소화 → 발판 없애기 (펫이 떨어짐)
                self.plats = {k: v for k, v in self.plats.items() if k[0] != h}
                self.win_rects.pop(h, None)
                continue
            if old is None or (r[0], r[1]) == old:
                continue
            ox, oy = self.to_logical(*old)
            nx, ny = self.to_logical(r[0], r[1])
            dx, dy = nx - ox, ny - oy
            self.win_rects[h] = (r[0], r[1])
            for k, (x1, x2, y, wl) in list(self.plats.items()):
                if k[0] == h:
                    self.plats[k] = (x1 + dx, x2 + dx, y + dy, wl + dx)

    def set_window_play(self, on):
        self.settings.data["window_play"] = on
        self.settings.save()

    def set_hide_fullscreen(self, on):
        self.settings.data["hide_fullscreen"] = on
        self.settings.save()

    def toggle_snooze(self):
        now = time.time() - self.t0
        if now < self.snooze_until:
            self.snooze_until = 0.0
        else:
            self.snooze_until = now + 30 * 60
        self.snooze_action.setText("다시 보이기" if self.snooze_until else "30분 동안 숨기기")
        self.tick()

    def set_paused(self, paused):
        if paused == self.paused:
            return
        self.paused = paused
        for pet in self.pets.values():
            pet.setVisible(not paused)
        for _, win in self.snacks:
            win.setVisible(not paused)
        self.snooze_action.setText("다시 보이기" if self.snooze_until else "30분 동안 숨기기")

    def tick(self):
        now = time.time() - self.t0
        self.frame += 1

        # 전체화면(발표·영상·게임) 중이거나 '30분 숨기기' 중이면 쉬기
        if now - self.last_fs_check >= 1.0:
            self.last_fs_check = now
            self.fullscreen = self.settings.data.get("hide_fullscreen", True) and winplat.fullscreen_foreground()
        if self.snooze_until and now >= self.snooze_until:
            self.snooze_until = 0.0
        self.set_paused(self.fullscreen or now < self.snooze_until)
        if self.paused:
            self.set_interval(PAUSE_TICK_MS)
            return

        if self.settings.data.get("window_play", True):
            if now - self.last_scan >= SCAN_EVERY:
                self.last_scan = now
                self.scan_windows(now)
            else:
                self.follow_windows()
        elif self.plats:
            self.plats = {}

        c = QCursor.pos()
        mouse = (c.x(), c.y())
        pets = list(self.pets.values())
        brains = [p.brain for p in pets]
        for pet in pets:
            pet.think(now, mouse, brains, self.plats)
        resolve_contacts(brains, now)
        for pet in pets:
            pet.render()
        self.update_snacks(now)
        self.events(now, brains)

        busy = any(b.state in FAST_STATES or b.emotes or b.hop_v or b.squash > 0.05 for b in brains)
        self.set_interval(TICK_MS if busy or self.new_windows or self.snacks else IDLE_TICK_MS)
        if TRACE and self.frame % 15 == 0:
            try:
                with open(DATA_DIR / "trace.txt", "a", encoding="utf-8") as f:
                    pl = {f"{k[0]}:{k[1]}": tuple(round(v) for v in val) for k, val in self.plats.items()}
                    f.write(f"t={now:.1f} plats={pl}\n")
                    for name, pet in self.pets.items():
                        b = pet.brain
                        f.write(f"   {name} {b.state} cx={b.cx:.0f} cy={b.cy:.0f} h={b.h} on={b.on} "
                                f"vx={b.vx:.1f} vy={b.vy:.1f} leap={b.leap} area={b.area}\n")
            except Exception:
                pass

    def demo_poll(self):
        go = DATA_DIR / "demo_go"
        if not go.exists():
            return
        try:
            what = go.read_text(encoding="utf-8").strip() or "bump"
        except Exception:
            what = "bump"
        go.unlink(missing_ok=True)
        if what == "bump":
            self.demo_bump()
        elif what == "train":
            for p in self.pets.values():
                if p.brain.state not in ("air", "drag"):
                    p.brain.on = None
                    p.brain.set_state("idle", 9, 9)
            self.start_train()
        elif what == "snack":
            self.drop_snack()
        elif what.startswith("clock "):          # 예: clock 16:59:57 → 시계를 그 시각으로
            hh, mm, ss = (int(v) for v in what.split()[1].split(":"))
            real = datetime.datetime.now()
            want = real.replace(hour=hh, minute=mm, second=ss, microsecond=0)
            self.clock_offset = want - real
            self.done_events = {}

    def demo_bump(self):
        """시험 녹화용: 펫끼리 부딪히는 장면 연출"""
        brains = [p.brain for p in self.pets.values()]
        if len(brains) < 4:
            return
        area = screen_area(brains[0].cx, brains[0].cy)
        mid = (area[0] + area[2]) / 2
        a, b, c, d = brains[:4]
        for br in brains:
            br.meet_cool = 60                    # 인사 말고 부딪히기만
            br.angle = br.flat = 0
        for br, x, f in ((a, mid - 260, 1), (b, mid + 60, -1)):
            br.cx, br.facing, br.speed = x, f, 2.6
            br.set_state("walk", 6, 6)
        d.cx = mid + 330
        d.flat = 0.22
        d.set_state("sleep", 30, 30)            # 자고 있는 친구
        c.cx = mid - 80

        def throw():
            c.start_drag()
            c.cx, c.cy = mid + 150, area[3] - c.h / 2 - 115
            c.throw(10, -3)                      # 자는 친구 쪽으로 휙
        QTimer.singleShot(4500, throw)

    # ── 간식 ──
    def now(self):
        return time.time() - self.t0

    def drop_snack(self, x=None, food=None):
        if len(self.snacks) >= 3 or not self.pets:
            return
        now = self.now()
        brains = [p.brain for p in self.pets.values()]
        if x is None:
            ref = random.choice(brains)
            x = ref.cx + random.uniform(-300, 300)
        area = screen_area(x, QGuiApplication.primaryScreen().availableGeometry().center().y())
        x = min(max(x, area[0] + 40), area[2] - 40)
        sn = Snack(x, area[1] + 20, food or random.choice(FOODS))
        sn.born = now
        win = SnackWindow(sn)
        win.sync(now)
        if not self.paused:
            win.show()
        self.snacks.append((sn, win))
        for b in brains:
            if b.is_free() and b.snack is None:
                if b.state == "sleep":
                    b.flat = 0.0
                b.emote("ex", 0.9)
                b.go_snack(sn)

    def update_snacks(self, now):
        if not self.snacks:
            return
        keep = []
        for sn, win in self.snacks:
            area = screen_area(sn.x, sn.y)
            sn.update(now, area)
            if sn.gone:
                win.close()
                continue
            win.sync(now)
            keep.append((sn, win))
        self.snacks = keep

    # ── 기차놀이 ──
    def start_train(self):
        start_train([p.brain for p in self.pets.values()], self.now())

    # ── 시계 (퇴근임박 / 휴식 알림) ──
    def clock(self):
        return datetime.datetime.now() + self.clock_offset

    def free_brains(self, brains):
        return [b for b in brains if b.is_free()]

    def events(self, now, brains):
        if not brains:
            return
        # 가끔 저절로 기차놀이
        if now >= self.next_train:
            self.next_train = now + random.uniform(150, 360)
            if len(brains) >= 2 and random.random() < 0.7:
                start_train(brains, now)

        # 50분마다 쉬는 시간
        if now >= self.next_rest:
            if not self.settings.data.get("rest_alert", True):
                self.next_rest = now + 50 * 60
            else:
                free = self.free_brains(brains)
                if free:
                    self.next_rest = now + 50 * 60
                    first = random.choice(free)
                    first.stretch(random.choice(["50분 지났어요! 잠깐 쉬어요 ☕", "기지개 쭉~ 쉬었다 해요",
                                                 "눈 좀 쉬어 줘요 👀", "물 한 잔 마셔요 💧"]))
                    for b in free:
                        if b is not first and random.random() < 0.6:
                            b.stretch()
                else:
                    self.next_rest = now + 30

        # 퇴근임박 모드 (1초에 한 번만 확인)
        if now - self.last_clock_check < 1.0:
            return
        self.last_clock_check = now
        on = self.settings.data.get("offwork", True)
        dt = self.clock()
        weekday_ok = dt.weekday() < 5 or self.clock_offset != datetime.timedelta(0)
        hh, mm = (int(v) for v in self.settings.data.get("work_end", "18:00").split(":"))
        end = dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
        start = end - datetime.timedelta(hours=1)
        day = dt.date().isoformat()
        in_window = on and weekday_ok and start <= dt < end
        for b in brains:
            b.sleepy = in_window
        if in_window:
            mins = max(1, int((end - dt).total_seconds() // 60) + 1)
            if self.done_events.get("hour") != day:
                self.done_events["hour"] = day
                self.offwork_start(brains, mins)
                self.next_chat = now + random.uniform(240, 420)
            elif mins <= 10 and self.done_events.get("ten") != day:
                self.done_events["ten"] = day
                free = self.free_brains(brains) or brains
                random.choice(free).say("퇴근 10분 전! 슬슬 정리해요~", 4)
                self.next_chat = now + 180
            elif now >= self.next_chat:
                self.next_chat = now + random.uniform(300, 540)
                free = self.free_brains(brains)
                if free:
                    b = random.choice(free)
                    b.say(random.choice(OFFWORK_LINES).format(m=mins), 3.5)
                    if b.state == "sleep":
                        b.flat = 0.0
                        b.set_state("idle", 1, 2)
        if on and weekday_ok and end <= dt < end + datetime.timedelta(minutes=20) \
                and self.done_events.get("end") != day:
            self.done_events["end"] = day
            self.offwork_party(brains)

    def offwork_start(self, brains, mins):
        """퇴근 1시간 전: 다 같이 폴짝 + 간식 타임"""
        free = self.free_brains(brains) or brains
        lead = random.choice(free)
        lead.say(f"퇴근 {mins}분 전!" if mins < 60 else "퇴근 1시간 전!", 4)
        for b in free:
            b.flat = 0.0
            b.angle = 0.0
            b.hops_left = 2
            b.set_state("happy", 1.5, 2)
            if b is not lead:
                b.emote("ex", 1.0)
        QTimer.singleShot(2200, lambda: self.drop_snack(lead.cx + 200))
        others = [b for b in free if b is not lead]
        if others:
            QTimer.singleShot(2600, lambda: random.choice(others).say("당 충전 타임! 🍪", 3))

    def offwork_party(self, brains):
        """퇴근 시간: 다 같이 춤추며 축하"""
        lead = random.choice(brains)
        for b in brains:
            if b.state in ("drag", "climb", "hang"):
                continue
            b.flat = 0.0
            b.snack = None
            b.set_state("dance", 6, 8)
            b.emote("party", 2.0)
            b.emote("✦", 0.8, dx=-20, style="burst")
            b.emote("✦", 0.8, dx=20, style="burst")
            b.say("퇴근이다!! 🎉" if b is lead else random.choice(["수고했어요 ♥", "오늘도 최고!", "집에 가자~"]), 4.5)

    def set_option(self, key, value):
        self.settings.data[key] = value
        self.settings.save()

    def set_interval(self, ms):
        if self.timer.interval() != ms:
            self.timer.setInterval(ms)

    def set_enabled(self, name, on):
        self.settings.pet(name)["enabled"] = on
        self.settings.save()
        if on:
            self.spawn(name)
        elif name in self.pets:
            self.pets.pop(name).close()
        self.window.sync_checks()

    def set_all(self, on):
        for name in self.pet_names():
            self.set_enabled(name, on)

    def set_scale(self, name, value):
        self.settings.pet(name)["scale"] = value
        self.settings.save()
        if name in self.pets:
            self.pets[name].update_scale()

    def set_global_scale(self, value):
        self.settings.data["global_scale"] = value
        self.settings.save()
        for pet in self.pets.values():
            pet.update_scale()

    def delete_pet(self, name):
        if QMessageBox.question(self.window, "펫 삭제", f"'{name}' 펫을 삭제할까요?") != QMessageBox.Yes:
            return
        if name in self.pets:
            self.pets.pop(name).close()
        (PET_DIR / f"{name}.png").unlink(missing_ok=True)
        self.settings.data["pets"].pop(name, None)
        self.settings.save()
        self.window.rebuild()

    def add_images(self, paths):
        worker = BackgroundRemover(paths, self.settings.data.get("split", True))
        worker.progress.connect(self.window.status.setText)
        worker.finished_one.connect(self.on_added)
        worker.failed.connect(lambda f, err: QMessageBox.warning(self.window, "추가 실패", f"{f}\n\n{err}"))
        worker.finished.connect(lambda: self.on_worker_done(worker))
        self.workers.append(worker)
        worker.start()

    def on_worker_done(self, worker):
        self.window.status.setText("완료! ✨")
        QTimer.singleShot(3000, lambda: self.window.status.setText(""))
        if worker in self.workers:
            self.workers.remove(worker)
        if not self.workers:
            QTimer.singleShot(30_000, self.release_model)

    def release_model(self):
        """배경 제거가 끝나면 AI 모델(수백 MB)을 메모리에서 내림"""
        if self.workers:
            return
        mod = sys.modules.get("bgremove")
        if mod is not None:
            mod.release()

    def on_added(self, name):
        self.settings.pet(name)
        self.settings.save()
        self.spawn(name)
        self.window.rebuild()

    def quit(self):
        self.settings.save()
        self.tray.hide()
        for pet in self.pets.values():
            pet.close()
        self.qapp.quit()


def install_error_log():
    """오류가 나면 %APPDATA%\\DesktopPet\\error.log에 기록 (창 없는 exe라 오류가 안 보이므로)"""
    import traceback

    def hook(etype, value, tb):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(DATA_DIR / "error.log", "a", encoding="utf-8") as f:
                f.write(time.strftime("[%Y-%m-%d %H:%M:%S]\n"))
                f.write("".join(traceback.format_exception(etype, value, tb)) + "\n")
        except Exception:
            pass
    sys.excepthook = hook


def main():
    install_error_log()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName(APP_NAME)
    qapp.setFont(QFont("Malgun Gothic", 9))
    init_emote_style()
    winplat.lower_priority()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    single = QLockFile(str(DATA_DIR / "running.lock"))
    if not single.tryLock(100):
        QMessageBox.information(None, APP_NAME, "이미 실행 중이에요.\n작업표시줄 오른쪽 발바닥 아이콘을 눌러 보세요.")
        return

    app = PetApp(qapp)
    qapp.exec()
    single.unlock()


if __name__ == "__main__":
    main()
