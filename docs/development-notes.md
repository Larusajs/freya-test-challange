# Geliştirme notları

## İlk temel

- PDF'nin üç sayfası okunup görsel olarak incelendi; tablolar seed verisine aktarıldı.
- Next.js + FastAPI + LiveKit worker + SQLite seçildi.
- İlk entegrasyon tarayıcı sesidir; gerçek outbound arama sonraki adım.
- Paket kurulumu sandbox DNS kısıtı nedeniyle npm ve PyPI'da başarısız oldu. Bu nedenle frontend derlemesi ve gerçek SDK/model çağrıları doğrulanmadı. İş kuralı testleri ağ gerektirmeden sistem Python'uyla çalıştırılabilir.
- Gerçek ekran kaydı süreleri bilinmediğinden yön değişikliği zamanları üretilmedi. Kullanıcı kayıttaki zamanları eklemeli.

## Sonraki adımlar

1. Env alanlarını doldur, bağımlılıkları kur, typecheck/build ve ilk canlı Türkçe görüşmeyi tamamla.
2. Ses seçimi, STT tarih doğruluğu ve Gemini araç çağrıları için aynı senaryolarda değerlendirme yap. TTFT, STT final ve TTS ilk ses gecikmelerini ölç.
3. Görüşme yaşam döngüsünü genişlet: agent gelmeme/timeout, müşteri kopması, yarım kalan görüşme, sonuç ve süre kaydı; kişisel veriyi ayıklayan metrikler.
4. LiveKit SIP outbound trunk ve telefon sağlayıcısı ekle. Gerçek aramadan önce sağlayıcı hesabı, trunk kimliği, yetkili numara ve arama yetkisi gerekli; mevcut kod telefon numaralarını aramaz.
5. Üretim için operatör girişi, rol bazlı yetki, müşteri bazlı güçlü doğrulama/deneme sınırı, onay kanıtı, PostgreSQL, migration, denetim izi, veri saklama ve silme politikası, izleme ve insan destek entegrasyonu tasarla.

## Doğrulama

`cd backend && python3 -m unittest discover -s tests -v`: 9 test başarılı.

Python kaynak dosyaları `ast.parse` ile sözdizimi kontrolünden geçti. Next.js typecheck/build, LiveKit worker import/startup ve sesli uçtan uca testler bağımlılıklar ve gerçek API anahtarları olmadığı için çalıştırılmadı.

## Gemini güncellemesi

Kullanıcı tercihiyle LLM hattı yalnız Gemini kullanacak şekilde sadeleştirildi. OpenAI plugin seçimi ve uygulama ayarları kaldırıldı; özel env dosyasındaki mevcut anahtarlar korunuyor. Gerekli env alanlarının doluluğu ve frontend/backend servis anahtarı eşleşmesi kontrol edildi; anahtarların sağlayıcı tarafından geçerliliği henüz doğrulanmadı. 9 iş kuralı testi yeniden geçti. npm/PyPI kurulumu tekrar denendi; DNS erişim hatası devam ediyor.

## Geri aranma talebi

- `callback_requests` tablosu müşteri, kaynak görüşme, UTC tercih zamanı ve pending/completed/cancelled durumunu saklar. `initialize()` eski veriyi silmeden tabloyu ve indeksini ekler.
- Aynı müşteri için tek bekleyen talep; aynı görüşmeden aynı zamanla tekrar çağrı idempotent. Kaynak görüşme `callback_requested` durumuna geçer ve teslimat işlemlerine kapanır.
- Talep kimlik doğrulamasından önce alınabilir; yalnız kayıtlı numaraya geri dönüş içindir, teslimat verisi açılmaz. Kesin, gelecekte ve saat dilimli tarih/saat ile açık onay gerekir. Operatör panelinde saat İstanbul olarak gösterilir.
- Agent aracı ve prompt güncellendi. Dashboard talepleri getirir; operatör tamamlandı/iptal işlemlerini kimlik korumalı backend endpoint'i üzerinden yapar. Gerçek telefon araması veya zamanlayıcı eklenmedi; saat bir tercih olup kesin arama garantisi değildir.
- Doğum tarihi doğrulamasının mevcut görüşme bazlı deneme sınırı bu değişiklikte değiştirilmedi.
- 14 iş kuralı testi başarılı; frontend typecheck başarılı. Canlı sesli geri aranma senaryosu ayrıca denenmeli.

