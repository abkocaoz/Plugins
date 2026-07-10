# -*- coding: utf-8 -*-
"""
Miyav Kedi
==========
Ekranin en altinda, gorev cubugu / Dock yuksekliginde seffaf bir seritte
yasayan minik bir kedi. Mouse imlecini yatayda takip eder; imlec durunca
konusma balonu cikarir ve sesli konusur.

Kedi gorseli koda gomuludur; yandaki `kedi.png` varsa o tercih edilir.

Kullanim:
  - Windows: pythonw miyav_kedi.pyw  (veya dosyaya cift tikla)
  - macOS:   python3 miyav_kedi.pyw  (ya da PyInstaller ile .app paketle)
  - Sol tik (kedinin ustune):  hemen konusur
  - Sag tik (kedinin ustune):  uygulamayi kapatir
    (macOS'ta PyObjC kuruluysa kedi tiklamalari tamamen gecirir;
     cikis Dock simgesinden yapilir)

Gereksinim: Python 3.8+ (tkinter Python ile birlikte gelir).
macOS'ta onerilen: pip3 install pyobjc-framework-Cocoa
  -> Dock yuksekligi tam olculur + serit tiklamalari engellemez.
"""

import math
import os
import random
import sys
import time
import tkinter as tk

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

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

MEOWS = ["Miyav!", "Mrrr...", "GTA Çalış"]
MEOW_WEIGHTS = [45, 30, 25]        # secilme olasiliklari (yaklasik yuzde)
SPRITE_FILE = "kedi.png"   # varsa bu dosya kullanilir; yoksa gomulu kopya


def pick_meow(last=None):
    """Siradaki konusmayi secer; ust uste ayni sey soylemez."""
    texts, weights = list(MEOWS), list(MEOW_WEIGHTS)
    if last in texts and len(texts) > 1:
        i = texts.index(last)
        del texts[i], weights[i]
    return random.choices(texts, weights=weights)[0]


def _wav_bytes(samples, rate=22050):
    """-1..1 arasi ornek listesini bellekte 16-bit mono WAV'a cevirir."""
    import io
    import struct
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for smp in samples:
            frames += struct.pack("<h", int(max(-1.0, min(1.0, smp)) * 32000))
        w.writeframes(bytes(frames))
    return buf.getvalue()


def synth_meow_wav(rate=22050):
    """Sentezlenmis kisa 'miyav': perde once tirmanir (mi-ya) sonra iner (uv)."""
    dur = 0.7
    n = int(dur * rate)
    out = []
    phase = 0.0
    for i in range(n):
        t = i / n
        if t < 0.35:
            f = 420 + (820 - 420) * (t / 0.35)
        else:
            f = 820 - (820 - 320) * ((t - 0.35) / 0.65)
        f *= 1.0 + 0.03 * math.sin(2 * math.pi * 5.5 * (i / rate))  # vibrato
        phase += 2 * math.pi * f / rate
        wv = (math.sin(phase) + 0.45 * math.sin(2 * phase)
              + 0.2 * math.sin(3 * phase))
        amp = min(t / 0.06, 1.0) * max(min((1.0 - t) / 0.25, 1.0), 0.0)
        if t < 0.08:            # 'm' girisi: bogumlu, yumusak
            wv = math.sin(phase)
            amp *= 0.6
        out.append(0.5 * amp * wv)
    return _wav_bytes(out, rate)


def synth_purr_wav(rate=22050):
    """Sentezlenmis 'mrrr': ~23 Hz'lik titresimle modulasyonlu pes ton."""
    dur = 1.3
    n = int(dur * rate)
    rnd = random.Random(7)
    out = []
    lp = 0.0
    for i in range(n):
        t = i / n
        ts = i / rate
        pulse = 0.55 + 0.45 * math.sin(2 * math.pi * 23 * ts)
        tone = 0.55 * math.sin(2 * math.pi * 48 * ts) \
            + 0.25 * math.sin(2 * math.pi * 96 * ts)
        lp = 0.85 * lp + 0.15 * rnd.uniform(-1, 1)   # yumusatilmis hisirti
        amp = min(t / 0.15, 1.0) * min((1.0 - t) / 0.2, 1.0)
        out.append(0.55 * amp * pulse * (tone + 0.5 * lp))
    return _wav_bytes(out, rate)


