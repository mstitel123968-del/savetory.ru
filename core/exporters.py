from __future__ import annotations

import base64
import binascii
import html
import io
import re
import zipfile
from datetime import datetime
from urllib.parse import quote

from django.http import HttpResponse
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

EMPTY_VALUE = '—'


def normalize_file_status(value: str, labels: dict[str, str]) -> str:
    status = str(value or '').strip().lower()
    return status if status in labels else 'keep'


def find_rubric(state_data: dict, rubric_id: str) -> dict | None:
    rubrics = state_data.get('rubrics') if isinstance(state_data, dict) else []
    if not isinstance(rubrics, list):
        return None
    wanted = str(rubric_id or '').strip()
    for rubric in rubrics:
        if isinstance(rubric, dict) and str(rubric.get('id') or '').strip() == wanted:
            return rubric
    return None


def safe_filename(name: str, extension: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', ' ', str(name or 'rubric')).strip()
    cleaned = re.sub(r'\s+', '_', cleaned) or 'rubric'
    return f'{cleaned}_export.{extension}'


def content_disposition(filename: str) -> str:
    fallback = re.sub(r'[^A-Za-z0-9_.-]+', '_', filename) or 'export'
    encoded = quote(filename)
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


def visible_fields(rubric: dict) -> list[dict]:
    mode = rubric.get('mode') if rubric.get('mode') == 'text' else 'file'
    removed = {
        str(field_id)
        for field_id in rubric.get('removedFieldIds', [])
        if field_id is not None
    } if isinstance(rubric.get('removedFieldIds'), list) else set()
    fields = []
    for field in rubric.get('fields', []):
        if not isinstance(field, dict):
            continue
        field_id = str(field.get('id') or '').strip()
        if not field_id or field_id in removed:
            continue
        field_type = str(field.get('type') or 'text')
        if mode == 'text' and (field_id == 'photo' or field_type == 'image'):
            continue
        fields.append({
            'id': field_id,
            'label': str(field.get('label') or 'Поле'),
            'type': field_type,
        })
    return fields


def field_value(file_item: dict, field: dict):
    values = file_item.get('values') if isinstance(file_item.get('values'), dict) else {}
    return values.get(field['id'])


def text_value(value) -> str:
    if value is None:
        return EMPTY_VALUE
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or EMPTY_VALUE
    if isinstance(value, (int, float, bool)):
        return str(value)
    return str(value).strip() or EMPTY_VALUE


def image_items(value) -> list[dict]:
    source = []
    if isinstance(value, dict):
        if isinstance(value.get('items'), list):
            source = value.get('items') or []
        elif value.get('src'):
            source = [value]
    elif isinstance(value, list):
        source = value
    elif isinstance(value, str):
        source = [{'src': value}]

    items = []
    for item in source:
        if isinstance(item, str):
            src = item
            item_id = item
        elif isinstance(item, dict):
            src = str(item.get('src') or '').strip()
            item_id = str(item.get('name') or item.get('id') or src).strip()
        else:
            continue
        if src:
            items.append({'id': item_id or src, 'src': src})
    return items


def image_text(value) -> str:
    items = image_items(value)
    if not items:
        return EMPTY_VALUE
    return ', '.join(item.get('id') or item.get('src') or EMPTY_VALUE for item in items)


def display_name(rubric: dict, fields: list[dict], file_item: dict) -> str:
    title_field = next((field for field in fields if field['id'] == 'title'), None)
    if title_field:
        value = text_value(field_value(file_item, title_field))
        if value != EMPTY_VALUE:
            return value
    return str(rubric.get('name') or 'Карточка')


def format_timestamp(value) -> str:
    if value in (None, ''):
        return EMPTY_VALUE
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return text_value(value)
    if timestamp > 100000000000:
        timestamp /= 1000
    try:
        dt = datetime.fromtimestamp(timestamp, tz=timezone.get_current_timezone())
    except (OverflowError, OSError, ValueError):
        return EMPTY_VALUE
    return timezone.localtime(dt).strftime('%d.%m.%Y %H:%M')


def export_rows(rubric: dict, status_labels: dict[str, str]) -> tuple[list[dict], list[dict]]:
    fields = visible_fields(rubric)
    data_fields = [field for field in fields if field['id'] != 'title']
    files = rubric.get('files') if isinstance(rubric.get('files'), list) else []
    rows = []
    for file_item in files:
        if not isinstance(file_item, dict):
            continue
        status = normalize_file_status(file_item.get('status'), status_labels)
        system_date = file_item.get('updatedAt') or file_item.get('createdAt')
        row = {
            'name': display_name(rubric, fields, file_item),
            'status': status_labels.get(status, status_labels.get('keep', status)),
            'date': format_timestamp(system_date),
            'file': file_item,
            'fields': [],
        }
        for field in data_fields:
            raw = field_value(file_item, field)
            value = image_text(raw) if field['type'] == 'image' else text_value(raw)
            row['fields'].append({'field': field, 'value': value})
        rows.append(row)
    return fields, rows


def build_xlsx(rubric: dict, status_labels: dict[str, str]) -> bytes:
    fields, rows = export_rows(rubric, status_labels)
    data_fields = [field for field in fields if field['id'] != 'title']
    headers = ['Наименование', 'Статус', 'Дата создания/обновления']
    headers.extend(field['label'] for field in data_fields)
    table_rows = [headers]
    for row in rows:
        table_rows.append([row['name'], row['status'], row['date'], *[item['value'] for item in row['fields']]])

    def col_name(index: int) -> str:
        result = ''
        while index:
            index, remainder = divmod(index - 1, 26)
            result = chr(65 + remainder) + result
        return result

    sheet_rows = []
    for row_index, row in enumerate(table_rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            ref = f'{col_name(col_index)}{row_index}'
            escaped = html.escape(text_value(value), quote=False)
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escaped}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    col_count = max(1, len(headers))
    row_count = max(1, len(table_rows))
    dimension = f'A1:{col_name(col_count)}{row_count}'
    cols = ''.join(f'<col min="{index}" max="{index}" width="22" customWidth="1"/>' for index in range(1, col_count + 1))
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dimension}"/><cols>{cols}</cols><sheetData>{"".join(sheet_rows)}</sheetData>'
        '</worksheet>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Экспорт" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )

    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', content_types_xml)
        archive.writestr('_rels/.rels', rels_xml)
        archive.writestr('xl/workbook.xml', workbook_xml)
        archive.writestr('xl/_rels/workbook.xml.rels', workbook_rels_xml)
        archive.writestr('xl/worksheets/sheet1.xml', sheet_xml)
    return output.getvalue()


