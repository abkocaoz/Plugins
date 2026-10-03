# Giriş UX Planı — Basit Ana Ekran

Mirror of the Project store plan. See also store path `docs/giris-ux-plani.md`.

## Hedef
Yerel demoda **tek ekrandan** inceleme başlatma. İlk ekranda API token, UUID veya prompt seçici yok.

## Ana akış (`/ui`)
1. **Doküman** — yeni yükle veya mevcut revizyon seç.
2. **Checklist tanımı** — registry’deki seedable katalog.
3. **Başlat** — extract/reference gerektiği kadar çalışır; checklist’e yönlendirir.

## Gizlenenler
Token, ham UUID’ler, job/prompt plumbing — varsayılan yolda gizli. Bağlam: `acr_session` + query.

## Kolaylık API
- `GET /api/v1/ui/home`
- `GET /api/v1/projects/{id}/document-revisions`
- `POST /api/v1/ui/start-review`
