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
                 "to_wall", "meet", "happy", "dizzy", "crouch", "go_snack", "eat", "train", "stretch")

EMOTE = {"heart": "♥", "note": "♪", "z": "z", "q": "?", "ex": "!", "star": "★", "sweat": "💦",
         "bonk": "콩!", "boing": "뿅!", "angry": "💢", "yum": "냠", "yawn": "하암", "party": "🎉"}

# 서로 밀어낼 수 있는 상태 / 앞으로 걸어가는 상태
CONTACT_SKIP = ("drag", "climb", "hang")
MOVING = ("walk", "run", "chase", "to_wall", "hop", "go_snack")
# 펫이 바로 다른 일을 시작해도 되는 (한가한) 상태
FREE_STATES = ("idle", "walk", "run", "sit", "look", "hop", "chase", "dance", "sleep")


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
        self.bubble = None          # 말풍선 [글, 시작, 지속]
        self.snack = None           # 쫓아가는 간식
        self.train = None           # 기차놀이 중이면 Train
        self.sleepy = False         # 퇴근임박: 졸림
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

    def say(self, text, dur=3.0):
        self.bubble = [text, self.now, dur]

    def is_free(self):
        return self.state in FREE_STATES

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
        if self.bubble and now - self.bubble[1] > self.bubble[2]:
            self.bubble = None
        if self.state != "train":
            self.train = None
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
        if self.sleepy:                           # 퇴근임박: 자꾸 졸고 하품
            weights["sleep"] += 14
            weights["sit"] += 8
            weights["run"] = 2
            if self.rng.random() < 0.25:
                self.emote("yawn", 1.6)
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
        if self.snack is not None and not self.snack.eaten:
            self.go_snack(self.snack)
            return
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
                same_train = a.train is not None and a.train is b.train
                # 기차랑 마주친 한가한 펫 → 꼬리 칸에 탑승
                if not same_train and (a.train is None) != (b.train is None):
                    tr, other = (a.train, b) if a.train is not None else (b.train, a)
                    near = (a.w + b.w) / 2 + 12 - abs(dx)
                    if near > 0 and other.state in FREE_STATES and other.state != "sleep" \
                            and other.snack is None and other.on is None and tr.leader is not None:
                        if tr.join(other, now):
                            continue
                overlap = (a.w + b.w) / 2 * 0.8 - abs(dx)
                if overlap <= 0:
                    continue
                if same_train and a.train.turning:
                    continue                          # 대장이 머리 위로 넘어가는 중
                a_push = a.state in MOVING and a.facing == side
                b_push = b.state in MOVING and b.facing == -side
                if same_train:
                    a_push = b_push = False           # 기차 칸끼리는 밀기만
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


# ───────────────────── 간식 ─────────────────────
class Snack:
    """화면에 떨어지는 간식. 펫들이 달려가서 먼저 닿은 펫이 먹음"""
    def __init__(self, x, y, food):
        self.x, self.y, self.vy = x, y, 0.0
        self.food = food
        self.landed = False
        self.eaten = False
        self.eat_t = None
        self.gone = False

    def update(self, now, area):
        if not self.landed:
            self.vy += GRAVITY * 0.8
            self.y += self.vy
            ground = area[3] - 14
            if self.y >= ground:
                self.y = ground
                if self.vy > 6:
                    self.vy = -self.vy * 0.35   # 통 튕김
                else:
                    self.vy = 0.0
                    self.landed = True
        if self.eat_t is not None and now - self.eat_t > 2.4:
            self.gone = True
        if not self.eaten and self.landed and self.eat_t is None and getattr(self, "born", now) + 40 < now:
            self.gone = True                   # 아무도 안 먹으면 40초 뒤 사라짐


def _go_snack(self, snack):
    self.snack = snack
    self.flat = 0.0
    self.angle = 0.0
    self.set_state("go_snack", 20, 20)