## Sesli açılış ve Gemini düzeltmesi

Canlı worker kaydında Gemini'nin araç çağrılarını v1 endpoint'inde 400 ile reddettiği görüldü. Gemini Developer API istemcisi açıkça v1beta ve vertexai=False ile yapılandırıldı. Agent müşterinin odaya katılmasını bekliyor, on_enter üzerinden müşteri adı ve demo unvanıyla sabit açılışı ElevenLabs TTS ile yapıyor. Açılış LLM'e bağımlı değil; müşteri yanıtından sonra Gemini devam ediyor. İlk açılış bölünmez; sonraki konuşma normal söz kesme davranışını koruyor.

Env'deki ElevenLabs ses kimliği voice_id_does_not_exist döndürdü. Hesabın ses listesinde erişilebilir Sarah seçildi; eski kimlik özel env'de yorum olarak korundu.

Canlı doğrulama: API üzerinden oluşturulan oturuma Python RTC test katılımcısı bağlandı. İlk açılış ve Gemini yanıtında sessizlikten farklı PCM ses örnekleri alındı. Katılımcının metin mesajıyla verdiği doğum tarihi Gemini verify_identity aracını çağırdı ve SQLite'ta doğrulandı. Bu test tarayıcı mikrofon girişini simüle etmez; oda bağlantısı, proaktif TTS açılışı, Gemini yanıtı ve gerçek araç çağrısını doğrular. 14 deterministik iş kuralı testi tekrar başarılı. API ve worker çalışma oturumunda açık bırakıldı.

## Doğru doğum tarihindeki araç hatası

Kullanıcı görüşmesinde STT `14.03.1988`, Gemini araç girdisi `1988-03-14` olarak doğruydu. Hata store.verify içindeki recipient_status erişiminde `IndexError: No item with that key` idi. Çalışan süreçler ile güncellenen kaynak/şema aynı sürümde değildi; aktif SDK dev komutu otomatik yeniden yüklemiyor. API ve worker güncel kodla birlikte yeniden başlatıldı. Artık her job başlangıcında additive initialize çalışıyor; eşzamanlı migration kontrolü BEGIN IMMEDIATE ile korunuyor. Eski şemaya eşzamanlı iki initialize sonrası muhatap teyidi ve doğru doğum tarihiyle doğrulama regresyon testi eklendi. Toplam 20 iş kuralı testi başarılı.

Kontrol sırasında API ve ana worker ayaktaydı; görüşme alt sürecinin kapanması backend'in tümünün çökmesiyle aynı şey değil. Terminalden bağımsız start-backend --background modu eklendi ve supervisor bu modda başlatıldı.

Düzeltme sonrası canlı RTC testinde yeni worker confirm_recipient(self) ve verify_identity(1988-03-14) araçlarını sırasıyla çağırdı; görüşmenin SQLite verified alanı true oldu. Duyulabilir açılış ve Gemini yanıtı alındı. Aynı isimle ikinci bir sahipsiz worker tespit edilip kapatıldı; tek supervisor altında API ve worker bırakıldı.

## Yanıttan sonra düşünüyor durumunda kalma

Son kullanıcı görüşmesinde STT “Evet, müsaitim. Sizi dinliyorum.” ifadesini doğru iletti. Gemini 2.5 Flash 429 RESOURCE_EXHAUSTED döndürdü: FreeTier günlük istek limiti 20, dakika limiti 5. Yeniden denemeler gecikmeye ve sessizliğe neden oldu. Kullanıcı ücretli kotasını kontrol edeceğini belirtti; model değiştirilmedi.

