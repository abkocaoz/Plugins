# Miyav Kedi 🐱

Ekranın en altında, **görev çubuğu (taskbar) yüksekliğinde** şeffaf bir şeritte
yaşayan minik bir masaüstü kedisi:

- Mouse imleciniz hareket ettikçe kedi, imlecin hizasına doğru **koşar**
  (zıplaya zıplaya).
- İmleç durunca kedi de durur ve kısa bir gecikmeyle **"GTA Çalış" konuşma
  balonu** çıkarır. Boş durdukça arada bir tekrar hatırlatır.
- Kedi görseli, `.pyw` dosyasının yanındaki **`kedi.png`** dosyasından yüklenir
  ve görev çubuğu yüksekliğine otomatik ölçeklenir. Dilerseniz bu PNG'yi
  (şeffaf arka planlı) başka bir görselle değiştirebilirsiniz; dosya yoksa
  program kendi çizdiği turuncu kediye geri döner.
- Şeridin yüksekliği otomatik olarak görev çubuğunuzun yüksekliği kadar alınır
  ve kedi görev çubuğunun hemen üstünde koşar. (Görev çubuğu gizli ya da yan
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
| İmleci hareket ettir | Kedi imlecin hizasına koşar |
| İmleci sabit tut | Kedi durur, "GTA Çalış" der |
| Kediye **sol tık** | Hemen konuşur |
| Kediye **sağ tık** | Uygulama kapanır |

## Windows açılışında otomatik başlatma (isteğe bağlı)

1. `Win + R` → `shell:startup` yazıp Enter'a basın.
2. Açılan klasöre `miyav_kedi.pyw` dosyasının bir **kısayolunu** kopyalayın.

## Tek EXE dosyası yapmak (isteğe bağlı)

```bat
pip install pyinstaller
pyinstaller --onefile --noconsole --add-data "kedi.png;." miyav_kedi.pyw
```

Oluşan `dist\miyav_kedi.exe` dosyası Python kurulu olmayan bilgisayarlarda da
çalışır.

## Görsel kaynağı

`kedi.png`, [Microsoft Fluent Emoji](https://github.com/microsoft/fluentui-emoji)
setindeki 3D kedi görselinden üretilmiştir (MIT lisansı).