def _s_go_snack(self, area, ground, mouse, others):
    sn = self.snack
    if sn is None or sn.eaten or sn.gone:
        self.snack = None
        self.emote("q", 1.2)
        if sn is not None and self.rng.random() < 0.4:
            self.say("내 간식…", 2.2)
        self.set_state("look", 1.2, 2)
        return
    dx = sn.x - self.cx
    if abs(dx) < self.w * 0.3:
        if self.on is not None:               # 창 위에 있으면 폴짝 내려감
            self.fall_off(surprised=False)
            self.vx, self.vy = self.facing * 1.5, -4.0
            return
        if sn.landed:
            sn.eaten = True
            sn.eat_t = self.now
            self.set_state("eat", 2.4, 2.4)
            self.emote("yum", 0.9)
        return
    self.facing = 1 if dx > 0 else -1
    step = min(abs(dx), 4.2)
    self.cx += self.facing * step
    self.phase += 0.25
    self.bob = abs(math.sin(self.phase * 1.6)) * 6
    self.edge_decided = True                  # 간식 쫓을 땐 창 끝에서도 안 돌아섬
    if self.now > self.until:
        self.snack = None
        self.set_state("idle", 1, 2)


def _s_eat(self, area, ground, mouse, others):
    self.phase += 0.3
    self.flat = 0.07 * abs(math.sin(self.phase * 2.5))   # 오물오물
    if self.now - self.last_emote > 0.7:
        self.emote("yum", 0.8)
    if self.now > self.until:
        self.flat = 0.0
        self.snack = None
        self.emote("heart", 1.4)
        if self.rng.random() < 0.5:
            self.say(self.rng.choice(["맛있다!", "냠냠 최고", "배불러~"]), 2.2)
        self.set_state("happy", 1.2, 1.8)
        self.hops_left = 2


# ───────────────────── 기지개 (50분 휴식 알림) ─────────────────────
def _stretch(self, text=None):
    self.angle = 0.0
    self.flat = -0.2                          # 쭉 늘어나기
    self.set_state("stretch", 2.2, 2.2)
    if text:
        self.say(text, 4.5)


def _s_stretch(self, area, ground, mouse, others):
    k = (self.until - self.now) / 2.2
    self.flat = -0.2 * math.sin(max(0.0, min(1.0, k)) * math.pi)
    if self.now > self.until:
        self.flat = 0.0
        self.set_state("idle", 1, 2)


# ───────────────────── 기차놀이 ─────────────────────
TRAIN_MAX = 8


class Train:
    def __init__(self, members, until, speed):
        self.members = members
        self.until = until
        self.speed = speed
        self.turning = False         # 대장이 친구들 머리 위로 넘어가서 방향 바꾸는 중

    @property
    def leader(self):
        return self.members[0] if self.members else None

    def end(self):
        for m in self.members:
            m.train = None
            if m.state == "train":
                m.emote("heart", 1.2)
                m.set_state("idle", 1, 2)
        self.members = []

    def join(self, b, now):
        """기차랑 마주친 펫이 꼬리 칸에 탑승"""
        if len(self.members) >= TRAIN_MAX or b in self.members:
            return False
        b.now = now
        b.train = self
        b.snack = None
        b.flat = 0.0
        b.angle = 0.0
        b.set_state("train", 99, 99)
        b.facing = self.leader.facing
        self.members.append(b)
        b.emote("ex", 0.9)
        b.say(b.rng.choice(["나도 탈래!", "같이 가~", "탑승!"]), 2.2)
        self.until = max(self.until, now + 12)      # 손님이 타면 조금 더 달림
        return True


