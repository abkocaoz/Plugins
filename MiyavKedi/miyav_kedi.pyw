# -*- coding: utf-8 -*-
"""
Miyav Kedi
==========
Ekranin en altinda, gorev cubugu (taskbar) yuksekliginde seffaf bir seritte
yasayan minik bir kedi. Mouse imlecini yatayda takip eder; imlec durunca
size doner ve "GTA Calis" balonu cikarir.

Kedi gorseli: yandaki `kedi.png` dosyasindan yuklenir (seffaf PNG).
Dosya bulunamazsa program kendi cizdigi turuncu kediye doner.

Kullanim:
  - Calistir:  pythonw miyav_kedi.pyw   (veya dosyaya cift tikla)
  - Sol tik (kedinin ustune):  hemen konusur
  - Sag tik (kedinin ustune):  uygulamayi kapatir

Gereksinim: Windows + Python 3.8+ (tkinter Python ile birlikte gelir).
"""

import math
import os
import random
import sys
import time
import tkinter as tk

IS_WINDOWS = sys.platform == "win32"

# ---- Renkler -----------------------------------------------------------
TRANS = "#ff00fe"          # seffaflik anahtar rengi (ekranda gorunmez)
FUR = "#f0912d"            # tuy rengi (turuncu tekir)
FUR_DARK = "#b96518"       # cizgiler / kontur
BELLY = "#ffe9cd"          # gogus
EAR_PINK = "#f2a7b3"       # kulak ici
NOSE_PINK = "#e8788a"      # burun
EYE_GREEN = "#5cc46a"      # goz
INK = "#3a2a1a"            # goz bebegi / agiz
WHISKER = "#8c8c8c"        # biyik
BUBBLE_BG = "#ffffff"      # konusma balonu
BUBBLE_EDGE = "#c9c2b8"
BUBBLE_TEXT = "#3b3b3b"

MEOWS = ["GTA Çalış"]
SPRITE_FILE = "kedi.png"   # .pyw ile ayni klasorde durmali


def make_dpi_aware():
    """Windows'ta olcekleme (DPI) acikken koordinatlarin kaymamasi icin."""
    if not IS_WINDOWS:
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_screen_and_taskbar():
    """(ekran_genisligi, ekran_yuksekligi, serit_yuksekligi, serit_ust_y) dondurur.

    Serit yuksekligi = gorev cubugu yuksekligi; serit gorev cubugunun hemen
    ustune oturur. Gorev cubugu bulunamazsa (gizli / yanda) 48px varsayilir.
    """
    fallback_h = 48
    if IS_WINDOWS:
        import ctypes

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        user32 = ctypes.windll.user32
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        r = RECT()
        ok = user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
        tb = sh - r.bottom if ok else 0
        if 10 <= tb <= sh // 3:
            h = tb
            top = r.bottom - h          # gorev cubugunun hemen ustu
        else:
            h = fallback_h
            bottom = r.bottom if ok and 0 < r.bottom <= sh else sh
            top = bottom - h
        return sw, sh, h, top
    # Windows disi (test icin): ekranin en alti
    tmp = tk.Tk()
    sw, sh = tmp.winfo_screenwidth(), tmp.winfo_screenheight()
    tmp.destroy()
    return sw, sh, fallback_h, sh - fallback_h


def load_sprite(strip_h):
    """kedi.png'yi yukleyip serit yuksekligine sigacak sekilde olcekler.

    tkinter PhotoImage yalnizca tamsayi zoom/subsample bilir; bu yuzden
    hedefe en yakin z/d oranini arar (or. 192px -> 48px icin 1/4).
    Dosya yoksa None doner ve program cizilmis kediye geri duser.
    """
    # PyInstaller --onefile icinde calisirken dosyalar _MEIPASS'a acilir
    base = getattr(sys, "_MEIPASS",
                   os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, SPRITE_FILE)
    try:
        img = tk.PhotoImage(file=path)
    except Exception:
        return None
    target = strip_h - 2
    best = None
    for z in range(1, 9):
        for d in range(1, 97):
            est = img.height() * z / d
            if est > strip_h or est < target * 0.6:
                continue
            score = (abs(target - est), z * d)
            if best is None or score < best[0]:
                best = (score, z, d)
    if best is None:
        return None
    _, z, d = best
    scaled = img.zoom(z) if z > 1 else img
    if d > 1:
        scaled = scaled.subsample(d)
    return scaled


