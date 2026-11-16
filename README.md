# Freya · Sesli teslimat asistanı

Başarısız kredi kartı teslimatından sonra müşteriyle Türkçe konuşarak yeni kurye teslimatı planlayan demo. Next.js operasyon paneli, FastAPI servisi, LiveKit Agents worker ve SQLite kullanır.

**Mevcut kapsam:** Tarayıcı mikrofonuyla sesli görüşme, muhatap teyidi, doğum tarihi doğrulaması, mevcut rezervasyon kontrolü, kapasiteye göre rezervasyon, geri aranma talebi, tekrar aranmama tercihi ve yanlış kayıt nedeniyle arama engeli uygulanmıştır. Gerçek telefon araması, otomatik geri arama ve rezervasyon değiştirme/iptal henüz yoktur.

Bu belge mevcut kodun davranışını anlatır. Prompt ile yönlendirilen konuşma davranışları, veritabanında zorunlu uygulanan kurallardan ayrı belirtilmiştir.

## Görev ve demo verileri

Kaynak görev belgesi `Freya-FDE-On-Test.pdf`: Salı günü adreste bulunamayan sekiz müşteriyi arayıp aynı hafta için yeniden teslimat planlamak. Bankanın müşteri ve kurye verisini tutan servisi de bu projenin parçasıdır. Görevde arayüz zorunlu değildir; panel operasyon ve demo için eklenmiştir.

| İlçe | Müşteri sayısı | Kurye pencereleri | Toplam yer |
| --- | --- | --- | --- |
| Kadıköy | 3 | Perşembe 09:00–13:00; Cuma 14:00–18:00 | 2 |
| Ataşehir | 2 | Perşembe 14:00–18:00 | 2 |
| Şişli | 2 | Cuma 09:00–13:00 | 2 |
| Beşiktaş | 1 | Perşembe 09:00–13:00 | 1 |

Sekiz müşteri için toplam yedi yer vardır. Kadıköy'deki üçüncü müşteride kapasitenin bitmesi beklenen sonuçtur; herkesin rezervasyon alması başarı ölçütü değildir. Müşteri listesi ve demo doğum tarihleri [case analizindedir](docs/case-analysis.md).

Kart yalnız sahibine, kimliği görülerek teslim edilir. Asistan rezervasyon öncesinde bu koşulu açıklayıp açık onay istemelidir; başarılı rezervasyonun kapanış mesajında da kimlik gösterme gereğini tekrarlar. Gerçek sokak adresi sağlanmadığından yalnız ilçe ve ev/iş yeri bilgisi tutulur.

### Açık varsayımlar

- Senaryo haftası `DEMO_WEEK_START=2026-11-16` ile sabitlenmiştir; teslimat tarihleri 19 ve 20 Kasım 2026'dır. Ayar pazartesi olmalıdır.
- Mevcut SQLite dosyasında hafta ayarını değiştirmek eski teslimatları taşımaz. Farklı demo haftası için ayrı `DATABASE_PATH` kullanılır. Mevcut dosyadaki müşteri ve rezervasyonlar seed sırasında ezilmez.
- Doğum tarihi, demo kimlik kontrolüdür; gerçek banka için güçlü kimlik doğrulaması değildir.
- Müşteri başına tek rezervasyon vardır. Değişiklik, iptal ve adres güncelleme destek kanalına yönlendirilir.
- Kurye yeri konuşma sırasında tutulmaz; yalnız başarılı rezervasyon işleminde tüketilir.
- Geri aranma saati müşterinin tercihidir; kesin arama garantisi veya otomatik arama görevi değildir.

## Mimari ve ses hattı

```text
Tarayıcı / Next.js panel
  ├─ Sunucu API proxy → FastAPI → store.py → SQLite
  └─ Mikrofon / hoparlör ↔ LiveKit odası ↔ Python agent
                                          └─ store.py → aynı SQLite dosyası
```

