# -*- coding: utf-8 -*-
"""펫의 움직임/행동 로직 (화면 그리기와 분리 → 따로 시험 가능)

좌표: 화면 픽셀, (cx, cy) = 펫 그림의 중심, angle = 시계방향 회전(도)
"""
import math
import random

GRAVITY = 0.9

# 다음 행동 고르기 가중치
BEHAVIORS = {
    "walk": 30, "run": 8, "idle": 18, "hop": 8, "jump": 6, "flip": 4,
    "dance": 6, "sleep": 5, "look": 6, "chase": 4, "climb": 6, "sit": 6,
    "window": 12,   # 열린 창 위로 뛰어오르기 (갈 수 있는 창이 있을 때만)
}

# 바닥(화면 아래나 창 위)에 서 있는 상태들
GROUND_STATES = ("idle", "walk", "run", "sit", "sleep", "hop", "dance", "look", "chase",
                 "to_wall", "meet", "happy", "dizzy", "crouch")

EMOTE = {"heart": "♥", "note": "♪", "z": "z", "q": "?", "ex": "!", "star": "★", "sweat": "💦",
         "bonk": "콩!", "boing": "뿅!", "angry": "💢"}

# 서로 밀어낼 수 있는 상태 / 앞으로 걸어가는 상태
CONTACT_SKIP = ("drag", "climb", "hang")
MOVING = ("walk", "run", "chase", "to_wall", "hop")


