"""Offline verification; only the server possesses the signing private key."""
import base64
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path

from cryptography.hazmat.primitives.serialization import load_pem_public_key

FREE_LIMIT = 10
API = 'https://savetory.ru/desktop/'


def safe_checkout(url):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and not parsed.username and not parsed.password
                and parsed.port in (None, 443)
                and any(parsed.hostname == host or (parsed.hostname or '').endswith('.' + host)
                        for host in ('yookassa.ru', 'yoomoney.ru')))
    except (ValueError, TypeError):
        return False


def verify(document, public_key_path):
    try:
        payload = base64.b64decode(document['payload'], validate=True)
        signature = base64.b64decode(document['signature'], validate=True)
        load_pem_public_key(Path(public_key_path).read_bytes()).verify(signature, payload)
        data = json.loads(payload)
        return (data.get('product') == 'sklad-desktop' and data.get('version') == 1
                and data.get('perpetual') is True and bool(data.get('license_id')))
    except Exception:
        return False


def is_licensed(data_dir, assets):
    try:
        return verify(json.loads((Path(data_dir) / 'license.json').read_text('utf-8')),
                      Path(assets) / 'license-public.pem')
    except (OSError, ValueError):
        return False


def save_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def activate(document, data_dir, assets):
    if not verify(document, Path(assets) / 'license-public.pem'):
        raise ValueError('Лицензия недействительна или выпущена для другого приложения.')
    save_json(Path(data_dir) / 'license.json', document)


def request(endpoint, document):
    req = urllib.request.Request(API + endpoint + '/',
                                 data=json.dumps(document).encode(),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            result = json.loads(response.read(65536))
    except urllib.error.HTTPError as exc:
        try:
            error = json.loads(exc.read(65536)).get('error')
        except (ValueError, AttributeError):
            error = None
        raise ValueError(error or 'Сервис покупки пока недоступен. Попробуйте позже.') from None
    except (OSError, ValueError):
        raise ValueError('Нет связи с сервером. Данные сохранены; повторите проверку позже.') from None
    if not isinstance(result, dict):
        raise ValueError('Некорректный ответ сервера.')
    return result
