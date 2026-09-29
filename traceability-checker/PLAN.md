# Traceability Matrix Doğrulama Aracı — Planlama

## 1. Amaç

Girdi olarak:

- **Gereksinim seti** (`.csv`): tüm gereksinimler (ID, metin, doğrulama yöntemi vb.)
- **Proje dokümanı** (`.docx`): ilk hedef **SDD** (Software Design Description). Sonra STP/STD/SRS/IDD gibi dokümanlar da eklenebilir.

Araç şunları yapar:

1. Word dokümanındaki **Traceability Matrix** tablosunu bulur.
2. Matristeki her satırı CSV'deki gereksinimle **ID üzerinden eşler**.
3. Matrisin gösterdiği **bölümü** (örn. `4.2.3`) dokümanda bulup o bölümün metnini çıkarır.
4. Bu metnin gereksinimi **gerçekten karşılayıp karşılamadığını** değerlendirir (Karşılıyor / Kısmen / Karşılamıyor / Belirlenemedi), gerekçesini ve dokümandan birebir alıntıyı verir.
5. Sonuçları, bir gözden geçirmecinin (reviewer) kullanabileceği bir **Excel raporu** olarak üretir.

> Not: Araç **karar vermez, karar destekler**. Nihai onay mühendis/QA incelemesindedir; araç kanıtı ve şüpheli satırları öne çıkarır.

---

## 2. Genel Akış

```
requirements.csv ──► [1] CSV okuma & normalizasyon ──┐
                                                     ├─► [4] Eşleştirme ──► [5] Değerlendirme ──► [6] Rapor (.xlsx)
SDD.docx ──► [2] Doküman modeli ──► [3] Matris tespiti┘        (ID + bölüm)      (kural + LLM)
```

---

## 3. Adımlar

### Adım 1 — CSV okuma ve normalizasyon

- Kodlama tespiti: `utf-8-sig`, `cp1254` (Türkçe Excel çıktıları), ayraç tespiti (`,` / `;`).
- **Kolon eşleme konfigürasyonu** (CSV şeması projeye göre değişir):
  ```yaml
  csv:
    id: "Req ID"
    text: "Requirement Text"
    verification_method: "Verification Method"   # T / A / I / D
    level: "Level"                               # System / SW / HW ...
    allocation: "Allocated To"                   # SDD'ye ilgili olanları süzmek için
    parent: "Parent ID"
  ```
- ID normalizasyonu: boşluk, büyük/küçük harf, `SRS-001` ↔ `SRS_001` ↔ `SRS-0001` gibi varyasyonlar.
- Çok satırlı gereksinim metinleri, tekrar eden ID'ler, boş metinler → "veri kalitesi" uyarısı.

### Adım 2 — Word dokümanından doküman modeli çıkarma

`python-docx` + gerekirse ham XML (`lxml`) ile:

- **Başlık hiyerarşisi**: `Heading 1..n` stilleri ve outline level.
  - Kritik nokta: Word'deki otomatik numaralar (`4.2.3`) metinde **yazmaz**, numbering tanımından (`numPr`, `numbering.xml`) hesaplanmalı. Bu adım ayrıca test edilecek; alternatif olarak LibreOffice ile numaraları "sabitleyip" okumak yedek yöntemdir.
- Her bölüm için: numara, başlık, gövde metni, **alt bölümler**, tablolar, şekil/tablo başlıkları (caption).
- Bookmark'lar ve `REF _Ref...` çapraz referans alanları (matris bölüm numarası yerine çapraz referans kullanıyorsa).
- Çıktı: `section_id → {başlık, metin, tablolar, alt bölümler}` indeksi (JSON olarak da kaydedilir; debug için).

### Adım 3 — Traceability Matrix tablosunu bulma

- Aday tablolar, başlık satırındaki anahtar kelimelerle puanlanır:
  `Requirement / Gereksinim / Req ID`, `Section / Bölüm / Paragraph / Madde`, `Traceability / İzlenebilirlik`.
- Ek sinyaller: tablonun "Traceability" başlıklı bir bölüm altında olması, kolondaki hücrelerin ID pattern'ine (regex) uyması.
- Birden fazla sayfaya/tabloya bölünmüş matrisleri **birleştirme**, tekrar eden başlık satırlarını atma, birleşik (merged) hücreleri açma.
- Konfigürasyonla elle override: `matrix: {table_index: 12}` veya `matrix: {after_heading: "Requirements Traceability"}`.

### Adım 4 — Eşleştirme

Matris hücreleri çözülür:

- ID listeleri ve aralıklar: `SRS-010, SRS-012`, `SRS-010 … SRS-015`, `SRS-010 to 015`.
- Bölüm referansları: `4.2.3`, `§4.2.3`, `Section 4.2.3`, `4.2.3, 4.3.1`, `4.2.x` (alt bölümlerin hepsi).

