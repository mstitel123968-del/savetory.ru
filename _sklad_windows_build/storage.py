from __future__ import annotations

import json
import os
import shutil
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any
from licensing import FREE_LIMIT, is_licensed


APP_NAME = "SKlad"

DEFAULT_FIELDS = [
    {"id": "photo", "label": "Фото", "type": "image", "enabled": True, "required": True},
    {"id": "title", "label": "Наименование", "type": "text", "enabled": True, "required": True},
    {"id": "location", "label": "Расположение", "type": "text", "enabled": True},
    {"id": "material", "label": "Материал", "type": "text", "enabled": True},
    {"id": "price", "label": "Стоимость", "type": "text", "enabled": True},
    {"id": "description", "label": "Описание", "type": "textarea", "enabled": True},
]

DEFAULT_SETTINGS = {
    "view": "grid",
    "sort": "created",
    "theme": "dark",
    "theme_color": "#0b1316",
    "accent": "green",
    "accent_color": "#3da653",
    "background_style": "gradient",
    "background_intensity": 68,
    "card_style": "outline",
    "font_scale": 100,
    "font_family": "Segoe UI",
    "line_height": "normal",
    "body_weight": "regular",
    "heading_font": "sans",
    "heading_style": "minimal",
    "heading_color": "auto",
    "text_tone": "balanced",
    "density": "cozy",
    "sidebar_size": "normal",
    "topbar_mode": "floating",
    "reduce_motion": False,
    "focus_strong": False,
    "plain_background": False,
    "show_hints": True,
    "card_size": "medium",
    "empty_fields": "dash",
    "thumbnails": "always",
}

DEMO_CARD_IDS = {
    "coin-1896", "space-stamp", "gaz-m20", "fed-2", "watch-flight",
    "moscow-postcard", "abbey-road", "robot-r35",
}


DEFAULT_DATA: dict[str, Any] = {
    "rubrics": [],
    "cards": [],
    "settings": deepcopy(DEFAULT_SETTINGS),
}