Panel ile agent, müşteri kimliğini tarayıcıdan araç parametresi olarak almaz. Backend müşteri için `call_id` oluşturur; agent bu kimliği sunucunun dispatch metadata'sından alır. API ve worker aynı servis katmanını, aynı makinedeki aynı SQLite dosyasını kullanır. Agent iş kuralları için FastAPI'ye HTTP isteği yapmak yerine `store.py` fonksiyonlarını çağırır.

Ses hattı:

```text
Mikrofon → LiveKit → ElevenLabs STT → Gemini → ElevenLabs TTS → Hoparlör
```

| Bileşen | Varsayılan |
| --- | --- |
| Konuşmayı metne çevirme | ElevenLabs `scribe_v2_realtime`, Türkçe |
| Dil modeli | Gemini `gemini-3.1-flash-lite` |
| Metni sese çevirme | ElevenLabs `eleven_flash_v2_5`, Türkçe; ses kimliği gerekli |
| Konuşma etkinliği algılama | Yerel Silero VAD |
| Kalıcı veri | SQLite |

Gemini yanıtları `gemini_completion.py` içindeki `generateContent` taşıması üzerinden alınır. Yanıt tamamlandığında LiveKit araçları yürütür ve ses üretimini yönetir. Araç turlarında Gemini thought signature değerleri korunur. Bazı muhatap yanıtları, tarih girdileri ve başarılı araç sonuçları ek model çağrısı olmadan işlenir veya sabit yanıtla seslendirilir.

Model ve ses ayarları ortam değişkenlerinden değiştirilebilir. Sağlayıcı erişimi ve model uyumluluğu hesap üzerinde doğrulanmalıdır. ElevenLabs için ayrı API anahtarı gerekir; LiveKit kredisi bunun yerine geçmez.

## Görüşme akışı

1. Agent adıyla hitap ederek kendini yapay zekâ asistanı olarak tanıtır ve doğru kişiyle görüşüp görüşmediğini sorar.
2. Muhatap yanıtı `confirm_recipient` ile kaydedilir. Kişinin “benim” demesi doğum tarihi doğrulamasının yerine geçmez.
3. Müşteri şimdi müsait değilse geri aranma akışına geçilir. Açıkça tekrar aranmak istemiyorsa kalıcı aranmama tercihi alınır.
4. Müşteri müsaitse doğum tarihi sorulur; belirsiz tarih netleştirilir. Beklenen doğum tarihi modele verilmez.
5. Doğrulama başarılıysa mevcut rezervasyon kontrol edilir. Rezervasyon varsa yeni seçenek sunmak yerine mevcut plan ele alınır.
6. Rezervasyon yoksa yalnız müşterinin ilçesindeki kalan yerler sunulur.
7. Seçilen tam tarih/saat ve şahsen kimlikle teslim koşulu tekrar edilir; açık onaydan sonra rezervasyon aracı çağrılır.
8. Veritabanı başarı döndürünce sonuç özetlenir. Başarılı rezervasyon, mevcut plan teyidi, yanlış muhatap, geri aranma kaydı ve aranmama tercihi gibi desteklenen kapanışlarda veda seslendirmesi tamamlanınca oda kapatılır.

### Sesli iletişim kuralları

Prompt kısa ve doğal Türkçe, her seferinde tek soru, sessizlik veya belirsiz ifadeyi onay saymama ve anlaşılmayan bilgiyi netleştirme kuralları içerir. Teknik araç çıktıları, kimlikler ve hata kodları müşteriye okunmamalıdır. Kart şifresi, güvenlik kodu, SMS kodu veya ödeme istenmez; banka iletişim bilgisi uydurulmaz.

Prompt sayıları konuşmada yazıyla ifade etmeyi ister. Sabit araç yanıtlarının bazı tarih/saatleri halen rakamla biçimlendirmesi nedeniyle seslendirme kalitesi canlı test edilmelidir. Tarih ve diğer araç parametreleri, sesli anlatımdan bağımsız olarak araçların beklediği yapısal biçimde gönderilir.

## Senaryolar ve güncel durum

