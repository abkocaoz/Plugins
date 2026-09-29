# Gereksinim Karşılaştırma

DOORS'tan alınan gereksinim setlerini (CSV / Excel) karşılaştırır:

- setler arasında **ortak gereksinimleri** metin benzerliğiyle bulur,
- farkları sütun sütun gösterir ve sınıflandırır (sayısal değer, shall/should, ondalık ayraç, öznitelik, eksik gereksinim…),
- her fark için karar vermenizi sağlar ve **Excel iş listesi** üretir,
- DOORS'ta düzeltip CSV'leri yeniden yüklediğinizde neyin **düzeldiğini / hâlâ farklı olduğunu / yeni bozulduğunu** raporlar,
- isteğe bağlı olarak yerel **Ollama** LLM'i ile farkları Türkçe açıklar ve İngilizce düzeltme önerir.

Tüm veriler bilgisayarınızda kalır; uygulama yalnızca `localhost` üzerinde çalışır.

## Kurulum (Windows)

1. [Python 3.10+](https://www.python.org/downloads/) kurun (kurulumda **"Add python.exe to PATH"** seçeneğini işaretleyin).
2. Bu klasörü örneğin `Desktop\Kişisel\GereksinimKarsilastirma` içine koyun.
3. `kurulum.bat` dosyasına çift tıklayın (bir kez).
4. `baslat.bat` ile uygulamayı açın. Tarayıcıda `http://localhost:8501` açılır.

> Kurumsal ağda `pip` paket indiremezse, pip için proxy ayarı gerekebilir:
> `pip config set global.proxy http://kullanici:sifre@proxy:port`

### Ollama (isteğe bağlı)

```
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
```

4 GB VRAM için `qwen2.5:3b` (veya `llama3.2:3b`) önerilir. Daha isabetli ama daha yavaş seçenek: `qwen2.5:7b`.
Uygulamada **7 · Ayarlar → Yerel LLM** bölümünden etkinleştirin ve "Bağlantıyı test et" deyin.

## Kullanım akışı

| Adım | Sayfa | Ne yapılır |
|---|---|---|
| 1 | Kenar çubuğu → Proje | Yeni proje oluşturun. Proje `projeler/<ad>.json` dosyasına otomatik kaydedilir. |
| 2 | 1 · Veri Yükleme | 17 CSV'yi seçip yükleyin. Ekipman adlarını kontrol edin (metinde maskelenir). İsterseniz bir ana set (ör. SRD) seçin. |
| 3 | 2 · Ortak Gereksinimler | Kapsam matrisi: ✓ aynı · ≠ farklı · – yok. Satıra tıklayınca detaya gider. |
| 4 | 3 · Grup Detayı | Setlerdeki haller yan yana, kelime düzeyinde fark, karar/not, LLM açıklaması. |
| 5 | 4 · Fark Listesi | Tüm farklar; filtreleyin, **Durum** (Açık / Düzeltilecek / Kasıtlı fark / Tamam) ve not girin, Excel'e aktarın. |
| 6 | 5 · Eşleşme Önerileri | Eşik altında kalan benzer öğeleri elle birleştirin; yanlış eşleşmeleri ayırın. |
| 7 | 6 · Doğrulama | **Temel çizgi** oluşturun → DOORS'ta düzeltin → yalnızca değişen CSV'leri yükleyin → rapor. |

## CSV biçimi

Sütunlar **sırayla** okunur (başlık adları dokümana göre değişebilir):

| Sıra | İçerik |
|---|---|
| 1 | Requirement ID (sete özel, ör. `PRSE-92`) |
| 2 | Source |
| 3 | Metin (ilk satır kısa ve noktasızsa **başlık**, kalanı **gövde** kabul edilir) |
| 4 | Attribute (Heading / Information / Requirement) |
| 5+ | Diğer öznitelikler (Compliance, Maturity, MoC, PoC, Rationale, Notes, …) |

- Set adı = dosya adı (`ESD-XXX-001.csv` → `ESD-XXX-001`). Aynı adla tekrar yüklenen dosya eski setin yerine geçer.
- Kodlama (UTF-8 / UTF-16 / Windows-1254) ve ayraç (`,` `;` sekme) otomatik algılanır.
- Heading satırları karşılaştırılmaz, ama her gereksinimin hangi bölümün altında olduğu kaydedilir.

## Nasıl karşılaştırır?

- **Eşleştirme:** Metinler küçük harfe çevrilir, noktalama ve fazla boşluklar atılır, ekipman adı `<EKIPMAN>` ile maskelenir.
  Farklı setlerdeki öğeler benzerlik puanına (%0–100) göre, her grupta her setten en fazla bir öğe olacak şekilde gruplanır.
  Varsayılan eşik %85 (Ayarlar'dan değiştirilebilir).
- **Referans:** Ana set seçilmişse o set; değilse her alanda **en çok tekrar eden değer**. Eşit oyda uyarı gösterilir.
- **Karşılaştırılan alanlar:** Requirement ID ve metin sütununun kendisi dışındaki tüm sütunlar + başlık, gövde ve bölüm.
- **Fark türleri ve önem:**

| Kategori | Önem |
|---|---|
| Sayısal değer (ör. `70 → 71`) | Yüksek |
| Zorunluluk ifadesi (shall/should/will/may…) | Yüksek |
| "Safety" içeren sütunda fark | Yüksek |
| Metin, öznitelik, Source, tür, eksik değer, eksik gereksinim | Orta |
| Sayı biçimi / ondalık virgül (`75,2`), set içi tekrar | Orta |
| Biçim (harf/noktalama/boşluk), bölüm yeri, boş Source | Düşük |

- **Doğrulama** tamamen kural tabanlıdır; LLM karar vermez.

## Klasör yapısı

```
app.py              Streamlit arayüzü (Türkçe)
core/loader.py      CSV/Excel okuma
core/normalize.py   Normalizasyon, sayı/zorunluluk çıkarımı
core/matching.py    Ortak gereksinim gruplama
core/compare.py     Referans ve fark sınıflandırma
core/verify.py      Temel çizgi ve doğrulama
core/export.py      Excel raporu
core/llm.py         Ollama istemcisi
core/project.py     Proje dosyası
projeler/           Proje JSON dosyaları (git'e eklenmez)
```