Eşleştirme sonucu **yapısal kontroller** (LLM gerektirmez, hızlı ve kesin):

| Kontrol | Açıklama |
|---|---|
| Matriste var, CSV'de yok | Yetim (orphan) / hatalı ID |
| CSV'de var (SDD'ye tahsisli), matriste yok | **Kapsama boşluğu** |
| Matristeki bölüm dokümanda yok | Kırık referans |
| Bölüm var ama boş / sadece "TBD" | Eksik içerik |
| Gereksinim metni CSV ile matristeki metin farklı | Sürüm uyumsuzluğu (matris metin içeriyorsa) |

### Adım 5 — İçerik değerlendirmesi ("bu metin gereksinimi karşılıyor mu?")

Her `(gereksinim, bölüm metni)` çifti için:

1. **Gereksinimi atomik parçalara ayırma**: tek bir "shall" cümlesi birden çok koşul içerebilir (performans değeri, mod, arayüz, hata durumu...). Her parça ayrı kontrol edilir → "Kısmen" kararını gerekçelendirmek için şart.
2. **Kural tabanlı ön kontroller**: gereksinimdeki sayısal değerler/birimler (örn. `50 ms`, `10 Hz`), sinyal/arayüz adları, mod adları bölüm metninde geçiyor mu?
3. **LLM değerlendirmesi** (Claude API, yapılandırılmış JSON çıktı):
   ```json
   {
     "verdict": "FULL | PARTIAL | NOT_ADDRESSED | UNDETERMINED",
     "atomic_checks": [{"clause": "...", "addressed": true, "evidence": "birebir alıntı"}],
     "missing": ["gereksinimin karşılanmayan yönleri"],
     "confidence": 0.0-1.0,
     "rationale": "kısa gerekçe"
   }
   ```
   - **Doküman tipine özel değerlendirme kriteri (rubrik)**: SDD için soru "tasarım, bu gereksinimin *nasıl* gerçekleştirileceğini tanımlıyor mu?" (bileşen, arayüz, algoritma, veri yapısı, zamanlama). STD için soru "test prosedürü gereksinimi doğrulayacak adımları ve geçme kriterini içeriyor mu?" olur. Rubrikler konfigürasyondan gelir.
   - CSV'deki **doğrulama yöntemi** (Test/Analiz/Inspection/Demo) rubriğe girdi olur: örn. yöntem "Analysis" ise SDD bölümünde analiz/hesap beklenir.
   - **Alıntı doğrulaması**: LLM'in verdiği her `evidence` bölüm metninde **birebir** aranır; bulunamazsa sonuç otomatik "UNDETERMINED" + uyarı (halüsinasyon koruması).
   - `temperature=0`, prompt + model + girdi hash'i ile **önbellek** → tekrar çalıştırmada aynı sonuç, düşük maliyet.
4. **Alternatif konum önerisi** (opsiyonel): Bölüm gereksinimi karşılamıyorsa, tüm doküman üzerinde arama (BM25 / embedding) yapıp "gereksinim muhtemelen §5.1'de karşılanıyor" önerisi → yanlış bölüm referansını yakalar.

### Adım 6 — Raporlama

`traceability_report.xlsx`:

| Sayfa | İçerik |
|---|---|
| Özet | Toplam gereksinim, kapsanan, FULL/PARTIAL/NOT/UNDET dağılımı, kırık referanslar |
| Detay | Req ID, gereksinim metni, doğrulama yöntemi, matristeki bölüm, bölüm başlığı, karar, eksikler, alıntı, güven, önerilen alternatif bölüm, **Reviewer kararı / yorum** (boş kolon) |
| Kapsama boşlukları | Matriste olmayan gereksinimler |
| Yetimler / kırık referanslar | Yapısal hatalar |
| Parse uyarıları | Tablo/başlık okuma sorunları |

Opsiyonel: SDD'nin **yorum eklenmiş kopyası** (`SDD_reviewed.docx`) — ilgili bölümlere Word yorumu olarak bulgular.

---

## 4. Mimari

```
traceability-checker/
├── config/
│   ├── default.yaml          # CSV kolon eşleme, ID regex'leri
│   └── rubrics/
│       ├── sdd.yaml          # SDD değerlendirme kriterleri
│       └── std.yaml          # (ileride)
├── tracecheck/
│   ├── csv_loader.py         # Adım 1
│   ├── docx_model.py         # Adım 2 (başlık numaralandırma dahil)
│   ├── matrix_finder.py      # Adım 3
│   ├── matcher.py            # Adım 4
│   ├── evaluator.py          # Adım 5 (kural + LLM + alıntı doğrulama + cache)
│   ├── report.py             # Adım 6
│   └── cli.py
└── tests/
    ├── fixtures/             # örnek küçük csv + docx
    └── gold/                 # elle etiketlenmiş değerlendirme seti
```

