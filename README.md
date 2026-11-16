# Freya · Sesli teslimat asistanı

Next.js operasyon paneli, FastAPI veri servisi ve Python LiveKit Agents worker ile kredi kartı yeniden teslimat demosu. Sekiz müşteri ve beş kurye penceresi PDF'den aynen seed edilir. Bu ilk sürüm tarayıcı mikrofonuyla çalışır; gerçek telefon araması yapmaz.

## Kurulum

Node.js 22+, Python 3.11+ ve [uv](https://docs.astral.sh/uv/) gerekli.

`backend/.env` ve `frontend/.env.local` oluşturuldu. Ortak `BACKEND_API_KEY` yerel kullanım için üretildi. Kullanıcıdan gerekenler `backend/.env` içinde:

| Değişken | Kaynak / amaç |
| --- | --- |
| `LIVEKIT_URL` | LiveKit Cloud proje WebSocket URL'si (`wss://…`) |
| `LIVEKIT_API_KEY` | Aynı LiveKit projesinin API anahtarı |
| `LIVEKIT_API_SECRET` | Aynı projenin gizli anahtarı |
| `ELEVEN_API_KEY` | ElevenLabs API anahtarı; STT ve TTS erişimi |
| `ELEVEN_VOICE_ID` | Hesabında erişebildiğin, Türkçe için denediğin ses |
| `GOOGLE_API_KEY` | Gemini API anahtarı |

LLM olarak yalnız Gemini kullanılır. Anahtarları sohbete veya git'e ekleme. Yeni checkout için `.env.example` dosyalarını ilgili yerel env dosyalarına kopyala ve iki serviste aynı `BACKEND_API_KEY` ayarla. Frontend'in env dosyasında yalnız backend adresi ve servis anahtarı bulunur; model anahtarları tarayıcıya gönderilmez.

```sh
cd backend
uv sync
uv run python -m app.agent download-files
```

Üç ayrı terminal:

```sh
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

```sh
cd backend
uv run python -m app.agent dev
```

```sh
cd frontend
npm install
npm run dev
```

`http://localhost:3000` adresini aç, müşteri seç, sesli görüşmeyi başlat ve mikrofon izni ver. Demo doğum tarihlerini [case analizinde](docs/case-analysis.md) bulabilirsin. Panel, worker ve API aynı yerel SQLite dosyasını kullanır; API ile worker'ı aynı makinede çalıştır.

## Model hattı

`Mikrofon → LiveKit → ElevenLabs Scribe v2 Realtime → Gemini → ElevenLabs Flash v2.5 → Hoparlör`

- STT: `scribe_v2_realtime`, dil `tr`. ElevenLabs anahtarı kullanır.
- TTS: `eleven_flash_v2_5`, dil `tr`; ses kimliği zorunlu. Kalite karşılaştırması için `ELEVEN_TTS_MODEL=eleven_multilingual_v2` denenebilir.
- LLM: Gemini, varsayılan `GOOGLE_MODEL=gemini-3.1-flash-lite`. Model env üzerinden değiştirilebilir; hesap erişimi ve Türkçe araç kullanımı canlı testte doğrulanmalıdır.
- VAD: yerel Silero; ek servis anahtarı gerekmez. `download-files` modeli indirir.
- Embedding, vektör veritabanı veya ayrı bir planlayıcı gerekmiyor: bilgi küçük ve yapılandırılmış; SQL sorguları yeterli.

ElevenLabs doğrudan plugin ile çağrılır. LiveKit Inference kredisi, ElevenLabs API anahtarının yerini tutmaz. Sağlayıcı ücretleri kendi hesaplarına yansır.

## Yapı

```text
frontend/app/                 Next.js panel ve sunucu API proxy
frontend/components/          LiveKit mikrofon, ses çıkışı, agent durumu
backend/app/main.py           Kimlik korumalı dashboard ve görüşme oluşturma
backend/app/agent.py          AgentServer, modeller, function tools
backend/app/gemini_completion.py Gemini generateContent ve araç yanıtı aktarımı
backend/app/prompts/delivery.md Türkçe kimlik, akış, istisnalar, sınırlar
backend/app/store.py          SQLite veri, doğrulama, atomik rezervasyon
backend/tests/                İş kuralı ve eşzamanlılık testleri
docs/                         Case analizi ve sonraki geliştirmeler
```

Agent'in araçları veri servisiyle aynı Python servis katmanını çağırır. Araç girdilerinde müşteri kimliği yoktur; görüşme kimliği sunucudaki dispatch metadata'sından gelir. Doğum tarihi modele verilmez. Tarih doğrulama, müşteri bazlı iki başarısız deneme sınırı, ilçe kontrolü, tek rezervasyon, terminal durum ve kapasite kontrolü SQL/Python tarafında uygulanır. `BEGIN IMMEDIATE` eşzamanlı son yer yarışında iki rezervasyonu engeller. Aynı rezervasyonun tekrarı idempotenttir.

Müşterinin açık onayı prompt ve `confirmed` araç alanıyla temsil edilir. Bu alan model tarafından doldurulur; bağımsız kullanıcı onay kanıtı değildir. Üretimde onay kanıtı ve güçlü doğrulama ayrıca tasarlanmalıdır.

Panelin API anahtarı sunucular arasıdır; operatör kullanıcı girişinin yerine geçmez. Panel yalnız localhost demosu içindir. Public yayın öncesi kullanıcı kimliği, yetkilendirme ve rate limit eklenmelidir. `DEMO_MODE=false` müşteri seçerek görüşme açmayı kapatır.

## Kontroller

```sh
cd backend
uv run python -m unittest discover -s tests -v
cd ../frontend
npm run typecheck
npm run build
```

Bu çalışma ortamında npm/PyPI DNS erişimi başarısız olduğundan bağımlılık kurulumu, Next.js derlemesi ve canlı ses entegrasyonu tamamlanamadı. İş kuralı testleri sistem Python'uyla çalıştırıldı; kesin sonuçlar geliştirme notunda. SDK kaynakları resmi dokümantasyonla karşılaştırıldı; kurulum sonrası tüm entegrasyon kontrolleri yine çalıştırılmalı.

## Demo senaryoları

1. Ayşe: doğru doğum tarihi → Kadıköy saati → kimlikle şahsen teslim koşulu → açık onay → rezervasyon.
2. Yanlış doğum tarihi → müşteri bazında iki başarısız denemede kilit → rezervasyon yok.
3. Kadıköy'de iki yer dolduktan sonra üçüncü müşteri → uygun yer yok.
4. Aynı son yer için iki görüşme → tek kazanan; diğerine tekrar sorgulama.
5. “Komşuma bırakın”, başka ilçe, adres değişikliği → destek gerekli, rezervasyon yok.
6. Kullanıcı konuşurken agent'i böl → ses kesilmesi ve konuşma sırasını canlı doğrula.

Kaynaklar: [LiveKit quickstart](https://docs.livekit.io/agents/start/voice-ai/), [ElevenLabs STT](https://docs.livekit.io/agents/models/stt/elevenlabs/), [ElevenLabs TTS](https://docs.livekit.io/agents/models/tts/elevenlabs/).

## Geri aranma talepleri

Müşteri şimdi konuşamıyorsa asistan kesin gün/saat ve açık onay alarak `request_callback` aracını çağırır. Talep, kayıtlı müşteri ve numarayla ilişkilendirilir; doğum tarihi doğrulaması gerektirmez ve teslimat kapasitesi ayırmaz. Geçmiş veya saat dilimsiz zaman reddedilir. Aynı müşteri için tek bekleyen talep tutulur; aynı görüşmenin tekrar çağrısı çift kayıt oluşturmaz.

`callback_requests` tablosu `initialize()` sırasında mevcut verilere dokunmadan eklenir. Panelin geri aranma bölümünde İstanbul saatiyle görünen talepler, geri arama yapıldıktan sonra tamamlandı veya iptal olarak işaretlenebilir. Bu akış operasyon takibi sağlar; otomatik telefon araması başlatmaz ve tercih edilen saatte kesin arama garantisi vermez. Doğrulama deneme sınırı müşteri bazında iki başarısız denemedir; yeni görüşmeyle sıfırlanmaz.

## Tek terminalden backend başlatma

Proje kökünde `bash scripts/start-backend.sh` çalıştır. API ve agent birlikte başlar;
terminal açık kaldığı sürece çalışırlar, Ctrl+C ile ikisi de kapanır.
Kayıtlar `.local/logs/api.log` ve `.local/logs/agent.log` dosyalarındadır.
Agent kaydında `registered worker` görünmeden sesli görüşme deneme.
Tarayıcıdaki oda bağlantısı ile agent hazır olma durumları ayrı gösterilir;
agent hazır olmazsa 45 saniye sonunda açıklayıcı hata verilir.

## Muhatap teyidi ve mevcut rezervasyon

Asistan açılışta aranan müşteriyle görüşüp görüşmediğini sorar ve `confirm_recipient` ile yanıtı kaydeder. `self` beyanı doğum tarihi doğrulamasının yerine geçmez. Telefonu başkası açtıysa `other_person`, yanlış numara/kayıt bildirildiyse `incorrect_details` sonucu kaydedilir; görüşme doğrulama, rezervasyon ve geri aranma işlemlerine kapanır. Kayıtlı müşteri bilgileri konuşma üzerinden değiştirilmez.

`calls.recipient_status` kolonu mevcut SQLite verilerine eklenen bir migration ile oluşturulur; eski görüşmeler `unknown` kabul edilir. Muhatap teyidi olmadan doğrulama ve geri aranma talebi alınmaz. Doğrulama başarılı olduğunda mevcut rezervasyonun tarih/saat, ilçe ve adres tipi yanıtla birlikte döner; ayrıca `get_existing_booking` aracı vardır. Bu bilgiler doğrulama öncesinde açılmaz. Mevcut plan korunacaksa `existing_booking_confirmed`, değişiklik veya kayıt itirazı varsa `needs_support` sonucu kullanılır; mevcut rezervasyon korunur. Panel bu sonuçları ayrı gösterir.

Kontrol: 19 iş kuralı testi başarılı. Gerçek konuşmada muhatap beyanının yorumlanması ve araç sırası ayrıca sesli test edilmelidir.

Backend'i terminalden bağımsız çalıştırmak için `bash scripts/start-backend.sh --background` kullan.
Supervisor kaydı `.local/logs/supervisor.log` dosyasındadır. Kod veya şema güncellendiğinde
API ve worker birlikte yeniden başlatılmalıdır; Python SDK'nin `dev` komutu bu sürümde
otomatik kod yenilemesi yapmaz. Her yeni görüşme şema geçişlerini ayrıca kontrol eder.

Gemini yanıtları `generateContent` üzerinden alınır. Bu ortamda SSE streaming çağrıları
503/504 verirken aynı modelin normal araç çağrıları başarılı olduğundan bu taşıma yolu
kullanılır. Model yanıtı tamamlanınca ElevenLabs ses üretir; araç yürütme LiveKit'tedir.
Gemini 3 thought signature değerleri araç yanıtı sonrası konuşma için korunur.


## Doğrulama sınırı ve tekrar aranmama tercihi

Müşterinin toplam iki başarısız doğum tarihi doğrulama hakkı vardır. Geçersiz/eksik tarih hak tüketmez; bir yanlışın ardından ikinci deneme doğruysa işlem devam eder. Başarısızlık sayacı müşteri bazında kalıcıdır, başarı veya yeni görüşme sayacı sıfırlamaz. İki başarısızlıktan sonra yeni görüşme, doğrulama ve geri aranma isteği engellenir; otomatik süreli açılma yoktur. Eski görüşmelerin deneme kayıtları migration sırasında başarısızlık sayacına aktarılır.

Muhatap kendisi olduğunu teyit ettikten sonra doğum tarihi doğrulaması gerekmeksizin açıkça tekrar aranmama talebi verebilir. `opt_out_calls` müşteri üzerinde `do_not_call` ve talep zamanını kaydeder, bekleyen geri aranma taleplerini iptal eder ve yeni görüşmeleri engeller. Teslimat rezervasyonları korunur. Agent tercih kaydedildikten sonra vedayı okuyup görüşmeyi kapatır. Sadece şimdi müsait olmamak veya görüşmeyi reddetmek kalıcı aranmama tercihi sayılmaz. Bu tercihi konuşmadan geri açan araç yoktur. Panel müşteri seçiminin yanında engeli gösterir ve görüşme başlatmayı kapatır.

## Yanlış numara / hatalı kayıt engeli

`incorrect_details` sonucu artık yalnız görüşmeye değil müşteriye de kaydedilir. `customers.contact_review_status=pending`, bildirim zamanı ve kaynak görüşme tutulur. Mevcut yanlış kayıt bildirimleri migration sırasında müşteri etiketine aktarılır. Yeni görüşme ve geri aranma talebi backend'de engellenir; bekleyen geri arama talepleri iptal edilir. Önceden açılmış görüşmeler de müşterinin engelini aşarak doğrulama veya rezervasyon yapamaz. Mevcut teslimat kaydı korunur.

Panel müşteri seçeneğinde etiketi, seçim altında açıklamayı ve ayrı kayıt inceleme listesini gösterir; görüşme başlatma düğmesi kapanır. Telefonu yakınının açması (`other_person`) kalıcı yanlış numara engeli oluşturmaz. Kayıt düzeltme ve engeli yeniden açma arayüzü bu değişiklikte eklenmedi; inceleme etiketi otomatik temizlenmez.