| Senaryo | Uygulanan davranış | Sınır / kalan iş |
| --- | --- | --- |
| Doğru müşteri, doğru doğum tarihi | Doğrulama sonrası rezervasyon veya müsaitlik bilgisi açılır | Doğum tarihi yalnız demo doğrulamasıdır |
| İlk yanlış doğum tarihi | Müşterinin başarısızlık sayısı artar, bir hak kalır | Belirsiz/geçersiz tarih hak tüketmez |
| İkinci yanlış doğum tarihi | Müşteri bazında kilit; yeni görüşme, doğrulama ve geri aranma engellenir | Otomatik süreli sıfırlama veya kilit açma ekranı yok |
| Yeni görüşme ile tekrar deneme | Önceki başarısızlıklar korunur | Başarı da önceki başarısızlığı sıfırlamaz |
| Telefonu yakınının/başkasının açması | `other_person` sonucu; bilgi paylaşmadan veda ve kapanış | Tek başına müşteride kalıcı yanlış numara engeli oluşturmaz |
| Yanlış numara / hatalı müşteri kaydı | `incorrect_details`; müşteri inceleme bekliyor, yeni aramalar engelli | Düzeltme ve engeli kaldırma ekranı yok |
| Şimdi konuşamama | Açık talep ve kesin gelecekteki zamanla geri aranma kaydı | “Şimdi müsait değilim” kalıcı aranmama sayılmaz |
| Tekrar aranmak istememe | Kalıcı tercih, yeni arama engeli, bekleyen geri aramaların iptali | Müşterinin kendisi olduğu teyit edilmeli; doğum tarihi gerekmez |
| Mevcut rezervasyon | Yalnız doğrulama sonrası getirilir, mevcut planın korunması sorulur | Değişiklik veya itirazda destek sonucu; mevcut kayıt korunur |
| Açık onay olmadan rezervasyon | `confirmed` alanı olmadan işlem reddedilir | Alanı model doldurur; bağımsız kullanıcı onay kanıtı yok |
| Başka ilçedeki yere rezervasyon | Servis katmanı reddeder | İlçe/adres güncelleme yok |
| Yakına teslimat / adres değişikliği | Prompt reddeder ve destek kanalına yönlendirir | Gerçek insan aktarımı yok |
| Aynı son yer için eşzamanlı onay | Atomik işlemle tek kazanan; diğerine yer doldu hatası | Yeni seçenek için yeniden onay gerekir; geçici yer tutma yok |
| Aynı rezervasyonun tekrarı | Aynı müşteri ve yer için idempotent yanıt | Başka yere ikinci rezervasyon engellenir |
| İlçede yer kalmaması | Boş müsaitlik; `no_availability` sonucu kaydedilebilir | Bekleme listesi veya yeni kapasite bildirimi yok |
| Sunulan saatlerin müşteriye uymaması | Yeni saat uydurulmaz | Ayrı sonuç kodu ve operasyon akışı eksik |
| Kapanmış görüşmeden işlem | Doğrulama/rezervasyon/geri aranma kuralları duruma göre erişimi engeller | `booked` aynı rezervasyon tekrarı için yetkili durumdur |
| Agent'in hazır olmaması | Panel 45 saniye sonra hata gösterip bağlantıyı keser | Bu olayın SQLite görüşme sonucuna otomatik aktarımı eksik |
| Model kotası / bağlantı hatası | Sesli teknik hata açıklaması ve panel hata bildirimi; kota dolunca aynı oturumda yeni model istekleri durur | Kalıcı teknik hata ve tam yaşam döngüsü kaydı eksik |
| Kullanıcının bağlantıyı kesmesi | Panel oturumu kapatır | Görüşme sonucuna kopma/yarım kalma kaydı eklenmeli |

### Yanlış numara ve kayıt incelemesi

`incorrect_details`, hem görüşmede hem müşteri üzerinde saklanır. Müşterinin `contact_review_status` alanı `pending` olur; bildirim zamanı ve kaynak görüşme kaydedilir. Bekleyen geri arama talepleri iptal edilir. Önceden açılmış bir görüşme de müşteri engelini aşarak doğrulama veya rezervasyon yapamaz. Mevcut teslimat kaydı korunur.

