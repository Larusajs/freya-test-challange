"""Strict, unambiguous dates for the identity stage; never infer missing years."""
import re
from datetime import date

MONTHS = {name:index+1 for index,name in enumerate(
    ('ocak','şubat','mart','nisan','mayıs','haziran','temmuz','ağustos','eylül','ekim','kasım','aralık'))}


def parse_birth_date(text):
    text = text.lower().strip().rstrip('.!? ')
    text = re.sub(r'^(?:benim\s+)?doğum\s+tarihim(?:\s+ise)?\s*[:,-]?\s*', '', text)
    day = month = year = None
    if match := re.fullmatch(r'(\d{1,2})[./-](\d{1,2})[./-](\d{4})',text):
        day,month,year = map(int, match.groups())
    elif match := re.fullmatch(r'(\d{1,2})\s+('+'|'.join(MONTHS)+r')\s+(\d{4})',text):
        day,month,year = int(match[1]),MONTHS[match[2]],int(match[3])
    elif match := re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})',text):
        year,month,day = map(int,match.groups())
    if day is None:
        return None
    try:
        return date(year,month,day).isoformat()
    except ValueError:
        return None