def load_font(size: int, bold: bool = False):
    candidates = [
        'C:/Windows/Fonts/arialbd.ttf' if bold else 'C:/Windows/Fonts/arial.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/local/share/fonts/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/local/share/fonts/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf',
        '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/dejavu/DejaVuSans.ttf',
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = str(text or EMPTY_VALUE).replace('\r\n', '\n').replace('\r', '\n').split()
    if not words:
        return [EMPTY_VALUE]
    lines = []
    line = ''
    for word in words:
        candidate = f'{line} {word}'.strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def decode_data_image(src: str) -> Image.Image | None:
    if not isinstance(src, str) or not src.startswith('data:image/'):
        return None
    try:
        _, payload = src.split(',', 1)
        image = Image.open(io.BytesIO(base64.b64decode(payload)))
        return image.convert('RGB')
    except (ValueError, OSError, UnidentifiedImageError, binascii.Error):
        return None


def primary_image(file_item: dict, fields: list[dict]) -> Image.Image | None:
    image_field = next((field for field in fields if field['type'] == 'image'), None)
    if not image_field:
        return None
    for item in image_items(field_value(file_item, image_field)):
        image = decode_data_image(item.get('src') or '')
        if image:
            return image
    return None


def build_pdf(rubric: dict, status_labels: dict[str, str]) -> bytes:
    fields, rows = export_rows(rubric, status_labels)
    title_font = load_font(34, bold=True)
    subtitle_font = load_font(18)
    card_title_font = load_font(22, bold=True)
    label_font = load_font(15, bold=True)
    body_font = load_font(15)
    muted_font = load_font(14)
    width, height = 1240, 1754
    margin = 70
    pages = []

    def new_page():
        page = Image.new('RGB', (width, height), '#f8fafc')
        return page, ImageDraw.Draw(page), margin

    page, draw, y = new_page()
    draw.text((margin, y), str(rubric.get('name') or 'Рубрика'), fill='#101828', font=title_font)
    y += 54
    exported_at = timezone.localtime(timezone.now()).strftime('%d.%m.%Y %H:%M')
    draw.text((margin, y), f'Дата выгрузки: {exported_at}', fill='#475467', font=subtitle_font)
    y += 30
    draw.text((margin, y), f'Карточек: {len(rows)}', fill='#475467', font=subtitle_font)
    y += 48

    def ensure_space(required: int):
        nonlocal page, draw, y
        if y + required <= height - margin:
            return
        pages.append(page)
        page, draw, y = new_page()

    if not rows:
        draw.text((margin, y), 'В этой рубрике пока нет карточек.', fill='#475467', font=body_font)
    for row in rows:
        file_item = row['file']
        image = primary_image(file_item, fields)
        x = margin + 28
        content_x = x + 250 if image else x
        text_width = width - margin - 28 - content_x
        title_lines = wrap_text(draw, row['name'], card_title_font, text_width)
        field_lines = []
        text_height = len(title_lines) * 30 + 68
        for item in row['fields']:
            field = item['field']
            if field['type'] == 'image':
                continue
            label = field['label']
            label_width = draw.textbbox((0, 0), f'{label}: ', font=label_font)[2]
            lines = wrap_text(draw, item['value'], body_font, max(160, text_width - label_width))
            field_lines.append((field, item['value'], label_width, lines))
            text_height += len(lines) * 24 + 6
        card_height = max(180, text_height + 56, 276 if image else 0)
        ensure_space(card_height + 26)
        card_top = y
        card_bottom = min(height - margin, y + card_height)
        draw.rounded_rectangle((margin, card_top, width - margin, card_bottom), radius=24, fill='#ffffff', outline='#d0d5dd', width=2)
        content_x = x
        if image:
            box_size = 220
            image.thumbnail((box_size, box_size))
            image_x = x
            image_y = card_top + 28
            draw.rounded_rectangle((image_x, image_y, image_x + box_size, image_y + box_size), radius=18, fill='#eef2f7')
            paste_x = image_x + (box_size - image.width) // 2
            paste_y = image_y + (box_size - image.height) // 2
            page.paste(image, (paste_x, paste_y))
            content_x = image_x + box_size + 30

        text_y = card_top + 28
        for line in title_lines:
            draw.text((content_x, text_y), line, fill='#101828', font=card_title_font)
            text_y += 30
        draw.text((content_x, text_y + 6), f"Статус: {row['status']}", fill='#344054', font=label_font)
        text_y += 34
        draw.text((content_x, text_y), f"Дата: {row['date']}", fill='#667085', font=muted_font)
        text_y += 34
        for field, value, label_width, lines in field_lines:
            label = field['label']
            draw.text((content_x, text_y), f'{label}:', fill='#344054', font=label_font)
            first_line = True
            for line in lines:
                line_x = content_x + label_width if first_line else content_x + 20
                draw.text((line_x, text_y), line, fill='#101828', font=body_font)
                text_y += 24
                first_line = False
            text_y += 6
        y = card_bottom + 24

    pages.append(page)
    output = io.BytesIO()
    first, rest = pages[0], pages[1:]
    first.save(output, format='PDF', save_all=True, append_images=rest, resolution=150.0)
    return output.getvalue()


def file_response(content: bytes, filename: str, content_type: str) -> HttpResponse:
    response = HttpResponse(content, content_type=content_type)
    response['Content-Disposition'] = content_disposition(filename)
    return response