Panel müşteri seçeneğinde etiketi, seçim altında açıklamayı ve ayrı kayıt inceleme listesini gösterir; görüşme başlatma düğmesi kapanır. Backend de aynı engeli bağımsız uygular. Bu etiket müşterinin tekrar aranmama tercihinden ayrıdır; otomatik temizlenmez.

### Geri aranma takibi

Kesin, gelecekte ve saat dilimi içeren tarih/saat ile açık onay gerekir. Muhatap teyidi zorunludur, doğum tarihi doğrulaması gerekmez. Talep kayıtlı müşteriye ve numaraya bağlıdır; başka numara alınmaz. Zaman UTC olarak saklanır, panel İstanbul saatiyle gösterir.

Aynı müşteri için tek bekleyen talep vardır. Aynı kaynak görüşme ve aynı zamanla tekrar çağrı çift kayıt oluşturmaz. Talep kapasite ayırmaz; kaynak görüşme `callback_requested` olur ve teslimat akışına kapanır. Operatör panelde talebi geri arama yapıldıktan sonra tamamlandı veya iptal olarak işaretleyebilir. Tamamlandı düğmesi telefon araması başlatmaz.

## SQLite veri modeli ve durumlar

Varsayılan dosya `backend/freya.sqlite3`; `DATABASE_PATH` ile değiştirilebilir.

| Tablo | İçerik |
| --- | --- |
| `customers` | Müşteri kimliği, isim, telefon, doğum tarihi, ilçe, adres tipi; başarısız doğrulama sayısı ve iletişim engelleri |
| `slots` | İlçe, teslimat tarihi, başlangıç/bitiş saati ve kapasite |
| `calls` | Müşteri, doğrulama, görüşme içi deneme sayısı, muhatap sonucu, durum ve oluşturulma zamanı |
| `bookings` | Müşteri başına tek rezervasyon, yer ve kaynak görüşme |
| `callback_requests` | Müşteri, kaynak görüşme, tercih zamanı, durum ve oluşturulma zamanı |

Müşteri alanları:

- `verification_failures`: Müşteri bazında kalıcı başarısız doğrulama sayısı; iki olduğunda kilit.
- `do_not_call`, `do_not_call_at`: Açık tekrar aranmama tercihi ve zamanı.
- `contact_review_status`: `clear` veya yanlış kayıt nedeniyle `pending`.
- `contact_issue_at`, `contact_issue_call_id`: Yanlış kayıt bildiriminin zamanı ve kaynak görüşmesi.

`calls.recipient_status`: `unknown`, `self`, `other_person`, `incorrect_details`.

| `calls.status` | Anlamı |
| --- | --- |
| `started` | Görüşme kaydı oluşturuldu |
| `booked` | Rezervasyon kaydedildi |
| `verification_failed` | Doğrulama sınırı doldu |
| `other_person` | Telefonu başka kişi açtı |
| `incorrect_details` | Yanlış numara veya hatalı kayıt bildirildi |
| `callback_requested` | Geri aranma talebi alındı |
| `do_not_call` | Aktif/bekleyen görüşme aranmama talebiyle kapandı |
| `declined` | Görüşme/talep reddedildi |
| `no_availability` | Uygun kurye yeri yok |
| `needs_support` | Destek gerekli |
| `existing_booking_confirmed` | Mevcut plan teyit edildi |

Geri aranma durumları `pending`, `completed`, `cancelled` değerleridir. Rezervasyon ayrı tabloda tutulur; ancak görüşmenin bağlantı yaşam döngüsü ve iş sonucu henüz ayrı durum alanlarına bölünmemiştir. Örneğin rezervasyon sonrası bağlantı kopmasını ayrıca kaydetme henüz yoktur. `do_not_call` müşteri alanı asıl iletişim engelidir; daha önce `booked` olmuş görüşmenin bu nedenle silinmesi veya durumunun ezilmesi gerekmez.

