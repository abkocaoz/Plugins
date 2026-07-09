# DOORS Kalıcı Filtre Yöneticisi

IBM DOORS 9.x (klasik, DXL destekli) için iki bileşenli filtre çözümü:

| Bileşen | Dosya | Görev |
|---|---|---|
| Filtre Editörü (Python/Tkinter) | `doors_filter_editor.py` | Filtre tanımlarını oluşturur/düzenler, `filters.json` + `filters.dat` kaydeder, kullanıcıya özel DXL üretir |
| Filtre Paneli (DXL) | `doors_filter_panel.dxl` | DOORS formal modül içinde panel açar, filtreleri uygular/kaldırır/AND-OR birleştirir |

`examples/` klasöründe örnek `filters.json` ve ondan üretilmiş `filters.dat`
vardır (örnek adlar, dosyalar her kodlamada bayt-uyumlu kalsın diye bilinçli
olarak ASCII'dir; Türkçe karakterli adlar da desteklenir, aşağıya bakın).

## Format kararı: neden `filters.json` + `filters.dat`?

- **`filters.json`** kanonik kayıttır: insan okunabilir, sürüm kontrolüne uygun,
  Python tarafında güvenle ayrıştırılır. (İstek gereği kayıt formatı JSON'dur.)
- **`filters.dat`** DXL'in okuduğu satır bazlı türetilmiş kopyadır. DXL'de JSON
  parser yoktur; DXL ile sağlam bir JSON ayrıştırıcı yazmak (tırnak kaçışları,
  Unicode, iç içe yapılar) hataya çok açıktır. Bunun yerine editör her
  "Dosyaya Kaydet"te JSON'un yanına şu formatta bir `.dat` üretir:

  ```
  FILTER
  name=Yüksek Öncelik ve Kapanmamış
  attr=Priority
  op=equals
  val=High
  logic=AND
  attr=Status
  op=not_equals
  val=Closed
  END
  ```

  Kurallar (format v2): `#` ile başlayan satır yorumdur; kayıtlar
  `FILTER`/`END` blokları içindedir; her satır **ilk** `=` işaretinden bölünür
  (değerler `=` içerebilir); her koşul `attr=`, `op=`, `val=` üçlüsüdür ve
  koşullar arasına `logic=AND|OR` satırı girer. Bir filtre **1..10 koşul**
  içerebilir; koşullar dosyadaki sırayla **soldan sağa** birleştirilir:
  `((k1 ∘ k2) ∘ k3) …`. Eski v1 dosyaları (attr1/op1/… anahtarlı) hem Python
  editör hem DXL parser tarafından geriye dönük uyumlu okunur. Değerler satır
  sonu içeremez (editör bunu engeller). Bu format DXL'de ~60 satırlık,
  kırılgan olmayan bir durum makinesiyle okunur. **`.dat` dosyasını elle
  düzenlemeyin; her zaman editörden kaydedin.**
- Kodlama: `.json` UTF-8; `.dat` ise DOORS klasik DXL dosyaları yerel ANSI kod
  sayfasıyla okuduğu için **cp1254** (Türkçe Windows) ile yazılır. Farklı yerel
  ayarda DOORS kullanıyorsanız `doors_filter_editor.py` içindeki `DAT_ENCODING`
  sabitini değiştirin.

## Kurulum ve kullanım

### 1) Python editör

Gereksinim: Python 3.8+ (yalnızca standart kütüphane; Tkinter, python.org
kurulumlarında hazır gelir).

```
python doors_filter_editor.py
```

1. İlk açılışta karşılama ekranındaki **Klasör Seç ve Başla** ile filtrelerin
   saklanacağı klasörü seçin (mevcut `filters.json` varsa otomatik yüklenir;
   son kullanılan klasör hatırlanır ve sonraki açılışta kendiliğinden açılır).
2. **+ Yeni Filtre** veya **Hazır Şablonlar** ile başlayın. Formda cümle kurar
   gibi ilerlersiniz: attribute (yaygın DOORS attribute'ları öneri listesinde),
   Türkçe operatör (içerir / eşittir / eşit değildir / boştur / büyüktür /
   küçüktür) ve değer. **+ Koşul ekle (VE / VEYA)** bağlantısıyla istediğiniz
   kadar (en çok 10) koşul ekler, her koşulun başındaki açılır kutudan VE/VEYA
   bağlacını seçer, `×` ile koşulu kaldırırsınız. Üçten fazla koşulda birleşim
   **soldan sağa** uygulanır (parantez gruplaması yoktur) ve form bunu bir
   ipucuyla hatırlatır. Alttaki **canlı önizleme**, filtrenin DOORS'ta ne
   yapacağını siz yazarken renkli bir cümle olarak gösterir.
3. **Filtreyi Kaydet** → filtre listeye eklenir ve `filters.json` +
   `filters.dat` **otomatik olarak** diske yazılır (ayrı bir "dosyaya kaydet"
   adımı yoktur; durum çubuğunda "✓ Kaydedildi" görünür). **Kopyala** mevcut
   bir filtreden türetmenizi sağlar, **Sil** kaldırır.
4. **DXL Üret → DOORS'ta kullan** → `filters.dat`'ın DOORS makinesindeki
   yolunu doğrulayın (dosya başka makinede duracaksa oradaki yolu yazın) ve
   `.dxl` dosyasını kaydedin. Üretilen DXL'e yol otomatik gömülür.

GUI olmadan üretim de mümkündür:

```
python doors_filter_editor.py --emit-dxl doors_filter_panel.dxl --dat-path "C:\DOORS_Filters\filters.dat"
python doors_filter_editor.py --export-dat filters.json filters.dat
```

### 2) DXL panelini DOORS'a ekleme

**Yöntem A — Tools > Edit DXL (en hızlı):**

1. DOORS'ta bir **formal modül** açın (panel yalnızca formal modülde çalışır).
2. Modül penceresinde **Tools > Edit DXL…** açın.
3. **Load…** ile üretilen `.dxl` dosyasını yükleyin, **Run** deyin.
4. Panel modsuz (non-modal) açılır; modülde çalışmaya devam edebilirsiniz.

**Yöntem B — Menü addin'i (kalıcı menü öğesi):**

1. `.dxl` dosyasını DOORS istemcisindeki addins klasörüne kopyalayın, örn.
   `C:\Program Files\IBM\Rational\DOORS\9.7\lib\dxl\addins\user\doors_filter_panel.dxl`
   (klasör yoksa oluşturun; site kurulumlarında `-addins` komut satırı
   anahtarıyla farklı bir kök tanımlı olabilir).
2. Aynı addins yapısındaki `user.idx` dosyasına script'i tanıtan bir satır
   ekleyin; DOORS yeniden başlatılınca formal modül penceresinde **User**
   menüsü altında görünür. `.idx` satır biçimi DOORS sürümüne göre küçük
   farklılıklar gösterebilir — kendi sürümünüzün *"Customizing DOORS /
   Adding DXL menus"* belgesindeki örneği baz alın (bu adım Yöntem A'nın
   aksine sürüm belgesinden doğrulanmalıdır).

### 3) Panel kullanımı

- **Uygula** — seçili filtreyi kurar ve `set(module, filter)` + `filtering on`
  ile uygular (mevcut filtre katmanını değiştirir).
- **AND ile Ekle / OR ile Ekle** — seçili filtreyi, panelden uygulanmış aktif
  filtreyle `&&` / `||` operatörleriyle birleştirip uygular; aktif filtre yoksa
  doğrudan uygular. "Aktif filtre" satırı birleşimi gösterir,
  örn. `(Onaylı Gereksinimler) AND ('shall' İçeren Nesneler)`.
- **Filtreyi Kaldır** — `filtering off` ile filtrelemeyi kapatır; view, kolonlar
  ve sıralama aynen korunur.
- **Detay** — seçili filtrenin koşulunu gösterir.
- **Yeniden Yükle** — `filters.dat` değiştiyse (editörde yeniden kaydettiyseniz)
  listeyi dosyadan tazeler.

**View güvenliği:** Script yalnızca çalışma zamanı filtre katmanını değiştirir;
view/kolon düzenine yazmaz ve hiçbir şeyi kaydetmez. Filtre uygulanmışken
view'ı elle kaydederseniz filtre view'a işlenir — istemiyorsanız kaydetmeden
önce **Filtreyi Kaldır** deyin.

**Hata dayanıklılığı:** Attribute modülde tanımlı değilse filtre kurulmadan
önce `find(Module, attrName)` ile denetlenir ve script çökmez; açıklayıcı bir
mesaj kutusu gösterilip panel çalışmaya devam eder. Veri dosyası yoksa da panel
açılır, "Yeniden Yükle" ile sonradan yüklenebilir.

## DXL API doğrulama notları (DOORS 9.7.2.x)

DXL Reference Manual'da belgeli olup yaygın kullanımla kesinliğinden emin
olduğum çağrılar: `pragma runLim` · `Stream read(string)` / `>>` (satır okuma) /
`end of` / `close` · `Filter contains(attribute string, string, bool)` ·
attribute karşılaştırma filtreleri `==` `!=` `<` `>` · filtre birleştirme
`&&` `||` · `set(Module, Filter)` · `filtering on/off` · `refresh(Module)` ·
`AttrDef find(Module, string)` · `null` denetimleri · DB/DBE: `create`, `label`,
`list`, `field`, `button`, `realize`, `show`, `hide`, `insert(DBE,int,string)`,
`delete(DBE,int)`, `set(DBE,…)`, `get(DBE)` · `ack` · `Module current` ·
`string type(Module)`.

**Elinizdeki 9.7.2.x kurulumunda doğrulanmasını önerdiğim noktalar** (script
bunlara dikkatle, kolay değiştirilebilir şekilde yazıldı):

1. `Stat create(string)` / `delete(Stat)` — dosya varlık denetimi için
   kullanıldı (OS commands bölümünde belgelidir). Derleme hatası verirse
   `loadFilters()` içindeki `Stat` bloğunu silebilirsiniz; tek fark, dosya
   yokken DXL'in kendi çalışma zamanı hatasını göstermesi olur.
2. `contains(...)` üçüncü parametresinin anlamı (büyük/küçük harf duyarlılığı).
   Script `false` = duyarsız varsayar; tersini isterseniz `buildCondition`
   içinde `true` yapın.
3. `>` / `<` filtrelerinin sayı/tarih attribute'larında tip-farkındalıklı
   karşılaştırma yaptığı (string attribute'larda sözlük sırası uygulanır).
4. `noElems(DBE)` bilinçli olarak **kullanılmadı** (liste boyutu global
   değişkenle izlenir) — eski sürümlerde davranışı değişkendir.

## Bilinen sınırlamalar

- Koşullar parantezle gruplanamaz; birleşim her zaman soldan sağadır:
  `k1 VEYA k2 VE k3` = `((k1 VEYA k2) VE k3)`. Karmaşık gruplama gerekiyorsa
  filtreyi ikiye bölüp DOORS panelindeki "AND/OR ile Ekle" düğmeleriyle
  birleştirebilirsiniz.
- Çok değerli (multi-valued) enumeration attribute'larında `equals` tam eşleşme
  arar; "değerlerden birini içeriyor" davranışı için DXL `includes()` gerekir
  (bu sürümde yok, ihtiyaç olursa `buildCondition`'a operatör olarak eklenebilir).
- `is empty`, `attribute == ""` ile gerçeklenir; bu, boş string ile hiç
  atanmamış (null) değeri aynı sayar — pratikte istenen davranış budur.
- AND/OR birleştirme yalnızca **panelden** uygulanan filtreleri izler; DOORS
  arayüzünden elle kurulmuş bir filtreyle birleştirmez (DXL'de modülün mevcut
  `Filter` nesnesini okuyan güvenilir bir getter yoktur).
- Panel, DOORS'un pencereye eklediği standart `Close` düğmesiyle kapatılır;
  script'i yeniden çalıştırmak yeni bir panel açar.
- DXL dosyası bilinçli olarak yalnız ASCII içerir (DXL editörü Unicode
  dosyaları güvenilir açamaz); bu yüzden panel metinleri aksansız Türkçedir.
  Filtre adları/değerlerindeki Türkçe karakterler `.dat` üzerinden cp1254 ile
  taşınır ve DOORS'ta doğru görünür.

## Sorun giderme

- **"Veri dosyasi bulunamadi"** — Editörde *Dosyaya Kaydet* yapıldığından ve
  DXL üretirken girilen yolun DOORS makinesinden erişilebilir olduğundan emin
  olun (ağ sürücüsü harfi DOORS'un çalıştığı oturumda bağlı olmalı).
- **"Oznitelik bu modulde tanimli degil"** — Attribute adı büyük/küçük harf
  dahil modüldekiyle birebir aynı olmalı (ör. `Object Text`).
- **Türkçe karakterler DOORS'ta bozuk** — DOORS istemcisi Türkçe olmayan bir
  Windows yerel ayarında çalışıyordur; `DAT_ENCODING`'i uygun kod sayfasına
  çekip yeniden kaydedin.
- **Liste eski görünüyor** — Editörde kaydettikten sonra panelde
  *Yeniden Yükle*'ye basın.