def start_train(brains, now, rng=random, leader=None):
    """바닥에 있는 한가한 펫들이 줄지어 칙칙폭폭. leader를 주면 그 펫이 대장"""
    for b in brains:                                 # 이미 달리는 기차는 끝내고 새로
        if b.train is not None:
            b.train.end()
    cands = [b for b in brains if b.on is None and b.state in FREE_STATES and b.state != "sleep"
             and b.snack is None]
    if leader is None:
        if len(cands) < 2:
            return None
        leader = rng.choice(cands)
    elif leader.state in ("air", "drag", "climb", "hang"):
        return None
    if leader.on is not None:                        # 창 위에 있던 대장은 바닥으로
        leader.on = None
    others = sorted((b for b in cands if b is not leader and abs(b.cx - leader.cx) < 900),
                    key=lambda b: abs(b.cx - leader.cx))[:TRAIN_MAX - 1]
    if not others:
        leader.now = now
        leader.say("같이 놀 친구가 없어…", 2.5)
        return None
    members = [leader] + others
    l, t, r, _ = leader.area or (0, 0, 1920, 1080)
    leader.facing = 1 if (r - leader.cx) > (leader.cx - l) else -1
    tr = Train(members, now + rng.uniform(30, 45), rng.uniform(1.9, 2.4))
    for m in members:
        m.now = now
        m.train = tr
        m.flat = 0.0
        m.angle = 0.0
        m.snack = None
        m.set_state("train", 99, 99)
        m.facing = leader.facing
    leader.say("칙칙폭폭~ 🚂", 2.6)
    for m in others:
        m.emote("note", 1.4)
    return tr


def _s_train(self, area, ground, mouse, others):
    tr = self.train
    if tr is None or self not in tr.members:
        self.train = None
        self.set_state("idle", 1, 2)
        return
    tr.members = [m for m in tr.members if m.state == "train" and m.train is tr]
    if len(tr.members) < 2 or self.now > tr.until:
        tr.end()
        return
    l, t, r, b = area
    i = tr.members.index(self)
    self.phase += 0.2
    lead = tr.members[0]
    if i == 0:
        if tr.turning:
            # 친구들 머리 위로 폴짝폴짝 넘어가기
            self.cx += self.facing * 5.0
            if self.hop_y == 0 and self.hop_v == 0:
                self.hop_v = -8.5
            last = tr.members[1]
            ahead_done = (self.cx < last.cx - (self.w + last.w) / 2 * 0.9) if self.facing < 0 \
                else (self.cx > last.cx + (self.w + last.w) / 2 * 0.9)
            if ahead_done or self.cx <= l + self.w / 2 or self.cx >= r - self.w / 2:
                tr.turning = False
                self.emote("note", 1.0)
            return
        self.bob = abs(math.sin(self.phase * 1.4)) * 4
        self.cx += self.facing * tr.speed
        if (self.facing > 0 and self.cx >= r - self.w / 2 - 4) or (self.facing < 0 and self.cx <= l + self.w / 2 + 4):
            # 벽에 닿으면 대장이 뒤로 돌아 친구들을 넘어가고, 줄 순서도 뒤집힘 (대장은 그대로!)
            self.facing = -self.facing
            tr.members[1:] = tr.members[:0:-1]
            for m in tr.members[1:]:
                m.facing = self.facing
            tr.turning = True
            self.say("반대로~!", 1.8)
    else:
        if tr.turning:                               # 대장이 넘어가는 동안 제자리에서 기다림
            self.facing = lead.facing
            self.bob = abs(math.sin(self.phase * 1.4)) * 2
            return
        self.bob = abs(math.sin(self.phase * 1.4)) * 4
        ah = tr.members[i - 1]
        gap = (ah.w + self.w) / 2 * 0.9
        tx = ah.cx - ah.facing * gap
        d = tx - self.cx
        lim = 5.0 if abs(d) > 40 else 3.6          # 멀면 뛰어서 따라붙기
        self.cx += max(-lim, min(lim, d))
        self.facing = ah.facing if abs(d) < 6 else (1 if d > 0 else -1)
        if self.rng.random() < 0.004:
            self.emote("note", 1.2)


PetBrain.go_snack = _go_snack
PetBrain.s_go_snack = _s_go_snack
PetBrain.s_eat = _s_eat
PetBrain.stretch = _stretch
PetBrain.s_stretch = _s_stretch
PetBrain.s_train = _s_train