LLM bağlantı tekrarları kapatıldı ve yanıt zaman aşımı 12 saniyeye indirildi. llm_node APIError durumunda modeli yeniden çağırmadan ElevenLabs'e sabit hata açıklaması iletiyor ve freya.error güvenilir veri paketiyle panelde hata gösteriyor. Aynı görüşmede 429 sonrası yeni konuşma tekrar Gemini isteği oluşturmuyor. Normal yanıt akışı ve kota hatası regresyonları dahil 22 test başarılı; frontend typecheck başarılı. Servisler güncel kodla arka planda yeniden başlatıldı. Kota/faturalandırma düzelmeden mevcut modelde normal görüşmenin devam edeceği doğrulanamaz.

## Yeni API anahtarında model erişimi

Yeni anahtarla gemini-2.5-flash çağrısı 404 döndü: sağlayıcı bu modeli yeni kullanıcılara kapattığını ve gemini-3.8-flash önerdiğini bildirdi. 3.8 Flash denemeleri 503 yüksek talep hatası verdi. Erişilebilir gemini-3.1-flash-lite için basit generateContent isteği 200 ve Merhaba yanıtı aldı; ancak LiveKit streaming + function call testleri aynı anda 503 döndürdü. Konfigürasyon erişilebilir 3.1 Flash Lite olarak güncellendi; düşünme seviyesi low. Sağlayıcı yoğunluğu nedeniyle agent araç konuşmasının düzeldiği henüz doğrulanmadı. Panelde 404/403/400/503 hataları ayrı açıklanıyor.

## Gemini streaming zaman aşımı için taşıma düzeltmesi

Son kullanıcı kaydı 504 idi. Aynı anahtar ve aynı modelle SSE streamGenerateContent 503/504 dönerken normal generateContent, araç çağrısıyla 200 ve yaklaşık 2,45 saniyede yanıt verdi. Bu fark doğrudan test edildi; genel model erişimi sorunu varsayımı bu vakayı tek başına açıklamıyordu.

Agent llm_node artık generateContent sonucunu LiveKit ChatChunk/FunctionToolCall yapısına dönüştürüyor. Araç yürütme LiveKit'te, ses üretimi ElevenLabs'te devam ediyor. Gemini 3 thought signature değerleri araç turları arasında korunuyor; düşünce metni seslendirilmiyor. Parametresiz araçlarda null şema REST payload'ından çıkarılıyor. API anahtarı yalnız header ile iletiliyor. 15 saniyelik istek zaman aşımı var; kota hatası aynı görüşmede tekrar istek oluşturmuyor.

Yeni taşıma ile gerçek Gemini müşteri teyidi çağrısı ve araç sonucundan sonra konuşmanın devamı doğrulandı. 24 test başarılı.

Canlı RTC oturumunda açılış sesi, kullanıcı teyidi sonrası doğum tarihi sorusu ve verify_identity aracı başarılı oldu; SQLite verified alanı true olarak doğrulandı. Test katılımcısına 4229 ses çerçevesi ulaştı. API ve worker güncel kodla arka planda bırakıldı.

## Doğrulama sonrası yanıtın tamamlanması

Son kullanıcı görüşmesinde doğru tarih verify_identity aracına ulaştı; SQL işlemi yaklaşık 8 ms'de tamamlandı ve verified=1 oldu. Hata sonraki Gemini generateContent isteğinin 15 saniyelik APITimeoutError sonucuydu. Önceki canlı test yalnız verified bayrağına kadar kontrol ettiği için bu devam hatasını kapsamıyordu.

