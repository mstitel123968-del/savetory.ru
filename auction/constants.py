"""Shared constants for the auction integration with «Ваш архив»."""

# Identity of the per-user system rubric that holds auction cards.
AUCTION_RUBRIC_NAME = 'Аукцион'
AUCTION_RUBRIC_SLUG = 'auction'

# Standard product-condition values, used both by the create-lot form and the
# «фильтр по состоянию» on the auction page. Stored in the card's `condition`
# field as the value (e.g. 'good'); the label is for display.
CONDITION_OPTIONS = [
    ('new', 'Новое'),
    ('like_new', 'Как новое'),
    ('good', 'Хорошее'),
    ('used', 'Б/у'),
    ('for_parts', 'На запчасти'),
]
CONDITION_LABELS = dict(CONDITION_OPTIONS)

# Fixed set of card fields for the system «Аукцион» rubric. The schema matches
# the shape the archive SPA uses ({id, label, type, description, modes?}).
# These fields are immutable: they cannot be added to, removed, reordered or
# edited by the user.
AUCTION_FIELD_SCHEMA = [
    {'id': 'title', 'label': 'Наименование', 'type': 'text',
     'description': 'Название товара', 'system': True},
    {'id': 'photo', 'label': 'Фотографии', 'type': 'image',
     'description': 'Изображения товара', 'system': True},
    {'id': 'description', 'label': 'Описание', 'type': 'textarea',
     'description': 'Подробное описание товара', 'system': True},
    {'id': 'category', 'label': 'Категория товара', 'type': 'text',
     'description': 'Категория или раздел товара', 'system': True},
    {'id': 'condition', 'label': 'Состояние', 'type': 'select',
     'description': 'Состояние товара', 'system': True,
     'options': [{'value': v, 'label': l} for v, l in CONDITION_OPTIONS]},
    {'id': 'completeness', 'label': 'Комплектность', 'type': 'text',
     'description': 'Что входит в комплект', 'system': True},
    {'id': 'location', 'label': 'Местонахождение', 'type': 'text',
     'description': 'Где находится товар', 'system': True},
    {'id': 'handover', 'label': 'Способ передачи', 'type': 'text',
     'description': 'Как товар передаётся покупателю', 'system': True},
    {'id': 'extra', 'label': 'Дополнительная информация', 'type': 'textarea',
     'description': 'Любые дополнительные сведения', 'system': True},
]
