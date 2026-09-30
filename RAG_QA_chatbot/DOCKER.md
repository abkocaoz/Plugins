# Docker ile Çalıştırma

Kaynak: [Agenta-AI/agenta · examples/python/RAG_QA_chatbot](https://github.com/Agenta-AI/agenta/tree/main/examples/python/RAG_QA_chatbot)

Üç servis çalışır:

| Servis     | Port | Açıklama                              |
|------------|------|---------------------------------------|
| `qdrant`   | 6333 | Yerel vektör veritabanı               |
| `backend`  | 8000 | FastAPI (RAG pipeline)                |
| `frontend` | 3000 | Next.js sohbet arayüzü (`/api` → backend) |

## 1. Ortam değişkenleri

```bash
cp env.example .env
```

`.env` içinde en az şunları doldurun:

```bash
OPENAI_API_KEY=sk-...
QDRANT_URL=http://qdrant:6333   # yerel Qdrant container'ı
QDRANT_API_KEY=                 # yerel Qdrant için boş bırakın
# İsteğe bağlı: AGENTA_API_KEY, COHERE_API_KEY
```

Qdrant Cloud kullanacaksanız `QDRANT_URL` / `QDRANT_API_KEY` değerlerini ona göre girin.

## 2. Başlatma

```bash
docker compose up -d --build
```

- Arayüz: http://localhost:3000
- API sağlık kontrolü: http://localhost:8000/health

## 3. Dokümanları yükleme (ingest)

`.mdx` dokümanlarınızı `./docs` klasörüne koyun, sonra:

```bash
docker compose run --rm ingest \
  --source /docs \
  --base-url https://docs.example.com \
  --recreate
```

## Diğer komutlar

```bash
docker compose logs -f backend   # logları izle
docker compose down              # durdur
docker compose down -v           # durdur + Qdrant verisini sil
```

## Upstream'e göre değişiklikler

- `frontend/next.config.js`: `output: "standalone"`, backend adresi `BACKEND_URL`
  build argümanından okunuyor; vendored UI bileşenlerindeki tip hataları nedeniyle
  production build'de tip kontrolü kapalı.
- `frontend/app/page.tsx`: `useChat` için AI SDK v6 uyumlu `DefaultChatTransport`.
- `run-agent-chat-slice.sh` (Agenta monoreposuna bağımlı) kaldırıldı.
