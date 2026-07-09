# Miyav Kedi 🐱

Ekranın en altında, **görev çubuğu (taskbar) yüksekliğinde** şeffaf bir şeritte
yaşayan minik bir masaüstü kedisi:

- Mouse imleciniz hareket ettikçe kedi, imlecin hizasına doğru **yürür/koşar**
  (gittiği yöne döner, bacakları ve kuyruğu sallanır).
- İmleç durunca kedi de durur, **size döner** ve kısa bir gecikmeyle
  **"Miyav!" konuşma balonu** çıkarır. Boş durdukça arada bir tekrar miyavlar,
  göz kırpar.
- Şeridin yüksekliği otomatik olarak görev çubuğunuzun yüksekliği kadar alınır
  ve kedi görev çubuğunun hemen üstünde yürür. (Görev çubuğu gizli ya da yan
  kenardaysa 48 piksel varsayılır.)
- Pencere çerçevesizdir, her zaman en üsttedir ve **şeffaf kısımları tıklamayı
  engellemez** — yani altındaki pencereleri kullanmaya devam edebilirsiniz.
  Sadece kedinin kendisi tıklanabilir.

## Gereksinimler

- Windows 10 / 11
- [Python 3.8+](https://www.python.org/downloads/) — kurulumda varsayılan
  ayarlar yeterli (`tkinter` Python ile birlikte gelir, ek paket gerekmez).

## Çalıştırma

`miyav_kedi.pyw` dosyasına **çift tıklayın** (pyw uzantısı konsol penceresi
açmadan çalıştırır) veya komut satırından:

```bat
pythonw miyav_kedi.pyw
```

## Kullanım

| Eylem | Sonuç |
| --- | --- |
| İmleci hareket ettir | Kedi imlecin hizasına yürür |
| İmleci sabit tut | Kedi size döner, "Miyav!" der |
| Kediye **sol tık** | Hemen miyavlar |
| Kediye **sağ tık** | Uygulama kapanır |

## Windows açılışında otomatik başlatma (isteğe bağlı)

1. `Win + R` → `shell:startup` yazıp Enter'a basın.
2. Açılan klasöre `miyav_kedi.pyw` dosyasının bir **kısayolunu** kopyalayın.

## Tek EXE dosyası yapmak (isteğe bağlı)

```bat
pip install pyinstaller
pyinstaller --onefile --noconsole miyav_kedi.pyw
```

Oluşan `dist\miyav_kedi.exe` dosyası Python kurulu olmayan bilgisayarlarda da
çalışır.