class Storage:
    def __init__(self, app_dir: Path, bundled_assets: Path, data_root: Path | None = None):
        self.app_dir = app_dir
        self.bundled_assets = bundled_assets
        override = os.environ.get("SKLAD_DATA_DIR")
        root = data_root or (Path(override) if override else Path(os.environ.get("APPDATA", Path.home())) / APP_NAME)
        self.data_dir = root
        self.images_dir = root / "images"
        self.file = root / "data.json"
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        self.images_dir.mkdir(parents=True, exist_ok=True)
        if not self.file.exists():
            self.data = deepcopy(DEFAULT_DATA)
            self._migrate()
            self.save()
            return
        try:
            raw = json.loads(self.file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("invalid data root")
            self.data = raw
            self.data.setdefault("rubrics", [])
            self.data.setdefault("cards", [])
            self.data.setdefault("settings", {})
            for key, value in DEFAULT_SETTINGS.items():
                self.data["settings"].setdefault(key, value)
            self._migrate()
        except (OSError, ValueError, json.JSONDecodeError):
            backup = self.file.with_suffix(".broken.json")
            try:
                shutil.copy2(self.file, backup)
            except OSError:
                pass
            self.data = deepcopy(DEFAULT_DATA)
            self.save()

    def save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temp = self.file.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.file)

    def add_rubric(self, name: str) -> dict[str, str]:
        name = name.strip()
        if not name:
            raise ValueError("Введите название рубрики")
        if any(r["name"].casefold() == name.casefold() for r in self.data["rubrics"]):
            raise ValueError("Такая рубрика уже существует")
        rubric = {"id": uuid.uuid4().hex, "name": name, "icon": "collection_box.png", "fields": deepcopy(DEFAULT_FIELDS)}
        self.data["rubrics"].append(rubric)
        self.save()
        return rubric

    def delete_rubric(self, rubric_id: str) -> None:
        if any(c["rubric_id"] == rubric_id for c in self.data["cards"]):
            raise ValueError("Сначала перенесите или удалите карточки этой рубрики")
        self.data["rubrics"] = [r for r in self.data["rubrics"] if r["id"] != rubric_id]
        self.save()

    def update_rubric(self, rubric_id: str, name: str, icon: str, fields: list[dict[str, Any]]) -> None:
        rubric = self.rubric(rubric_id)
        if not rubric:
            raise KeyError(rubric_id)
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Введите название рубрики")
        if any(r["id"] != rubric_id and r["name"].casefold() == clean_name.casefold() for r in self.data["rubrics"]):
            raise ValueError("Такая рубрика уже существует")
        rubric.update({"name": clean_name, "icon": icon, "fields": fields})
        self.save()

    def add_card(self, rubric_id: str, values: dict[str, str], image_sources: list[str] | None = None, status: str = "keep") -> dict[str, Any]:
        if not self.can_add_card():
            raise ValueError('Бесплатно можно хранить до 10 карточек. Полная версия — 299 ₽, один раз.')
        card_id = uuid.uuid4().hex
        images = self._import_images(image_sources or [], card_id)
        card = {"id": card_id, "rubric_id": rubric_id, "values": values, "images": images, "status": status}
        self.data["cards"].insert(0, card)
        try:
            self.save()
        except Exception:
            self.data['cards'].remove(card)
            for reference in images:
                self._delete_local_image(reference)
            raise
        return card

    def can_add_card(self):
        return len(self.data['cards']) < FREE_LIMIT or self.is_licensed()

    def is_licensed(self):
        return is_licensed(self.data_dir, self.bundled_assets)

    def update_card(self, card_id: str, rubric_id: str, values: dict[str, str], image_sources: list[str] | None = None, status: str = "keep") -> None:
        card = self.card(card_id)
        previous = deepcopy(card)
        next_images = None
        if image_sources is not None:
            # Every edit gets fresh filenames: reordering must never overwrite
            # another source photo or copy a file onto itself.
            next_images = self._import_images(image_sources, f"{card_id}-{uuid.uuid4().hex}")
        card.update({"rubric_id": rubric_id, "values": values, "status": status})
        if next_images is not None:
            card["images"] = next_images
        try:
            self.save()
        except Exception:
            card.clear()
            card.update(previous)
            for reference in next_images or []:
                self._delete_local_image(reference)
            raise
        if next_images is not None:
            for reference in previous.get("images", []):
                self._delete_local_image(reference)

    def delete_card(self, card_id: str) -> None:
        card = self.card(card_id)
        previous = self.data['cards']
        self.data["cards"] = [c for c in self.data["cards"] if c["id"] != card_id]
        try:
            self.save()
        except Exception:
            self.data['cards'] = previous
            raise
        for reference in card.get("images", []):
            self._delete_local_image(reference)

    def card(self, card_id: str) -> dict[str, str]:
        for item in self.data["cards"]:
            if item["id"] == card_id:
                return item
        raise KeyError(card_id)

    def rubric(self, rubric_id: str) -> dict[str, str] | None:
        return next((r for r in self.data["rubrics"] + self.data.get('retired_rubrics', []) if r["id"] == rubric_id), None)

    def resolve_image(self, reference: str) -> Path | None:
        if reference.startswith("asset:"):
            path = self.bundled_assets / reference.removeprefix("asset:")
        else:
            path = Path(reference) if reference else Path()
        return path if path.is_file() else None

    def _import_images(self, sources: list[str], card_id: str) -> list[str]:
        imported = []
        try:
            for index, source in enumerate(sources[:5]):
                if source:
                    imported.append(self._import_image(source, f"{card_id}-{index}"))
            return imported
        except Exception:
            for reference in imported:
                self._delete_local_image(reference)
            raise

    def _import_image(self, source: str, file_id: str) -> str:
        src = Path(source)
        if not src.is_file():
            return "asset:collection_box.png"
        suffix = src.suffix.lower() if src.suffix else ".png"
        destination = self.images_dir / f"{file_id}{suffix}"
        shutil.copy2(src, destination)
        return str(destination)

    def _delete_local_image(self, reference: str) -> None:
        path = self.resolve_image(reference)
        if path and path.parent == self.images_dir:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _migrate(self) -> None:
        changed = False
        if not self.data.get('standard_rubrics_removed'):
            standards = {'coins': 'Монеты', 'stamps': 'Марки', 'models': 'Модели', 'postcards': 'Открытки'}
            removed = [r for r in self.data['rubrics'] if standards.get(r.get('id')) == r.get('name')]
            if removed and self.file.exists():
                backup = self.data_dir / 'data.before-standard-rubrics-removal.json'
                if not backup.exists():
                    shutil.copy2(self.file, backup)
            # Keep the field definitions for viewing/editing existing cards only.
            self.data.setdefault('retired_rubrics', []).extend(removed)
            self.data['rubrics'] = [r for r in self.data['rubrics'] if r not in removed]
            self.data['standard_rubrics_removed'] = True
            changed = True
        filtered_cards = [card for card in self.data.get("cards", []) if card.get("id") not in DEMO_CARD_IDS]
        if len(filtered_cards) != len(self.data.get("cards", [])):
            self.data["cards"] = filtered_cards
            changed = True
        if self.data.get("settings", {}).get("density") == "comfortable":
            self.data["settings"]["density"] = "cozy"
            changed = True
        for rubric in self.data["rubrics"] + self.data.get('retired_rubrics', []):
            if "fields" not in rubric:
                rubric["fields"] = deepcopy(DEFAULT_FIELDS)
                changed = True
            icon = rubric.get("icon", "")
            icon_map = {"◎": "coin.png", "▧": "stamp.png", "◇": "model_car.png", "▣": "postcard.png", "○": "collection_box.png"}
            if icon in icon_map:
                rubric["icon"] = icon_map[icon]
                changed = True
        for card in self.data["cards"]:
            if "values" not in card:
                card["values"] = {
                    "title": card.pop("title", ""),
                    "description": card.pop("details", ""),
                    "year": card.pop("year", ""),
                }
                old_image = card.pop("image", "")
                card["images"] = [old_image] if old_image else []
                card["status"] = "keep"
                changed = True
        if changed:
            self.save()