class Sound:
    """Balon cikarken ses.

    Windows: Miyav/Mrrr sentezlenmis WAV (winsound, bellekten),
             'GTA Çalış' yerlesik TTS (SAPI, gizli PowerShell).
    macOS:   Miyav/Mrrr gecici WAV dosyalarindan `afplay` ile,
             'GTA Çalış' yerlesik `say` komutuyla (Turkce ses: Yelda).
    Diger platformlarda ve hata durumunda sessizce devre disi kalir."""

    def __init__(self):
        self.mode = "win" if IS_WINDOWS else ("mac" if IS_MAC else None)
        self._winsound = None
        self._wavs = {}
        try:
            if self.mode == "win":
                import winsound
                self._winsound = winsound
                self._wavs = {"Miyav!": synth_meow_wav(),
                              "Mrrr...": synth_purr_wav()}
            elif self.mode == "mac":
                import tempfile
                for key, data in (("Miyav!", synth_meow_wav()),
                                  ("Mrrr...", synth_purr_wav())):
                    path = os.path.join(tempfile.gettempdir(),
                                        "miyavkedi_%d.wav" % len(self._wavs))
                    with open(path, "wb") as f:
                        f.write(data)
                    self._wavs[key] = path
        except Exception:
            self.mode = None

    @property
    def enabled(self):
        return self.mode is not None

    def play(self, text):
        if self.mode is None:
            return
        try:
            if text in self._wavs:
                if self.mode == "win":
                    ws = self._winsound
                    ws.PlaySound(self._wavs[text],
                                 ws.SND_MEMORY | ws.SND_ASYNC
                                 | ws.SND_NODEFAULT)
                else:
                    import subprocess
                    subprocess.Popen(["afplay", self._wavs[text]])
            else:
                self._speak(text)
        except Exception:
            pass

    def _speak(self, text):
        import subprocess
        if self.mode == "mac":
            import shlex
            q = shlex.quote(text)
            # Turkce ses (Yelda) varsa onu kullan, yoksa varsayilan ses
            subprocess.Popen(
                ["sh", "-c", "say -v Yelda %s 2>/dev/null || say %s" % (q, q)])
            return
        import base64
        ps = ("Add-Type -AssemblyName System.Speech;"
              "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
              "$v=$s.GetInstalledVoices()|Where-Object{"
              "$_.VoiceInfo.Culture.Name -like 'tr*'}|Select-Object -First 1;"
              "if($v){$s.SelectVoice($v.VoiceInfo.Name)};"
              "$s.Speak('%s')" % text.replace("'", "''"))
        enc = base64.b64encode(ps.encode("utf-16-le")).decode()
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-WindowStyle", "Hidden", "-EncodedCommand", enc],
            creationflags=0x08000000)  # CREATE_NO_WINDOW


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


