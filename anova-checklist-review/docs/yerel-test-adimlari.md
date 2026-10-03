# Yerel Test Adımları (Bu Mac)

Bu rehber **kendi bilgisayarınızda** çalışan sadeleştirilmiş demo içindir.

**UI:** http://127.0.0.1:18080/ui  
Token otomatik (`dev-change-me`) — ana ekranda yapıştırmanız gerekmez.

Checkout: `/Users/abkocaoz/Desktop/dev/Plugins`  
Branch: `cursor/phase1-checklist-foundation-a927`  
App: `anova-checklist-review/`  
Compose proje adı: `anova-checklist-review`  
Gateway: yalnızca `127.0.0.1:18080`

UX planı: [giris-ux-plani.md](./giris-ux-plani.md)

## Hızlı yol (3 adım)

### 1) Ana sayfa
1. Aç: [http://127.0.0.1:18080/ui](http://127.0.0.1:18080/ui)
2. İlk seferde / boş listede: **Gelişmiş → Örnek veri yükle (Live Demo)**  
   (veya kendi dosyanızı **Yeni yükle** ile seçin)
3. **Mevcut revizyon**dan doküman seçin.
4. **Checklist** seçin (varsayılan: Software Code Standard).
5. **Başlat** — extract/reference gerektiği kadar çalışır; checklist sayfasına yönlendirir.

### 2) Checklist sonuçları
- Otomatik açılır: `/ui/checklist` (bağlam query + `localStorage`)
- Maddeleri görüntüle → isteğe bağlı insan kararı kaydet
- Export (taslak / onaylı) — sentetik Excel şablonu

### 3) Referanslar (isteğe bağlı)
- [http://127.0.0.1:18080/ui/references](http://127.0.0.1:18080/ui/references)  
- Document version ID yapıştırmanız gerekmez; ana akış bağlamı kullanır.

## Durum kontrolü (terminal)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/health   # 200
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/ui       # 200
curl -sS -H 'X-API-Token: dev-change-me' http://127.0.0.1:18080/api/v1/ui/home | head -c 400
docker compose -p anova-checklist-review -f /Users/abkocaoz/Desktop/dev/Plugins/anova-checklist-review/docker-compose.yml ps
```

## Durdurma (yalnız bu proje)
```bash
cd /Users/abkocaoz/Desktop/dev/Plugins/anova-checklist-review
docker compose -p anova-checklist-review down
```
Diğer Docker konteynerlerine dokunmayın; global prune kullanmayın.

## Bilinen sınırlar
- Gerçek production Excel şablonları yok (uydurulmadı).
- Ollama modeli yoksa LLM (`document_content`) maddeleri ERROR verebilir; deterministic yol çalışır.
- Prompt seçici ilk ekranda yok (bilinçli).