class PetBrain:
    def __init__(self, w, h, area, rng=None):
        self.rng = rng or random.Random()
        self.w, self.h = w, h
        l, t, r, b = area
        self.cx = self.rng.uniform(l + w, max(l + w + 1, r - w))
        self.cy = max(t + h, b - 350)       # 살짝 위에서 떨어지며 등장
        self.vx = self.rng.uniform(-2, 2)
        self.vy = 0.0
        self.angle = 0.0
        self.spin = 0.0
        self.facing = self.rng.choice([-1, 1])
        self.state = "air"
        self.until = 0.0
        self.speed = 1.5
        self.phase = self.rng.uniform(0, 6.28)
        self.squash = 0.0           # 착지할 때 납작
        self.flat = 0.0             # 잘 때/앉을 때 살짝 납작 (목표값)
        self.flat_now = 0.0
        self.bob = 0.0              # 그림만 위로 들썩
        self.hop_y = 0.0            # 깡충 높이
        self.hop_v = 0.0
        self.hops_left = 0
        self.wall = 0               # 벽타기: -1 왼쪽, 1 오른쪽
        self.target = 0.0
        self.emotes = []            # [글자, 시작시각, 지속, x흔들림]
        self.last_emote = 0.0
        self.bump_until = 0.0       # 부딪힘 쿨타임 (시각)
        self.strokes = 0
        self.meet_cool = 0.0
        self.partner = None
        self.idle_streak = 0
        self.now = 0.0
        self.history = []           # 시험용 기록
        self.plats = {}             # 창 발판: id -> (x1, x2, y, 창왼쪽x)
        self.on = None              # 지금 올라가 있는 창 발판 id
        self.on_wl = 0.0
        self.leap = None            # (발판id, 목표x)
        self.edge_decided = False
        self.area = None

    # ───── 공통 ─────
    def set_size(self, w, h):
        self.w, self.h = w, h

    def ground(self, area):
        p = self.plats.get(self.on) if self.on is not None else None
        if p is not None:
            return p[2] - self.h / 2
        return area[3] - self.h / 2

    def fall_off(self, surprised=True):
        """발판이 사라지거나 끝으로 걸어나가면 떨어짐"""
        self.on = None
        self.state = "air"
        self.log("fall")
        self.flat = 0.0
        self.spin = 0.0
        if surprised:
            self.vx, self.vy = 0.0, 0.0
            self.emote("ex", 0.9)

    def emote(self, kind, dur=1.4, dx=None, style="rise"):
        """style: rise(머리 위로 떠오름) / burst(그 자리에서 별이 톡 터짐)"""
        if dx is None:
            dx = self.rng.uniform(-8, 8)
        self.emotes.append([EMOTE.get(kind, kind), self.now, dur, dx, style])
        if style == "rise":
            self.last_emote = self.now

    def set_state(self, state, lo=1.0, hi=3.0):
        self.state = state
        self.until = self.now + self.rng.uniform(lo, hi)
        self.log(state)

    def log(self, name):
        self.history.append(name)
        if len(self.history) > 200:
            del self.history[:100]

    def busy(self):
        return self.state in ("air", "drag", "climb", "hang", "dizzy", "meet", "happy")

    # ───── 매 프레임 ─────
    def update(self, now, area, mouse=None, others=(), plats=None):
        self.now = now
        if plats is not None:
            self.plats = plats
        self.area = area
        # 올라가 있는 창이 움직이면 같이 이동, 없어지면 떨어짐
        if self.on is not None:
            p = self.plats.get(self.on)
            if p is None:
                self.fall_off()
            else:
                self.cx += p[3] - self.on_wl
                self.on_wl = p[3]
                if not (p[0] - self.w * 0.3 <= self.cx <= p[1] + self.w * 0.3):
                    self.fall_off()
        self.emotes = [e for e in self.emotes if now - e[1] < e[2]]
        self.phase += 0.08
        self.squash *= 0.85
        self.flat_now += (self.flat - self.flat_now) * 0.1
        self.bob = 0.0
        self.meet_cool = max(0.0, self.meet_cool - 0.03)
        l, t, r, b = area
        ground = self.ground(area)

        getattr(self, "s_" + self.state, self.s_idle)(area, ground, mouse, others)

        if self.state in ("air", "drag", "climb", "hang"):
            self.on = None
        elif self.on is not None and self.state in GROUND_STATES:
            # 창 끝으로 걸어나가면 떨어짐
            p = self.plats.get(self.on)
            if p is not None and not (p[0] - self.w * 0.15 <= self.cx <= p[1] + self.w * 0.15):
                moving = self.state in ("walk", "run", "chase", "to_wall", "hop")
                self.fall_off(surprised=False)
                self.vx = self.facing * (min(self.speed, 3.0) if moving else 1.0)
                self.vy = -2.0

        # 깡충 (hop, happy, meet, dance에서 사용)
        if self.hop_y < 0 or self.hop_v != 0:
            self.hop_v += GRAVITY * 0.8
            self.hop_y += self.hop_v
            if self.hop_y >= 0:
                self.hop_y, self.hop_v = 0.0, 0.0
                self.squash = max(self.squash, 0.35)

        # 화면 밖으로 나가지 않게 (드래그 중 제외)
        if self.state not in ("drag", "climb", "hang"):
            half = max(self.w, self.h) / 2 if abs(self.angle) > 20 else self.w / 2
            self.cx = min(max(self.cx, l + half), r - half)
            if self.state != "air":
                self.cy = self.ground(area)

    # ───── 행동들 ─────
    def choose_next(self, mouse):
        self.flat = 0.0
        weights = dict(BEHAVIORS)
        weights["sleep"] += self.idle_streak * 4
        if mouse is None:
            weights["chase"] = 0
        targets = self.reachable_platforms()
        if not targets:
            weights["window"] = 0
        name = self.rng.choices(list(weights), list(weights.values()))[0]
        self.idle_streak = self.idle_streak + 1 if name in ("idle", "sit") else 0

        if name in ("walk", "run"):
            if self.rng.random() < 0.4:
                self.facing = -self.facing
            self.speed = self.rng.uniform(0.8, 1.8) if name == "walk" else self.rng.uniform(3.5, 5.5)
            self.set_state(name, 2, 7) if name == "walk" else self.set_state(name, 1.2, 3)
        elif name == "idle":
            self.set_state("idle", 1.5, 4)
        elif name == "sit":
            self.flat = 0.12
            self.set_state("sit", 3, 7)
        elif name == "hop":
            self.hops_left = self.rng.randint(3, 6)
            self.set_state("hop", 10, 10)
        elif name in ("jump", "flip"):
            self.jump(flip=(name == "flip"))
        elif name == "dance":
            self.set_state("dance", 2.5, 5)
            self.emote("note")
        elif name == "sleep":
            self.flat = 0.22
            self.set_state("sleep", 6, 14)
            self.emote("z", 1.8)
        elif name == "look":
            self.set_state("look", 1.8, 3)
            self.emote("q")
        elif name == "chase":
            self.set_state("chase", 3, 6)
            self.emote("ex")
        elif name == "window":
            self.leap_to(self.rng.choice(targets))
        elif name == "climb":
            self.facing = self.rng.choice([-1, 1])
            self.speed = self.rng.uniform(2, 3)
            self.set_state("to_wall", 15, 15)

    # ───── 창 위로 뛰어오르기 ─────
    def reach_x(self, p):
        """그 발판으로 뛸 수 있으면 착지할 x, 아니면 None"""
        x1, x2, y, _ = p
        if x2 - x1 < self.w * 0.9:
            return None
        feet = self.cy + self.h / 2
        up = feet - y
        lo, hi = x1 + self.w / 2, x2 - self.w / 2
        tx = min(max(self.cx + self.rng.uniform(-60, 60), lo), hi) if lo < hi else (x1 + x2) / 2
        top = self.area[1] if self.area else -1e9
        if y - self.h - 40 < top:          # 창 위에 펫이 설 자리가 없음 (최대화된 창 등)
            return None
        if 15 < abs(up) and -450 < up < 560 and abs(tx - self.cx) < 900:
            return tx
        return None

    def reachable_platforms(self):
        return [pid for pid, p in self.plats.items() if pid != self.on and self.reach_x(p) is not None]

    def leap_to(self, pid):
        p = self.plats.get(pid)
        tx = self.reach_x(p) if p else None
        if tx is None:
            return False
        self.leap = (pid, tx)
        self.facing = 1 if tx > self.cx else -1
        self.angle = 0
        self.flat = 0.25                 # 웅크리기
        self.set_state("crouch", 0.35, 0.55)
        self.emote("ex", 0.8)
        return True

    def notice_platform(self, pid, plats=None):
        """새 창이 열렸을 때: 놀고 있으면 그 창으로 뛰어오름"""
        if plats is not None:
            self.plats = plats
        if self.state in ("idle", "walk", "run", "sit", "look", "hop", "dance", "chase"):
            return self.leap_to(pid)
        return False

    def s_crouch(self, area, ground, mouse, others):
        self.bob = 0
        if self.now < self.until:
            return
        pid, tx = self.leap
        p = self.plats.get(pid)
        self.flat = 0.0
        if p is None:
            self.set_state("look", 1, 2)
            self.emote("q")
            return
        tx = min(max(tx, p[0] + self.w / 2), p[1] - self.w / 2) if p[1] - p[0] > self.w else (p[0] + p[1]) / 2
        feet = self.cy + self.h / 2
        rise = max(0.0, feet - p[2]) + 30            # 창보다 30px 높이까지 솟았다가 내려앉음
        vy0 = -math.sqrt(2 * GRAVITY * rise)
        disp = p[2] - feet
        t = (-vy0 + math.sqrt(max(vy0 * vy0 + 2 * GRAVITY * disp, 0.0))) / GRAVITY
        self.vy = vy0
        self.vx = (tx - self.cx) / max(t, 1.0)
        self.facing = 1 if self.vx >= 0 else -1
        self.spin = self.facing * 360 / t if (rise > 150 and self.rng.random() < 0.3) else 0.0
        self.squash = -0.5                           # 쭉 늘어나며 도약
        self.state = "air"
        self.on = None
        self.log("leap")

    def jump(self, flip=False, power=None):
        self.flat = 0.0
        self.state = "air"
        self.log("flip" if flip else "jump")
        self.vy = -(power or self.rng.uniform(12, 16))
        self.vx = self.facing * self.rng.uniform(1, 3.5)
        air = 2 * -self.vy / GRAVITY
        self.spin = self.facing * 360 / air if flip else 0.0
        self.squash = 0.4

    def s_idle(self, area, ground, mouse, others):
        self.bob = (math.sin(self.phase) + 1) * 1.0
        self.look_at_mouse(mouse)
        self.try_meet(others)
        if self.now > self.until:
            self.choose_next(mouse)

    def s_sit(self, area, ground, mouse, others):
        self.bob = (math.sin(self.phase * 0.6) + 1) * 0.6
        self.look_at_mouse(mouse)
        if self.now > self.until:
            self.choose_next(mouse)

    def look_at_mouse(self, mouse):
        if mouse is None:
            return
        dx = mouse[0] - self.cx
        if abs(dx) < 250 and abs(mouse[1] - self.cy) < 250:
            self.facing = 1 if dx > 0 else -1
            if self.now - self.last_emote > 6 and self.rng.random() < 0.01:
                self.emote("q")

    def s_walk(self, area, ground, mouse, others):
        l, t, r, b = area
        fast = self.state == "run"
        self.cx += self.facing * self.speed
        self.phase += 0.25 if fast else 0.14
        self.bob = abs(math.sin(self.phase * (1.6 if fast else 1.2))) * (6 if fast else 4)
        if fast and self.rng.random() < 0.02:
            self.emote("sweat", 0.8)
        if self.cx <= l + self.w / 2 or self.cx >= r - self.w / 2:
            self.facing = 1 if self.cx <= l + self.w / 2 else -1
        self.edge_check()
        self.try_meet(others)
        if self.now > self.until:
            self.choose_next(mouse)

    s_run = s_walk

    def edge_check(self):
        """창 위를 걷다가 끝에 다다르면: 대부분 돌아서고, 가끔 뛰어내림"""
        p = self.plats.get(self.on) if self.on is not None else None
        if p is None:
            return
        near = (self.facing > 0 and self.cx > p[1] - self.w * 0.45) or \
               (self.facing < 0 and self.cx < p[0] + self.w * 0.45)
        if near and not self.edge_decided:
            self.edge_decided = True
            if self.rng.random() < 0.75:
                self.facing = -self.facing
            else:
                self.emote("ex", 0.6)
        elif not near:
            self.edge_decided = False

    def s_hop(self, area, ground, mouse, others):
        l, t, r, b = area
        if self.hop_y == 0 and self.hop_v == 0:
            if self.hops_left <= 0:
                self.set_state("idle", 0.8, 2)
                return
            self.hops_left -= 1
            self.hop_v = -self.rng.uniform(6, 9)
            self.edge_check()
        if self.hop_y < 0:
            self.cx += self.facing * 1.6
        if self.cx <= l + self.w / 2 or self.cx >= r - self.w / 2:
            self.facing = -self.facing

    def s_dance(self, area, ground, mouse, others):
        self.phase += 0.12
        self.angle = 14 * math.sin(self.phase * 1.5)
        self.bob = abs(math.sin(self.phase * 1.5)) * 5
        if int(self.phase * 1.5 / math.pi) % 4 == 0 and self.rng.random() < 0.05:
            self.facing = -self.facing
        if self.now - self.last_emote > 1.0:
            self.emote("note")
        if self.now > self.until:
            self.angle = 0
            self.set_state("idle", 1, 2)

    def s_sleep(self, area, ground, mouse, others):
        self.bob = 0
        self.flat = 0.2 + 0.04 * math.sin(self.phase * 0.5)
        if self.now - self.last_emote > 1.5:
            self.emote("z", 1.8)
        if self.now > self.until:
            self.flat = 0
            self.emote("ex", 0.8)
            self.set_state("idle", 1, 2)

    def s_look(self, area, ground, mouse, others):
        if self.rng.random() < 0.04:
            self.facing = -self.facing
        self.bob = (math.sin(self.phase) + 1) * 0.8
        if self.now > self.until:
            self.choose_next(mouse)

    def s_chase(self, area, ground, mouse, others):
        if mouse is None:
            self.set_state("idle", 1, 2)
            return
        dx = mouse[0] - self.cx
        self.phase += 0.25
        if abs(dx) > self.w * 0.3:
            self.facing = 1 if dx > 0 else -1
            self.cx += self.facing * 4.5
            self.bob = abs(math.sin(self.phase * 1.6)) * 6
        else:
            self.bob = abs(math.sin(self.phase)) * 2
            if mouse[1] < self.cy - self.h and self.rng.random() < 0.04:
                self.jump(power=13)               # 마우스가 위에 있으면 점프해서 잡으려 함
                return
        if self.now > self.until:
            self.choose_next(mouse)

    # ── 벽타기 ──
    def s_to_wall(self, area, ground, mouse, others):
        l, t, r, b = area
        self.cx += self.facing * self.speed
        self.phase += 0.2
        self.bob = abs(math.sin(self.phase * 1.4)) * 4
        edge_l, edge_r = l + self.w / 2, r - self.w / 2
        if self.cx <= edge_l or self.cx >= edge_r:
            self.wall = -1 if self.cx <= edge_l else 1
            self.cx = (l + self.h / 2) if self.wall < 0 else (r - self.h / 2)
            self.angle = 90 * self.wall * -1        # 발이 벽 쪽을 향하도록
            self.target = self.rng.uniform(t + self.w, ground - self.w)
            self.speed = self.rng.uniform(1.0, 1.8)
            self.state = "climb"
            self.log("climb")
        elif self.now > self.until:
            self.choose_next(mouse)

    def s_climb(self, area, ground, mouse, others):
        l, t, r, b = area
        self.cy -= self.speed
        self.phase += 0.2
        self.bob = abs(math.sin(self.phase * 1.3)) * 3
        if self.cy <= self.target or self.cy <= t + self.w / 2:
            self.set_state("hang", 1, 3)

    def s_hang(self, area, ground, mouse, others):
        self.bob = 0
        if self.now > self.until:
            l, t, r, b = area
            if self.rng.random() < 0.5:
                # 벽을 박차고 뛰어내림 (공중제비)
                self.facing = -self.wall
                self.vx = -self.wall * self.rng.uniform(3, 6)
                self.vy = -self.rng.uniform(3, 7)
                self.spin = -self.wall * 9
            else:
                # 그냥 손 놓고 떨어짐
                self.vx = -self.wall * 1.5
                self.vy = 0
                self.spin = self.wall * 3
                self.emote("ex", 0.8)
            self.cx += -self.wall * (self.h - self.w) / 2
            self.wall = 0
            self.state = "air"

    # ── 공중 ──
    def s_air(self, area, ground, mouse, others):
        l, t, r, b = area
        prev_feet = self.cy + self.h / 2
        self.vy += GRAVITY
        self.cx += self.vx
        self.cy += self.vy
        self.vx *= 0.995
        self.angle += self.spin
        if self.cx < l + self.w / 2 or self.cx > r - self.w / 2:
            self.vx = -self.vx * 0.6
            self.spin = -self.spin * 0.6
            self.cx = min(max(self.cx, l + self.w / 2), r - self.w / 2)
        if self.cy < t + self.h / 2 and self.vy < 0:
            self.cy = t + self.h / 2
            self.vy = -self.vy * 0.3
        # 떨어지는 중이면 아래로 지나치는 창 윗변에 착지
        land_y, land_id = None, None
        feet = self.cy + self.h / 2
        if self.vy > 0:
            for pid, (x1, x2, y, wl) in self.plats.items():
                if self.vy > 0 and prev_feet <= y + 1 and feet >= y and \
                        x1 - self.w * 0.2 <= self.cx <= x2 + self.w * 0.2:
                    if land_y is None or y < land_y:
                        land_y, land_id = y, pid
        if land_y is None and self.cy >= ground:
            land_y = ground + self.h / 2
        if land_y is not None:
            self.cy = land_y - self.h / 2
            if land_id is not None:
                self.on = land_id
                self.on_wl = self.plats[land_id][3]
            hard = self.vy > 28
            spun = abs(self.spin) > 4 and abs((self.angle + 180) % 360 - 180) > 60
            if self.vy > 9:
                self.vy = -self.vy * 0.35        # 통 튕김
                self.vx *= 0.6
                self.squash = 1.0
                self.spin *= 0.5
                if hard or spun:
                    self.dizzy_next = True
                return
            self.vy = self.vx = self.spin = 0
            self.angle = 0
            self.squash = max(self.squash, 0.6)
            self.state = "idle"     # 아래 상태 정리 전에 air에서 벗어나 발판 유지
            if getattr(self, "dizzy_next", False):
                self.dizzy_next = False
                self.set_state("dizzy", 2, 3)
                self.emote("star", 2.5)
            else:
                self.set_state("idle", 0.5, 1.5)
        # 착지 직전에 각도 정리
        if self.spin == 0 and self.angle:
            self.angle *= 0.8

    def s_dizzy(self, area, ground, mouse, others):
        self.angle = 10 * math.sin(self.phase * 4)
        if self.now > self.until:
            self.angle = 0
            self.set_state("idle", 1, 2)

    # ── 다른 펫과 만나기 ──
    def try_meet(self, others):
        if self.meet_cool > 0:
            return
        for o in others:
            if o is self or o.busy() or o.meet_cool > 0 or o.state == "sleep":
                continue
            if abs(o.cx - self.cx) < (self.w + o.w) / 2 + 10 and abs(o.cy + o.h / 2 - self.cy - self.h / 2) < 5:
                if self.rng.random() < 0.45:          # 이번엔 인사 안 하고 그냥 콩! 부딪히기
                    self.meet_cool = o.meet_cool = 8
                    return
                for a, bb in ((self, o), (o, self)):
                    a.facing = 1 if bb.cx > a.cx else -1
                    a.flat = 0
                    a.angle = 0
                    a.set_state("meet", 1.8, 2.5)
                    a.meet_cool = 15
                    a.hops_left = 2
                    a.emote("heart", 1.6)
                return

    def s_meet(self, area, ground, mouse, others):
        if self.hop_y == 0 and self.hop_v == 0 and self.hops_left > 0:
            self.hops_left -= 1
            self.hop_v = -6
        if self.now - self.last_emote > 0.7:
            self.emote("heart")
        if self.now > self.until:
            self.facing = -self.facing
            self.speed = 1.5
            self.set_state("walk", 2, 4)

    def s_happy(self, area, ground, mouse, others):
        self.angle = 8 * math.sin(self.phase * 3)
        if self.hop_y == 0 and self.hop_v == 0 and self.hops_left > 0:
            self.hops_left -= 1
            self.hop_v = -7
        if self.now - self.last_emote > 0.4:
            self.emote("heart")
        if self.now > self.until:
            self.angle = 0
            self.set_state("idle", 1, 2)

    def s_drag(self, area, ground, mouse, others):
        pass

    # ───── 마우스 상호작용 ─────
    def poke(self):
        """더블클릭"""
        if self.state in ("sleep", "sit"):
            self.flat = 0
            self.emote("ex", 0.9)
            self.jump(power=9)
        elif self.state not in ("air", "drag"):
            self.jump(flip=self.rng.random() < 0.5)

    def stroke(self):
        """마우스로 쓰다듬기 (버튼 안 누르고 펫 위에서 움직임)"""
        if self.state in ("air", "drag", "climb", "hang", "happy"):
            return
        self.strokes += 1
        if self.strokes > 25:
            self.strokes = 0
            self.flat = 0
            self.hops_left = 3
            self.set_state("happy", 2, 3)
            self.emote("heart")

    def start_drag(self):
        self.state = "drag"
        self.flat = 0
        self.wall = 0
        self.spin = 0
        self.emote("ex", 0.8)

    def drag_to(self, cx, cy, mvx):
        self.cx, self.cy = cx, cy
        # 집어 들면 대롱대롱 흔들림
        target = max(-45, min(45, -mvx * 3))
        self.angle += (target - self.angle) * 0.3

    def throw(self, vx, vy):
        self.vx, self.vy = vx, vy
        self.spin = vx * 1.2 if abs(vx) > 8 else 0
        if abs(vx) > 1:
            self.facing = 1 if vx > 0 else -1
        if abs(vx) + abs(vy) > 35:
            self.dizzy_next = True
        self.state = "air"
        self.log("thrown")


