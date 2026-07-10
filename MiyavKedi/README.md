# Miyav Kedi 🐱

Ekranın en altında, **görev çubuğu (taskbar) yüksekliğinde** şeffaf bir şeritte
yaşayan minik bir masaüstü kedisi:

- Mouse imleciniz hareket ettikçe kedi, imlecin hizasına doğru **koşar**
  (zıplaya zıplaya).
- İmleç durunca kedi de durur ve kısa bir gecikmeyle konuşma balonu çıkarır:
  bazen **"Miyav!"**, bazen **"Mrrr..."**, arada da **"GTA Çalış"** der
  (üst üste aynı şeyi söylemez). Boş durdukça arada bir tekrar konuşur.
- **Sesli!** "Miyav!" ve "Mrrr..." için program kendi ürettiği sevimli
  sentez sesleri çalar; **"GTA Çalış"** ise Windows'un yerleşik Türkçe
  okuma sesiyle (TTS) yüksek sesle söylenir. (Türkçe ses kurulu değilse
  varsayılan sistem sesi kullanılır.)
- Kedi görseli kodun içine gömülüdür — `.pyw` dosyası **tek başına**
  taşınsa bile kedi her yerde aynı görünür. Yanına şeffaf arka planlı bir
  `kedi.png` koyarsanız onu tercih eder; yani görseli dilediğinizle
  değiştirebilirsiniz.
- Şeridin yüksekliği otomatik olarak görev çubuğunuzun yüksekliği kadar alınır
  ve kedi görev çubuğunun hemen üstünde koşar. (Görev çubuğu gizli ya da yan
  kenardaysa 48 piksel varsayılır.)
- Pencere çerçevesizdir, her zaman en üsttedir ve **şeffaf kısımları tıklamayı
  engellemez** — yani altındaki pencereleri kullanmaya devam edebilirsiniz.
  Sadece kedinin kendisi tıklanabilir.

## Gereksinimler

- Windows 10 / 11 **veya** macOS
- [Python 3.8+](https://www.python.org/downloads/) — kurulumda varsayılan
  ayarlar yeterli (`tkinter` Python ile birlikte gelir, ek paket gerekmez).
  macOS'ta da python.org kurulumunu kullanın (Tk dahildir).

## Çalıştırma (Windows)

`miyav_kedi.pyw` dosyasına **çift tıklayın** (pyw uzantısı konsol penceresi
açmadan çalıştırır) veya komut satırından:

```bat
pythonw miyav_kedi.pyw
```

## Kullanım

| Eylem | Sonuç |
| --- | --- |
| İmleci hareket ettir | Kedi imlecin hizasına koşar |
| İmleci sabit tut | Kedi durur; "Miyav!", "Mrrr..." ya da "GTA Çalış" der (sesli) |
| Kediye **sol tık** | Hemen konuşur |
| Kediye **sağ tık** | Uygulama kapanır |

## Windows açılışında otomatik başlatma (isteğe bağlı)

1. `Win + R` → `shell:startup` yazıp Enter'a basın.
2. Açılan klasöre `miyav_kedi.pyw` dosyasının bir **kısayolunu** kopyalayın.

## Tek EXE dosyası yapmak (Windows, isteğe bağlı)

```bat
pip install pyinstaller
pyinstaller --onefile --noconsole miyav_kedi.pyw
```

Oluşan `dist\miyav_kedi.exe` dosyası Python kurulu olmayan bilgisayarlarda da
çalışır. (Kedi görseli kodun içine gömülü olduğundan `--add-data` gerekmez.)

## macOS'ta çalıştırma ve .app paketi yapmak

> **Önemli:** `.app` paketi yalnızca **Mac üzerinde** derlenebilir —
> PyInstaller çapraz derleme yapmaz. Aşağıdaki adımları Mac'te uygulayın.

**1. Python kurun** — [python.org](https://www.python.org/downloads/macos/)
üzerinden (Tk/tkinter dahildir).

**2. (Şiddetle önerilir) PyObjC kurun:**

```bash
pip3 install pyobjc-framework-Cocoa
```

Bu paket sayesinde şerit **Dock'un yüksekliğini tam ölçer**, Dock'un hemen
üstüne oturur ve **tıklamaları tamamen geçirir** (alttaki pencereleri hiç
engellemez). PyObjC yoksa uygulama yine çalışır ama kedi ekranın en altında
gezer ve şeridin boş kısmı tıklamaları alttaki pencerelere geçirmez.

**3. Denemek için doğrudan çalıştırın:**

```bash
python3 miyav_kedi.pyw
```

**4. .app paketini derleyin:**

```bash
pip3 install pyinstaller
pyinstaller --windowed --name "Miyav Kedi" --icon kedi.icns miyav_kedi.pyw
```

Çıktı: `dist/Miyav Kedi.app` — bunu **Applications** klasörüne
sürükleyebilirsiniz. (`kedi.icns` bu depoda hazır; kedi simgesi olur.)

**Notlar:**

- İmzasız uygulama olduğundan ilk açılışta macOS uyarabilir: uygulamaya
  **sağ tıklayıp "Aç"** deyin (bir kez yeterli).
- PyObjC kuruluysa kedi tıklama-geçirgen olur; **çıkmak için Dock'taki
  simgesine sağ tıklayıp Quit** seçin. PyObjC yoksa kediye sağ tık yine
  kapatır.
- macOS'ta sesler: miyav/mır sesleri `afplay` ile, **"GTA Çalış"** ise
  macOS'un yerleşik `say` komutuyla okunur (Türkçe **Yelda** sesi kuruluysa
  onunla; Sistem Ayarları → Erişilebilirlik → Sözlü İçerik'ten
  indirebilirsiniz).
- Girişte otomatik başlatma: Sistem Ayarları → Genel → **Login Items** →
  `Miyav Kedi.app`'i ekleyin.

## Görsel kaynağı

`kedi.png`, [Microsoft Fluent Emoji](https://github.com/microsoft/fluentui-emoji)
setindeki 3D kedi görselinden üretilmiştir (MIT lisansı).
