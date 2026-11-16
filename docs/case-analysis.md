# Case analizi ve kararlar

Kaynak: Kullanıcının sağladığı Freya-FDE-On-Test.pdf, 3 sayfa, sürüm 2026-11-07. Tüm sayfalar metin ve render üzerinden incelendi.

## Beklenen problem

Yeni banka salı günü adreste bulunamayan sekiz kart sahibini arayıp bu hafta yeniden kurye teslimatı planlamak istiyor. Bankanın sistemi yok; müşteri ve müsaitlik verilerini tutan, asistanın konuşma sırasında çağırdığı servis gerekiyor. Arayüz zorunlu değil; kullanıcı Next.js istediği için basit operasyon/demo paneli eklendi.

| ID | Müşteri | Telefon | Doğum tarihi | İlçe | Adres tipi |
| --- | --- | --- | --- | --- | --- |
| c1 | Ayşe Kaya | 0532 000 00 01 | 14.03.1988 | Kadıköy | Ev |
| c2 | Mehmet Demir | 0532 000 00 02 | 02.11.1975 | Kadıköy | İş yeri |
| c3 | Zeynep Arslan | 0532 000 00 03 | 27.06.1993 | Kadıköy | Ev |
| c4 | Can Yıldız | 0532 000 00 04 | 09.01.1981 | Ataşehir | Ev |
| c5 | Elif Şahin | 0532 000 00 05 | 30.08.1990 | Ataşehir | İş yeri |
| c6 | Burak Çelik | 0532 000 00 06 | 18.12.1969 | Şişli | Ev |
| c7 | Selin Aydın | 0532 000 00 07 | 05.04.1999 | Şişli | Ev |
| c8 | Ali Öztürk | 0532 000 00 08 | 21.07.1984 | Beşiktaş | İş yeri |

| İlçe | Gün | Saat | Kapasite |
| --- | --- | --- | --- |
| Kadıköy | Perşembe | 09:00–13:00 | 1 |
| Kadıköy | Cuma | 14:00–18:00 | 1 |
| Ataşehir | Perşembe | 14:00–18:00 | 2 |
| Şişli | Cuma | 09:00–13:00 | 2 |
| Beşiktaş | Perşembe | 09:00–13:00 | 1 |

Kart yalnız kart sahibine, kimliği görülerek teslim edilir. Toplam 7 yer vardır. Kadıköy'de 3 müşteri ve 2 yer olduğundan herkesin planlanması başarı ölçütü olamaz; bir müşteride kapasite yok sonucu beklenir.

## Açık varsayımlar

- PDF kesin takvim tarihi vermiyor. Senaryo haftası 16 Kasım 2026 Pazartesiye sabitlendi; teslimatlar 19/20 Kasım. Böylece demo, çalıştırıldığı gün nedeniyle bozulmaz. Bu bir simülasyondur: gerçek geçmiş tarih engeli henüz yok.
- `DEMO_WEEK_START` pazartesi olmalı. Seed tekrarında veri ezilmez. Hafta değiştirmek için yeni `DATABASE_PATH` kullan; mevcut rezervasyonları sessizce başka tarihe taşımıyoruz.
- Gerçek sokak adresi verilmediğinden yalnız ilçe ve adres tipi tutulur. Adres değişikliği alınmaz.
- Demo kimlik kontrolü doğum tarihi ve 3 deneme. Bu, gerçek banka için yeterli değildir. Deneme sınırı görüşme bazlıdır; yeni görüşmeyle sıfırlanır.
- Tek müşteri tek rezervasyon. Mevcut rezervasyonu değiştirme/iptal ilk sürüm dışında.
- Yer, konuşma sırasında tutulmaz; yalnız açık onayla rezervasyon anında tüketilir. Yarış kaybedilirse tekrar müsaitlik sorulur.
- Uygun saat yok/ret/destek gerekli sonuçları kaydedilir. İnsan destek kuyruğu veya gerçek aktarım henüz yok.
- Tarayıcı demo görüşmesi outbound telefon aramasının ilk entegrasyon adımıdır; telefon araması tamamlandı sayılmaz.

## Başarı ölçümü

İş kuralları için deterministik testler: seed doğruluğu, doğrulamasız veri erişiminin engellenmesi, 3 yanlış deneme, doğru ilçe, açık onay alanı, tek rezervasyon, idempotency, kapanan görüşmenin işlem yapamaması, eşzamanlı son yer ve kapasite tükenmesi. Canlı model değerlendirmesi ayrı yapılmalı: Türkçe tarih anlama, araç sırası, onay isteme, başarısız araç sonrası dürüst yanıt, araya girme, yanıt gecikmesi ve görüşme tamamlama oranı.

## PDF teslim koşulları

İki saatlik geliştirme boyunca baştan sona ekran kaydı, ses isteğe bağlı. İki saat dolunca durma. Plan değişikliklerinin zamanını kaydetme. En fazla 10 dakikalık ekran ve sesli anlatım: kurulanlar, kapsam dışı seçimler, kod, sesli demo, ölçüm sonuçları, gerçek banka öncesi gerekliler ve yön değişikliği zamanları. Tek mesajla ekran kaydı, anlatım videosu, kod bağlantısı ve AI sohbet kayıtlarını gönderme. Bu kayıtları ve gönderimi kullanıcı yapacak; sistem ekran kaydı başlatmadı.