def rounded_rect(c, x1, y1, x2, y2, r, **kw):
    """Kosesi yuvarlatilmis dikdortgen (smooth polygon hilesi)."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
           x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


class MiyavKedi:
    IDLE_AFTER = 0.6      # imlec bu kadar sn kimildamayinca kedi durup bakar
    MEOW_DELAY = 0.35     # donup baktiktan sonra balonun cikma gecikmesi
    MEOW_SHOW = 2.4       # balonun ekranda kalma suresi (sn)
    MEOW_REPEAT = (5.0, 11.0)  # bos dururken tekrar miyavlama araligi (sn)

    def __init__(self, root, sw, strip_h):
        self.root = root
        self.sw = sw
        self.h = strip_h
        self.s = strip_h / 48.0          # tum cizim 48px'lik tasarima gore olcekli
        self.gy = strip_h - 1            # zemin cizgisi (seridin alti)

        self.canvas = tk.Canvas(root, width=sw, height=strip_h,
                                bg=TRANS, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.sprite = load_sprite(strip_h)   # referans tutulmali (GC'ye karsi)
        self.canvas.bind("<Button-1>", self.poke)
        self.canvas.bind("<Button-3>", self.quit)
        root.bind("<Escape>", self.quit)

        self.cat_x = sw / 2.0
        self.facing = 1                  # 1 = saga, -1 = sola bakiyor
        self.phase = 0.0                 # yurume animasyonu fazi
        self.walking = False
        self.idle = False

        px, py = self.pointer()
        self.last_mx, self.last_my = px, py
        self.last_move_t = time.time()

        self.meow_due = None             # balonun cikacagi an
        self.meow_start = None           # balon su an gorunuyorsa baslangici
        self.meow_forced = False         # tiklamayla miyavladiysa yururken de goster
        self.meow_text = MEOWS[0]

        self.next_blink = time.time() + 3.0
        self.blink_until = 0.0
        self._frame = 0

    # ---- yardimcilar ----------------------------------------------------
    def pointer(self):
        try:
            return self.root.winfo_pointerxy()
        except tk.TclError:
            return int(self.cat_x), 0

    def poke(self, _event=None):
        self.meow_start = time.time()
        self.meow_forced = True
        self.meow_text = random.choice(MEOWS)

    def quit(self, _event=None):
        self.root.destroy()

    # ---- ana dongu -------------------------------------------------------
    def tick(self):
        now = time.time()
        mx, my = self.pointer()
        if abs(mx - self.last_mx) > 2 or abs(my - self.last_my) > 2:
            self.last_move_t = now
            self.last_mx, self.last_my = mx, my

        s = self.s
        margin = 26 * s
        target = min(max(mx, margin), self.sw - margin)
        dx = target - self.cat_x
        moving = abs(dx) > 2

        if moving:
            step = min(max(abs(dx) * 0.14, 0.6 * s), 11 * s)
            self.cat_x += math.copysign(step, dx)
            self.facing = 1 if dx > 0 else -1
            self.phase += step / (2.2 * s)
        self.walking = moving

        idle = (not moving) and (now - self.last_move_t > self.IDLE_AFTER)
        if idle and not self.idle:
            self.idle = True
            self.meow_due = now + self.MEOW_DELAY
        elif not idle and self.idle:
            self.idle = False
            self.meow_due = None
            if not self.meow_forced:
                self.meow_start = None

        if self.meow_start is not None and now - self.meow_start > self.MEOW_SHOW:
            self.meow_start = None
            self.meow_forced = False
            if self.idle:
                self.meow_due = now + random.uniform(*self.MEOW_REPEAT)
        if self.idle and self.meow_start is None and self.meow_due is not None \
                and now >= self.meow_due:
            self.meow_start = now
            self.meow_text = random.choice(MEOWS)
            self.meow_due = None

        # goz kirpma (sadece bize bakarken)
        if now >= self.next_blink:
            self.blink_until = now + 0.13
            self.next_blink = now + random.uniform(2.5, 6.0)

        self.redraw(now)

        # bazi pencereler ustune cikabilir; arada bir tekrar en one al
        self._frame += 1
        if self._frame % 120 == 0:
            try:
                self.root.lift()
                self.root.attributes("-topmost", True)
            except tk.TclError:
                pass

        self.root.after(16, self.tick)

    # ---- cizim -----------------------------------------------------------
    def redraw(self, now):
        c = self.canvas
        c.delete("all")
        if self.sprite is not None:
            self.draw_sprite(c)
        elif self.idle:
            self.draw_front(c, now)
        else:
            self.draw_side(c)
        if self.meow_start is not None:
            self.draw_bubble(c, now)

    def draw_sprite(self, c):
        """kedi.png ile cizim: yururken hoplar, dururken sabit durur."""
        bob = abs(math.sin(self.phase)) * 2.5 * self.s if self.walking else 0.0
        c.create_image(self.cat_x, self.gy + 1 - bob, anchor="s",
                       image=self.sprite)

    def oval(self, c, x1, y1, x2, y2, **kw):
        return c.create_oval(min(x1, x2), min(y1, y2),
                             max(x1, x2), max(y1, y2), **kw)

    def draw_side(self, c):
        """Yandan gorunum: yuruyen / imlece kosan kedi."""
        s, f, p = self.s, self.facing, self.phase
        X = lambda vx: self.cat_x + f * vx * s
        Y = lambda vy: self.gy - vy * s
        w = lambda v: max(1.0, v * s)

        # bacaklar (govdenin arkasinda kalsin diye once cizilir)
        legs = ((-11, 0.0, FUR_DARK), (-6, math.pi, FUR),
                (4, math.pi, FUR_DARK), (9, 0.0, FUR))
        walk = self.walking
        for lx, off, col in legs:
            swing = math.sin(p + off) * 3.2 if walk else 0.0
            c.create_line(X(lx), Y(9), X(lx + swing), Y(0.5),
                          width=w(2.6), fill=col, capstyle="round")

        # kuyruk
        wag = math.sin(p * 0.5) * 2.5
        c.create_line(X(-14), Y(12), X(-19), Y(18), X(-18 + wag), Y(24),
                      smooth=True, width=w(2.8), fill=FUR, capstyle="round")

        # govde + cizgiler
        self.oval(c, X(-16), Y(7), X(10), Y(19),
                  fill=FUR, outline=FUR_DARK, width=w(1))
        for sx in (-8, -2, 4):
            c.create_line(X(sx), Y(18.5), X(sx - 2), Y(13.5),
                          width=w(1.6), fill=FUR_DARK, capstyle="round")

        # kafa (yururken hafif salinir)
        bob = math.sin(p) * 0.7 if walk else 0.0
        # kulaklar (kafanin altinda kalan taban kisimlari kafayla ortulur)
        c.create_polygon(X(15), Y(23 + bob), X(19.5), Y(31 + bob),
                         X(20.5), Y(22 + bob),
                         fill=FUR, outline=FUR_DARK, width=w(1))
        c.create_polygon(X(7.5), Y(23.5 + bob), X(5.5), Y(31 + bob),
                         X(11.5), Y(24 + bob),
                         fill=FUR, outline=FUR_DARK, width=w(1))
        self.oval(c, X(5.5), Y(9.5 + bob), X(20.5), Y(24.5 + bob),
                  fill=FUR, outline=FUR_DARK, width=w(1))

        # goz + burun
        self.oval(c, X(14.3), Y(17.3 + bob), X(16.7), Y(19.7 + bob),
                  fill=INK, outline="")
        self.oval(c, X(19.3), Y(15.4 + bob), X(21.1), Y(17.2 + bob),
                  fill=NOSE_PINK, outline="")

    def draw_front(self, c, now):
        """Onden gorunum: durup size bakan kedi."""
        s = self.s
        X = lambda vx: self.cat_x + vx * s
        Y = lambda vy: self.gy - vy * s
        w = lambda v: max(1.0, v * s)
        blink = now < self.blink_until

        # kuyruk one kivrilmis
        c.create_line(X(8), Y(2), X(14), Y(3), X(16), Y(8),
                      smooth=True, width=w(2.8), fill=FUR, capstyle="round")

        # govde (oturmus) + gogus + patiler
        self.oval(c, X(-10), Y(0), X(10), Y(17),
                  fill=FUR, outline=FUR_DARK, width=w(1))
        self.oval(c, X(-4.5), Y(1), X(4.5), Y(11), fill=BELLY, outline="")
        self.oval(c, X(-6.5), Y(0), X(-1.5), Y(3),
                  fill=FUR, outline=FUR_DARK, width=w(1))
        self.oval(c, X(1.5), Y(0), X(6.5), Y(3),
                  fill=FUR, outline=FUR_DARK, width=w(1))

        # kulaklar (kafadan once cizilir, ucler kafanin ustunde kalir)
        for m in (-1, 1):
            c.create_polygon(X(m * 8.2), Y(29), X(m * 10.5), Y(39),
                             X(m * 1.8), Y(32.5),
                             fill=FUR, outline=FUR_DARK, width=w(1))
            c.create_polygon(X(m * 7.6), Y(30), X(m * 9.0), Y(36.2),
                             X(m * 3.8), Y(31.8),
                             fill=EAR_PINK, outline="")

        # kafa
        self.oval(c, X(-9), Y(16), X(9), Y(34),
                  fill=FUR, outline=FUR_DARK, width=w(1))

        # gozler
        for m in (-1, 1):
            ex = m * 3.9
            if blink:
                c.create_line(X(ex - 1.8), Y(26.5), X(ex + 1.8), Y(26.5),
                              width=w(1.5), fill=INK, capstyle="round")
            else:
                self.oval(c, X(ex - 1.9), Y(24.1), X(ex + 1.9), Y(28.9),
                          fill=EYE_GREEN, outline=FUR_DARK, width=w(0.8))
                self.oval(c, X(ex - 0.7), Y(24.9), X(ex + 0.7), Y(28.1),
                          fill=INK, outline="")
                self.oval(c, X(ex + 0.2), Y(27.0), X(ex + 1.1), Y(27.9),
                          fill="#ffffff", outline="")

        # burun + agiz + biyiklar
        c.create_polygon(X(-1.3), Y(22.9), X(1.3), Y(22.9), X(0), Y(21.6),
                         fill=NOSE_PINK, outline="")
        c.create_line(X(0), Y(21.6), X(-1.2), Y(20.4), X(-2.2), Y(21.0),
                      smooth=True, width=w(1), fill=INK, capstyle="round")
        c.create_line(X(0), Y(21.6), X(1.2), Y(20.4), X(2.2), Y(21.0),
                      smooth=True, width=w(1), fill=INK, capstyle="round")
        for m in (-1, 1):
            c.create_line(X(m * 3.2), Y(23.0), X(m * 10.0), Y(24.4),
                          width=w(1), fill=WHISKER)
            c.create_line(X(m * 3.4), Y(22.2), X(m * 10.4), Y(22.2),
                          width=w(1), fill=WHISKER)
            c.create_line(X(m * 3.2), Y(21.4), X(m * 10.0), Y(20.2),
                          width=w(1), fill=WHISKER)

    def draw_bubble(self, c, now):
        """Konusma balonu: metin olculur, balon kedinin yanina yerlestirilir."""
        s = self.s
        grow = min(1.0, (now - self.meow_start) / 0.15)
        side = 1 if self.cat_x < self.sw - 160 * s else -1
        fs = max(8, int(10 * s))
        pad_x, pad_y = 7 * s, 3 * s

        # once metni olc (gecici konumda), sonra balonu konumlandir
        text_id = c.create_text(-1000, -1000, text=self.meow_text,
                                font=("Segoe UI", fs, "bold"),
                                fill=BUBBLE_TEXT, anchor="center")
        tx1, ty1, tx2, ty2 = c.bbox(text_id)
        half_w = (tx2 - tx1) / 2 + pad_x
        half_h = (ty2 - ty1) / 2 + pad_y

        # balonun kediye bakan kenari, kedinin hemen yaninda dursun
        if self.sprite is not None:
            edge = self.sprite.width() / 2 + 6 * s
        else:
            edge = 22 * s
        bx = self.cat_x + side * (edge + half_w)
        bx = min(max(bx, half_w + 2), self.sw - half_w - 2)  # ekrana sigdir
        by = half_h + 1 + (1.0 - grow) * 8 * s
        c.coords(text_id, bx, by)
        x1, y1, x2, y2 = bx - half_w, by - half_h, bx + half_w, by + half_h

        # ibre (balondan kedinin kulagina dogru)
        if self.sprite is not None:
            tip_x = self.cat_x + side * self.sprite.width() * 0.25
            tip_y = self.gy - self.sprite.height() * 0.88
        else:
            tip_x = self.cat_x + side * 8 * s
            tip_y = self.gy - 34 * s
        base_x = bx - side * half_w * 0.5
        c.create_polygon(base_x - 4 * s, y2 - 2, base_x + 4 * s, y2 - 2,
                         tip_x, tip_y,
                         fill=BUBBLE_BG, outline=BUBBLE_EDGE, width=max(1, s))
        rounded_rect(c, x1, y1, x2, y2, 8 * s,
                     fill=BUBBLE_BG, outline=BUBBLE_EDGE, width=max(1, s))
        c.tag_raise(text_id)


def main():
    make_dpi_aware()
    sw, _sh, strip_h, strip_top = get_screen_and_taskbar()

    root = tk.Tk()
    root.title("Miyav Kedi")
    root.overrideredirect(True)              # cerceve yok
    root.attributes("-topmost", True)        # hep en ustte
    try:
        # TRANS rengindeki pikseller hem gorunmez hem tiklanamaz olur;
        # yani serit, altindaki pencereleri engellemez. Sadece kedinin
        # kendisi tiklanabilir (sol tik: miyav, sag tik: kapat).
        root.attributes("-transparentcolor", TRANS)
    except tk.TclError:
        pass  # Windows disinda seffaflik desteklenmez
    root.geometry("%dx%d+0+%d" % (sw, strip_h, strip_top))

    app = MiyavKedi(root, sw, strip_h)
    app.tick()
    root.mainloop()


if __name__ == "__main__":
    main()