# ───────────────────── 펫끼리 부딪히기 ─────────────────────
def bump(p, away, now, power=1.0, word=None):
    """away 쪽으로 콩 튕겨 나감"""
    was_sleeping = p.state == "sleep"
    p.flat = 0.0
    p.angle = 0.0
    p.state = "air"
    p.log("bump")
    p.vx = away * p.rng.uniform(2.3, 3.3) * power
    p.vy = -p.rng.uniform(5.0, 6.5) * power
    p.spin = away * 4 * power if power > 1.2 else 0.0
    p.squash = 0.9
    p.facing = -away                      # 부딪힌 친구를 바라보며 뒤로 콩
    p.bump_until = now + 2.5
    if was_sleeping:
        p.emote("angry", 1.4)             # 자다가 맞으면 💢
    elif word:
        p.emote(word, 1.1)
    if power > 1.3 and p.rng.random() < 0.5:
        p.dizzy_next = True


def burst(p, side, now):
    """부딪힌 자리에서 반짝이 톡"""
    p.emote("✦", 0.6, dx=side * p.w * 0.45, style="burst")


def resolve_contacts(brains, now):
    """펫끼리 겹치지 않게 밀어내고, 부딪히면 콩! 효과"""
    n = len(brains)
    for i in range(n):
        a = brains[i]
        for j in range(i + 1, n):
            b = brains[j]
            if a.state in CONTACT_SKIP or b.state in CONTACT_SKIP:
                continue
            dx = b.cx - a.cx
            side = 1 if dx > 0 else -1 if dx < 0 else a.rng.choice([-1, 1])   # b가 a의 어느 쪽에 있나
            a_air, b_air = a.state == "air", b.state == "air"

            if not a_air and not b_air:
                # 같은 바닥(화면 바닥 또는 같은 창) 위에 서 있을 때만
                if a.on != b.on or abs((a.cy + a.h / 2) - (b.cy + b.h / 2)) > 4:
                    continue
                overlap = (a.w + b.w) / 2 * 0.8 - abs(dx)
                if overlap <= 0:
                    continue
                a_push = a.state in MOVING and a.facing == side
                b_push = b.state in MOVING and b.facing == -side
                if (a_push or b_push) and now > a.bump_until and now > b.bump_until:
                    power = 1.4 if (a.state == "run" or b.state == "run") else 1.0
                    first = a if a_push else b
                    bump(a, -side, now, power, "bonk" if first is a else None)
                    bump(b, side, now, power, "bonk" if first is b else None)
                    burst(a, side, now)
                else:
                    step = min(overlap / 2, 1.2)  # 살살 밀어내기
                    a.cx -= side * step
                    b.cx += side * step
            else:
                # 공중에서 날아와 부딪힘 (던졌거나 점프하다가)
                if abs(dx) > (a.w + b.w) / 2 * 0.7 or abs(b.cy - a.cy) > (a.h + b.h) / 2 * 0.7:
                    continue
                if now < a.bump_until or now < b.bump_until:
                    continue
                if math.hypot(a.vx - b.vx, a.vy - b.vy) < 6:
                    continue
                for p, away in ((a, -side), (b, side)):
                    if p.state == "air":
                        p.vx = away * max(2.5, abs(p.vx) * 0.4)
                        p.vy = min(p.vy, -3.0)
                        p.spin = away * 6
                        p.bump_until = now + 1.5
                        p.emote("boing", 1.0)
                    else:
                        bump(p, away, now, 1.5, "ex")
                burst(a, side, now)
