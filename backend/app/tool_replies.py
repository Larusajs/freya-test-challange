"""Speak authoritative tool results without a second model round trip."""
from datetime import date

MONTHS = ('Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran',
          'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık')
DAYS = ('Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar')


def delivery_time(slot):
    day = date.fromisoformat(slot['delivery_date'])
    return (f"{day.day} {MONTHS[day.month-1]} {day.year} {DAYS[day.weekday()]}, "
            f"saat {slot['start']} ile {slot['end']} arası")


def slots_reply(slots):
    if not slots:
        return ('Bu hafta ilçeniz için uygun kurye yeri kalmamış. '
                'Yeni teslimat seçenekleri için bankanın resmi kanallarına başvurabilirsiniz.')
    options = '; veya '.join(delivery_time(slot) for slot in slots)
    return f"Uygun teslimat zamanları: {options}. Hangisi sizin için uygun?"


def tool_reply(name, result):
    if not isinstance(result, dict) or result.get('error'):
        return None
    if name == 'opt_out_calls' and result.get('do_not_call'):
        return ('Tekrar aranmama tercihinizi kaydettim. Bekleyen geri aranma talepleriniz iptal edildi. '
                'Mevcut teslimat rezervasyonunuz varsa korunur. İyi günler dilerim.')
    if name == 'confirm_recipient' and result.get('status') in ('other_person', 'incorrect_details'):
        return 'Rahatsız ettiğim için kusura bakmayın. Yanlış numara bilgisini sisteme kaydediyorum. İyi günler dilerim.'
    if name == 'confirm_recipient' and result.get('recipient_status') == 'self':
        return ('Teşekkür ederim. Görüşmek için müsaitseniz kimliğinizi doğrulamak üzere '
                'doğum tarihinizi gün, ay ve yıl olarak öğrenebilir miyim?')
    if name == 'verify_identity':
        if result.get('verified') is False:
            if result.get('remaining_attempts', 0) > 0:
                return ('Verdiğiniz tarih kayıtla eşleşmedi. '
                        'Doğum tarihinizi gün, ay ve yıl olarak tekrar söyler misiniz?')
            return ('Kimliğinizi doğrulayamadım. Güvenliğiniz için bu görüşmede ilerleyemiyorum. '
                    'Lütfen bankanın resmi kanallarına başvurun.')
        if result.get('verified') is True:
            if booking := result.get('booking'):
                return (f"Kimliğiniz doğrulandı. Mevcut teslimatınız {delivery_time(booking)}. "
                        'Bu teslimat planını korumak ister misiniz?')
            if 'slots' in result:
                return ('Kimliğiniz doğrulandı. Teslimatınızı yeniden planlayabiliriz. '
                        + slots_reply(result['slots']))
    if name == 'get_available_slots' and 'slots' in result:
        return slots_reply(result['slots'])
    if name == 'reserve_delivery' and result.get('booking_id') and result.get('delivery_date'):
        return (f"Teslimatınız {delivery_time(result)} için planlandı. "
                'Kartınızı yalnızca siz, kimliğinizi göstererek teslim alabilirsiniz. Teşekkür ederim, iyi günler dilerim.')
    if name == 'finish_call' and result.get('status') == 'existing_booking_confirmed':
        return 'Mevcut teslimat planınız onaylandı. Teşekkür ederim, iyi günler dilerim.'
    if name == 'request_callback' and result.get('callback_id') and result.get('status') == 'pending':
        return 'Geri aranma talebinizi kaydettim. Anlayışınız için teşekkür ederim, iyi günler dilerim.'
    return None