def get_screen_and_taskbar(root):
    """(ekran_genisligi, ekran_yuksekligi, serit_yuksekligi, serit_ust_y) dondurur.

    Serit yuksekligi = gorev cubugu / Dock yuksekligi; serit onun hemen
    ustune oturur. Olculemezse (gizli / yanda / arac yok) 48px varsayilir
    ve serit ekranin en altina yerlesir.

    `root`: main() icinde olusturulan TEK Tk penceresi. (macOS'ta olcum
    icin gecici bir Tk acip kapatmak cokmeye yol acabildiginden ayni
    pencere kullanilir.)
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
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    if IS_MAC:
        try:
            # PyObjC varsa Dock yuksekligini tam olc
            from AppKit import NSScreen
            scr = NSScreen.mainScreen()
            f, v = scr.frame(), scr.visibleFrame()
            dock = int(v.origin.y - f.origin.y)  # Cocoa'da y asagidan yukari
            if 10 <= dock <= sh // 3:
                return sw, sh, dock, sh - 2 * dock  # Dock'un hemen ustu
        except Exception:
            pass
    # Dock olculemedi / gizli / diger platform: ekranin en alti
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
    img = None
    if os.path.exists(path):
        try:
            img = tk.PhotoImage(file=path)
        except Exception:
            img = None
    if img is None and EMBEDDED_SPRITE.strip():
        # kedi.png yoksa kodun icine gomulu kopya kullanilir; boylece
        # kedi her kosulda ayni gorunur
        try:
            img = tk.PhotoImage(data=EMBEDDED_SPRITE)
        except Exception:
            img = None
    if img is None:
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

        bg = "systemTransparent" if IS_MAC else TRANS
        self.canvas = tk.Canvas(root, width=sw, height=strip_h,
                                bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.sprite = load_sprite(strip_h)   # referans tutulmali (GC'ye karsi)
        self.sound = Sound()
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

    def say(self, text=None):
        """Balonu gosterir ve sesi calar."""
        if text is None:
            text = pick_meow(self.meow_text)
        self.meow_text = text
        self.meow_start = time.time()
        self.sound.play(text)

    def poke(self, _event=None):
        self.say()
        self.meow_forced = True

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
            self.say()
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


# Gomulu kedi gorseli (kedi.png'nin base64 kopyasi): dosya yaninda
# tasinmasa bile kedi her yerde ayni gorunsun diye koda gomuludur.
EMBEDDED_SPRITE = """
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
SUVORK5CYII=
"""


def make_mac_click_through(root):
    """macOS + PyObjC: pencere tiklamalari tamamen gecirsin.

    Basarili olursa serit alttaki pencereleri hic engellemez; ama kediye
    de tiklanamaz — cikis Dock simgesine sag tiklayip Quit ile yapilir.
    PyObjC yoksa False doner; kedi tiklanabilir kalir fakat seffaf serit
    alanindaki tiklamalar alttaki pencerelere gecmez (Tk siniri)."""
    try:
        from AppKit import NSApp
        root.update_idletasks()
        root.update()
        for w in NSApp.windows():
            w.setIgnoresMouseEvents_(True)
        return True
    except Exception:
        return False


def main():
    try:
        # cokme olursa (ozellikle macOS/Tk uyumsuzluklari) iz birakir;
        # pythonw altinda stderr olmayabilir, o yuzden korumali
        import faulthandler
        faulthandler.enable()
    except Exception:
        pass

    make_dpi_aware()

    root = tk.Tk()                           # surec boyunca TEK Tk penceresi
    root.title("Miyav Kedi")
    if IS_MAC:
        try:
            # macOS'ta gercek seffaflik: pencere haritalanmadan ONCE
            # ayarlanmali; 'systemTransparent' zeminle birlikte kullanilir
            root.attributes("-transparent", True)
            root.config(bg="systemTransparent")
        except tk.TclError:
            pass
    else:
        try:
            # TRANS rengindeki pikseller hem gorunmez hem tiklanamaz olur;
            # yani serit, altindaki pencereleri engellemez. Sadece kedinin
            # kendisi tiklanabilir (sol tik: konus, sag tik: kapat).
            root.attributes("-transparentcolor", TRANS)
        except tk.TclError:
            pass  # diger platformlarda seffaflik desteklenmez

    sw, _sh, strip_h, strip_top = get_screen_and_taskbar(root)
    root.overrideredirect(True)              # cerceve yok
    root.attributes("-topmost", True)        # hep en ustte
    root.geometry("%dx%d+0+%d" % (sw, strip_h, strip_top))

    app = MiyavKedi(root, sw, strip_h)
    if IS_MAC:
        make_mac_click_through(root)
    app.tick()
    root.mainloop()


if __name__ == "__main__":
    main()