Artık müşteri teyidi, doğum tarihi sonucu, kurye yerleri ve rezervasyon başarı yanıtları güvenilir araç çıktısından doğrudan üretiliyor. Başarılı doğrulama sonucuna ilçe bazlı gerçek SQL slotları ekleniyor; takip eden model turu aynı slot kimliklerini görebiliyor. Böylece doğru tarih sonucu ve teslimat seçeneklerini seslendirmek için ikinci Gemini isteği gerekmiyor. Yanlış tarihler yine reddediliyor. İş aracı süreleri ve verified sonucu kişisel veri olmadan loglanıyor. Doğru/yanlış tarih ve modelsiz sonuç devamı testleri dahil 26 test başarılı.

Genişletilmiş testte Gemini'nin bazen verify_identity çağrısından önce de timeout verdiği görüldü. Kimlik aşaması daha açık hale getirildi: yalnız bilinen kısa, açık müşteri teyitleri sunucuda karşılanıyor; diğer ifadeler hâlâ modele gidiyor. Doğum tarihi beklenirken tam gün/ay/dört haneli yıl içeren açık sayısal veya Türkçe ay adındaki tarih yerel olarak ayrıştırılıp aynı store.verify servisine veriliyor. Eksik yıl veya geçersiz tarih tahmin edilmiyor. Kimlik kuralları, deneme sayısı ve muhatap şartı aynı SQLite servisinde uygulanıyor. Doğrulanan güncel slot kimlikleri sonraki model turuna sunucu bağlamı olarak aktarılıyor.

LiveKit 1.8'in araç sonuçlarını JSON yerine str(dict) ile ilettiği kaynak kodda doğrulandı; doğrudan sonuç seslendirme bu biçimi güvenli literal parser ile de destekliyor. Regresyon testi gerçek SDK make_function_call_output işlevini kullanıyor. Gerçek geçici SQLite ile açık müşteri teyidi → doğru doğum tarihi → seçenek yanıtı, Gemini çağrısı olmadan sınandı. Toplam 28 test başarılı.

Genişletilmiş canlı RTC testinin tamamı başarılı: müşteri teyidi → doğum tarihi → SQLite doğrulaması (1,2 ms) → iki gerçek teslimat penceresinin tamamı → “Hangisi sizin için uygun?” transkripti test katılımcısına ulaştı. Test `Delivery options received after verification: OK` ile tamamlandı; yalnız verified bayrağına dayanılmadı. Bu senaryoda teyit ve açık tarih adımı Gemini isteği gerektirmedi. Slot seçimi gibi sonraki serbest konuşma adımları Gemini kullanmaya devam eder; sağlayıcı gecikmelerinin tümünün ortadan kalktığı iddia edilmiyor.

## Başarılı rezervasyondan sonra görüşmeyi bitirme

reserve_delivery başarıyla booking_id döndürdüğünde RunContext speech_handle tamamlanma callback'i kaydediliyor. Son rezervasyon özeti ve iyi günler mesajı aynı konuşma turunda seslendiriliyor; bu sırada kesme ve yeni mikrofon girişi kapatılıyor. Son ses tamamlanınca LiveKit odası silinerek tüm katılımcılar çıkarılıyor, oturum ve job kapanıyor. Böylece tool içinden kendi speech_handle'ını bekleyen bir döngü oluşmuyor. Mevcut rezervasyonun yeniden onayında da aynı kapanış uygulanıyor. Başarısız rezervasyon callback kaydetmiyor ve görüşme açık kalıyor. Son söz tamamlanmadan delete_room çalışmaması ve başarısız işlemde kapanmama regresyonlarıyla toplam 30 test başarılı.

Canlı RTC testinde c1'in mevcut rezervasyonu korunarak onaylandı. Son “iyi günler” transkripti katılımcıya ulaştıktan sonra sunucu odayı kapattı ve katılımcı otomatik disconnected durumuna geçti. Görüşme sonucu existing_booking_confirmed olarak saklandı; mevcut rezervasyon değiştirilmedi. API/worker arka planda çalışmaya devam ediyor.
