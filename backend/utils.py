import re


def clean_float(value, decimals=2, default=0.0):
    """Nettoie et convertit n'importe quelle entrée numérique ou texte en float."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return round(float(value), decimals)
    if not isinstance(value, str):
        try:
            return round(float(value), decimals)
        except Exception:
            return default
            
    s = value.strip()
    is_percent = s.endswith('%')
    if is_percent:
        s = s[:-1].strip()
        
    s = re.sub(r'[^0-9.,\-eE]', '', s)
    if ',' in s and '.' in s:
        s = s.replace(',', '')
    elif ',' in s and '.' not in s:
        s = s.replace(',', '') if s.count(',') > 1 else s.replace(',', '.')
        
    try:
        num = float(s)
        if is_percent:
            num /= 100.0
        return round(num, decimals)
    except Exception:
        return default

def to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default