`store.initialize()` tabloları ve eksik kolonları ekler. Eski deneme kayıtlarından başarısızlık sayacı, eski `incorrect_details` sonuçlarından inceleme etiketi bir kez aktarılır. Migration kontrolleri API ve worker eşzamanlı başlarken işlem kilidi altında yapılır. Uygulama başlarken ve yeni agent işi başlarken şema kontrol edilir.

Rezervasyonlar, denemeler ve iletişim engelleri yeniden başlatmada korunur. Demo tekrarında bu kayıtların sıfırlanması gerekiyorsa mevcut dosyayı silmek yerine ayrı bir `DATABASE_PATH` ile yeni veri seti kullanmak mümkündür.

## Agent araçları ve API

| Araç | Görevi |
| --- | --- |
| `confirm_recipient` | Muhatap beyanını kaydetmek; yanlış kayıt bildirildiyse müşteri engeli oluşturmak |
| `verify_identity` | Doğum tarihini doğrulamak; başarıda mevcut rezervasyonu döndürmek |
| `get_existing_booking` | Doğrulanmış müşterinin mevcut rezervasyonunu getirmek |
| `get_available_slots` | Doğrulanmış müşterinin ilçesindeki kalan yerleri getirmek |
| `reserve_delivery` | Onay alanı, ilçe, kapasite ve tek rezervasyon kurallarıyla kayıt oluşturmak |
| `request_callback` | Açık onayla geri aranma talebi oluşturmak |
| `opt_out_calls` | Kalıcı aranmama tercihini ve bekleyen taleplerin iptalini kaydetmek |
| `finish_call` | Ret, uygun yer yok, destek veya mevcut plan teyidi sonucunu kaydetmek |

FastAPI uçları:

- `GET /health`: Servis ayakta kontrolü; sağlayıcıların veya worker'ın hazır olduğunu kanıtlamaz.
- `GET /dashboard`: Müşteriler, yerler, son 20 görüşme ve geri aranma talepleri.
- `POST /sessions`: Demo müşteri seçimiyle görüşme, LiveKit token ve agent dispatch oluşturma.
- `POST /callbacks/{callback_id}`: Geri aranma talebini `completed` veya `cancelled` yapma.

Health dışındaki uçlar `X-API-Key` ister. Next.js proxy yalnız izin verilen yolları iletir; değişiklik isteklerinde aynı origin kontrolü yapar. Servis anahtarı operatör girişi değildir; panel localhost demosu içindir. `DEMO_MODE=false` tarayıcıdan müşteri seçerek görüşme açmayı kapatır.

## Kurulum ve çalıştırma

Node.js 22+, Python 3.11+ ve `uv` gereklidir. LiveKit, ElevenLabs ve Gemini erişimi gerekir.

İlk kurulumda aşağıdaki örnek dosyaları kopyala; mevcut yerel ayarların varsa üzerlerine yazma:

```sh
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```

| Değişken | Yer / amaç |
| --- | --- |
| `BACKEND_API_KEY` | Backend ve frontend'de aynı servis anahtarı |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Backend; aynı LiveKit projesi |
| `LIVEKIT_AGENT_NAME` | Backend; varsayılan `freya-delivery` |
| `ELEVEN_API_KEY`, `ELEVEN_VOICE_ID` | Backend; konuşma tanıma ve seslendirme erişimi |
| `GOOGLE_API_KEY`, `GOOGLE_MODEL` | Backend; Gemini erişimi ve model seçimi |
| `ELEVEN_STT_MODEL`, `ELEVEN_TTS_MODEL` | Backend; isteğe bağlı model seçimi |
| `DEMO_WEEK_START`, `DEMO_MODE` | Backend; demo haftası ve müşteri seçimi |
| `DATABASE_PATH` | Backend; isteğe bağlı SQLite dosya yolu |
| `BACKEND_URL` | Frontend; varsayılan `http://127.0.0.1:8000` |

Anahtarlar yalnız yerel env dosyalarında tutulmalıdır. Frontend'e yalnız backend adresi ve sunucular arası anahtar konur; sağlayıcı anahtarları tarayıcıya gönderilmez. `NEXT_PUBLIC_` değişkenleri kullanılmaz.

Bağımlılıklar ve VAD dosyaları:

```sh
cd backend
uv sync
uv run python -m app.agent download-files
```

```sh
cd frontend
npm ci
```

Proje kökünden API ve worker'ı birlikte başlat:

```sh
bash scripts/start-backend.sh
```

Ayrı terminalde paneli başlat:

```sh
cd frontend
npm run dev
```

`http://localhost:3000` adresini aç, müşteri seç, görüşmeyi başlat ve mikrofon izni ver. Agent kaydında `registered worker` görünmesini bekle. Müşteri engelliyse düğme kapalıdır; açıklama ve etiket panelde görünür.

Başlatma betiğinde Ctrl+C API ve worker'ı birlikte kapatır. Arka plan seçeneği `bash scripts/start-backend.sh --background` şeklindedir. API kaydı `.local/logs/api.log`, agent kaydı `.local/logs/agent.log`, arka plan supervisor kaydı `.local/logs/supervisor.log` içindedir. Kod/şema değişikliklerinden sonra API ve worker birlikte yeniden başlatılmalıdır; `dev` komutunun otomatik yenilemesine güvenilmemelidir.

Betik yerine ayrı terminaller de kullanılabilir:

```sh
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

```sh
cd backend
uv run python -m app.agent dev
```

## Doğrulama ve demo senaryoları

```sh
cd backend
uv run python -m unittest discover -s tests -v
```

```sh
cd frontend
npm run typecheck
npm run build
```

Son kontrol: 16 Kasım 2026'da backend'in 44 otomatik testi, frontend tür kontrolü ve üretim derlemesi başarılıdır. Önceki kurulum sırasında yaşanan bağımlılık/DNS sorunu güncel testlerin çalışmasına engel değildir.

Testler; kapasite yarışı, idempotency, müşteri bazında iki deneme, muhatap teyidi, mevcut rezervasyon gizliliği, kalıcı aranmama tercihi, yanlış kayıt engeli, geri aranma, eski şema geçişleri ve agent'in bazı araç/veda/hata akışlarını kapsar. Sağlayıcı çağrılarının taklit edildiği testler gerçek sesli görüşme kanıtı değildir.

Manuel demo kontrol listesi:

1. Doğru müşteri ve doğum tarihiyle saat seç; kimlikle şahsen teslim koşulunu ve açık onayı doğrula. Tek rezervasyon oluşmalı ve veda bitince oda kapanmalı.
2. Aynı müşteriyle yeniden görüş; doğrulamadan önce rezervasyon bilgisi açılmamalı, sonrasında mevcut plan getirilmeli.
3. Bir yanlış tarih söyle, yeni görüşmede ikinci yanlış tarihi söyle; sonraki görüşme engellenmeli. Ayrı müşteride ilk yanlışın ardından doğru tarih başarıyla ilerlemeli.
4. Telefonu yakınının açtığını söyle; bilgi paylaşılmadan kapanmalı, müşteri kalıcı yanlış numara engeli almamalı.
5. Yanlış numara/kayıt bildir; görüşme sonucu ve müşteri inceleme etiketi görünmeli, yeni görüşme düğmesi kapanmalı.
6. Gelecekte bir zaman için geri aranma iste; panelde tek talep görünmeli, kapasite değişmemeli. Geçmiş veya belirsiz zaman kesinleşmemeli.
7. Bekleyen geri araması olan müşteri tekrar aranmak istemediğini söylesin; talep iptal edilmeli, iletişim engeli kalıcı olmalı, varsa teslimat korunmalı.
8. Kadıköy'deki iki yeri doldur; üçüncü müşteriye olmayan bir yer vaat edilmemeli.
9. Mikrofon izni, araya girme, provider hatası ve bağlantı kopmasını dene; yanlış başarı mesajı verilmediğini kontrol et. Kopmanın veritabanı yaşam döngüsü kaydı halen eksiktir.

Canlı Türkçe ses, tarih anlama, araya girme, gecikme ve tüm senaryoların uçtan uca başarı oranları için bu README kapsamında ölçülmüş sonuç sunulmamaktadır.

## Eksik ve kısmen uygulanmış senaryolar

- Görüşmenin bağlantı durumunu rezervasyon/iş sonucundan ayırmak; kopma, süre, bitiş zamanı ve teknik hata nedenini kalıcı kaydetmek.
- Geçmiş teslimat pencerelerini engellemek; son kabul saati ve aynı gün rezervasyon kuralı koymak. Geri aranma zamanının gelecekte olması kontrolü vardır; teslimat tarihleri için henüz yoktur.
- Müşterinin pencerenin tamamında müsaitliğini açıkça netleştirmek; kesin kurye saati veya ön arama vaat etmeme kuralını güçlendirmek.
- Açık onayı seçilen pencereye ve konuşma kanıtına bağlamak. Mevcut `confirmed` alanı bağımsız onay kanıtı değildir.
- Rezervasyon değiştirme/iptal; yeni yer kesinleşmeden eski yeri kaybetmeme.
- Yanlış müşteri kaydını düzeltme ve inceleme engelini kaldırma ekranı; doğrulama kilidini veya iletişim tercihini yetkili işlemle yönetme.
- Kapasite yetersizliğinde açık arama/öncelik politikası, bekleme listesi ve yeni yer bildirimi.
- “Kapasite yok” ile “mevcut saatler müşteriye uymuyor” için ayrı sonuçlar.
- Gerçek telefon araması, SIP/telefon sağlayıcısı ve geri arama zamanlayıcısı.
- İnsan destek kuyruğu ve gerçek aktarım; mevcut `needs_support` yalnız sonuç kaydıdır.
- Tüm canlı sesli senaryoların ölçümü ve tekrar üretilebilir değerlendirmesi.

Bilinen konuşma tutarsızlığı: Sabit `other_person` kapanış yanıtı da yanlış numara ifadesi kullanabiliyor. Veritabanında bu sonuç kalıcı yanlış numara engeli oluşturmuyor; konuşma metni ayrımı ayrıca düzeltilmeli. Prompt'taki kuralların tek başına bütün sabit yanıt yollarını değiştirmediği dikkate alınmalıdır.

Gerçek banka kullanımı öncesinde ayrıca operatör girişi, rol bazlı yetki, güçlü müşteri doğrulaması, rate limit, denetim izi, veri saklama/silme kuralları, izleme ve merkezi veritabanı/migration yönetimi gerekir. Bunlar mevcut demo kapsamında tamamlanmış değildir.

## Kod haritası ve görev teslimi

```text
backend/app/main.py               FastAPI, servis anahtarı, LiveKit dispatch
backend/app/store.py              SQLite, seed, migration ve iş kuralları
backend/app/agent.py              Agent, araçlar, konuşma ve kapanış yönetimi
backend/app/gemini_completion.py  Gemini taşıması ve araç yanıtları
backend/app/birth_dates.py        Belirli tarih ifadelerini ayrıştırma
backend/app/tool_replies.py       Sabit araç sonucu seslendirmeleri
backend/app/prompts/delivery.md   Türkçe konuşma akışı ve sınırlar
backend/tests/                   İş kuralı, migration ve agent testleri
frontend/app/                    Panel ve sunucu API proxy
frontend/components/             Ses kontrolleri ve görüşme dökümü
scripts/start-backend.sh          API/worker başlatma ve kayıtlar
docs/                            Case analizi ve geliştirme geçmişi
```

Görev teslimi için iki saatlik geliştirme ekran kaydı, en fazla on dakikalık ekran/ses anlatımı, kod bağlantısı ve AI sohbet kayıtları istenir. Plan değişikliklerinin zamanları anlatılmalıdır. Video ve kayıtların hazırlanıp gönderilmesi uygulamanın bir özelliği değildir; depodaki kod bunların tamamlandığını kanıtlamaz.

[Case analizi](docs/case-analysis.md) ve [geliştirme notları](docs/development-notes.md) ek bağlam sağlar; geliştirme notları geçmiş aşamalardaki sonuçları da içerir. Güncel davranış için bu README ve kaynak kod esas alınmalıdır.