Kullanım:

```bash
tracecheck --reqs requirements.csv --doc SDD.docx --doc-type sdd \
           --config config/default.yaml --out traceability_report.xlsx
# LLM'siz sadece yapısal kontrol:
tracecheck ... --structural-only
```

Teknoloji: Python 3.11+, `python-docx`, `lxml`, `pandas`, `openpyxl`, `pydantic`, `anthropic`, `rank-bm25` (opsiyonel).

Bu repo bir plugin deposu olduğu için, CLI hazır olduktan sonra aynı mantık bir **Claude Code skill/plugin**'i olarak da paketlenebilir ("şu CSV ve SDD'yi kontrol et" dendiğinde CLI'yi çalıştırıp raporu yorumlayan bir skill).

---

## 5. Aşamalar (Milestone)

| # | Aşama | Çıktı | Kabul kriteri |
|---|---|---|---|
| M1 | CSV + DOCX okuma | Doküman modeli JSON'u | Gerçek SDD'de tüm bölüm numaraları Word'deki ile birebir |
| M2 | Matris tespiti + eşleştirme | Yapısal kontrol raporu (LLM'siz) | Matristeki tüm satırlar doğru çözülüyor; boşluk/yetim listesi doğru |
| M3 | LLM değerlendirmesi | Detay sayfası dolu rapor | Alıntıların %100'ü dokümanda birebir bulunuyor |
| M4 | Kalibrasyon | Gold set sonuçları | ~50 elle etiketlenmiş çiftte mühendis kararıyla uyum ≥ %85; "NOT_ADDRESSED" kaçırma oranı düşük |
| M5 | Genişletme | STD/STP rubrikleri, yorumlu docx, skill paketi | — |

M1–M2 tek başına bile değerli: kırık referans ve kapsama boşluklarını LLM'siz, deterministik olarak yakalar.

---

## 6. Riskler ve Önlemler

| Risk | Önlem |
|---|---|
| **Gizlilik**: Savunma/havacılık dokümanları dış API'ye gönderilemeyebilir (ITAR/EAR, kurum politikası) | Önce güvenlik biriminden onay. Alternatifler: `--structural-only` mod, kurum içi (on-prem) model, sadece ilgili bölüm metninin gönderilmesi |
| Word otomatik numaralandırmasının yanlış hesaplanması | M1'de gerçek dokümanla birebir doğrulama; LibreOffice yedek yolu |
| Matrisin farklı formatlarda olması (birleşik hücre, çok sayfa, ters yön: Bölüm→Gereksinim) | Puanlama + konfigürasyonla override; iki yönlü matris desteği |
| LLM'in yanlış "karşılıyor" demesi | Atomik kontrol, birebir alıntı doğrulama, güven eşiği altı → "UNDETERMINED", gold set ile kalibrasyon, reviewer kolonu |
| Bölüm metninin tek başına yetersiz olması (şekil/diyagram ağırlıklı SDD) | Caption ve tablo içeriği dahil edilir; görsel içerik için "UNDETERMINED + şekil var" işareti |
| Çok büyük bölümler | Alt bölümlere bölme ve en ilgili parçaları seçme (retrieval) |

---

## 7. Netleştirilmesi Gerekenler (başlamadan önce)

1. **CSV kolonları**: Hangi kolonlar var? (ID, metin, doğrulama yöntemi, seviye, tahsis/allocation, parent…) — 5–10 satırlık anonim örnek yeterli.
2. **Matris formatı**: Gereksinim → Bölüm mü, Bölüm → Gereksinim mi? Bölüm numarası mı, başlık mı, çapraz referans mı kullanılıyor? Matris metin içeriyor mu?
3. **"Doğrulama kısmı"** ile kastedilen: (a) CSV'deki *verification method* kolonu mu, (b) matriste doğrulama/kanıt kolonu mu, (c) genel olarak "bu bölüm gereksinimi karşılıyor mu" sorusu mu?
4. SDD'de hangi gereksinimler olmalı? (Tüm SRS mi, sadece SW'ye tahsisli olanlar mı?) — kapsama boşluğu hesabı buna bağlı.
5. **Dokümanları dış bir LLM API'sine göndermek serbest mi?** Değilse M1–M2 yapısal kontrolle başlanır, M3 için kurum içi model planlanır.
6. Rapor dili ve formatı: Excel yeterli mi, Word yorumları da isteniyor mu?
7. Standart bağlamı: DO-178C / MIL-STD-498 / ARP4754A gibi bir şablon kullanılıyor mu? (Rubrik ifadelerini buna göre yazarız.)
