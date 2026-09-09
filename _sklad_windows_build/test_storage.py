import tempfile
import unittest
from pathlib import Path

from storage import Storage


class StorageTests(unittest.TestCase):
    def test_repeated_photo_reorder_preserves_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Storage(root, root, root / 'data')
            sources = []
            for index in range(3):
                path = root / f'{index}.png'
                path.write_bytes(bytes([index]))
                sources.append(str(path))
            card = store.add_card('r', {'title': 'Фото'}, sources)
            expected = [0, 1, 2]
            for _ in range(5):
                expected.reverse()
                store.update_card(card['id'], 'r', card['values'], list(reversed(card['images'])))
                self.assertEqual([Path(p).read_bytes()[0] for p in card['images']], expected)
                self.assertEqual(len(list(store.images_dir.iterdir())), 3)

    def test_photo_update_rollback_on_save_error(self):
        from unittest.mock import patch
        from copy import deepcopy
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Storage(root, root, root / 'data')
            source = root / 'photo.png'
            source.write_bytes(b'original')
            card = store.add_card('r', {'title': 'Original'}, [str(source)])
            previous = deepcopy(card)
            with patch.object(store, 'save', side_effect=OSError('Disk full')):
                with self.assertRaises(OSError):
                    store.update_card(card['id'], 'r', {'title': 'Changed'}, card['images'])
            self.assertEqual(card, previous)
            self.assertEqual(Path(card['images'][0]).read_bytes(), b'original')
            self.assertEqual(len(list(store.images_dir.iterdir())), 1)

    def test_standard_rubrics_removed_without_losing_cards(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / 'data'
            data.mkdir()
            original = {'rubrics': [{'id': 'coins', 'name': 'Монеты'}, {'id': 'custom', 'name': 'Мои вещи'}],
                        'cards': [{'id': 'user-card', 'rubric_id': 'coins', 'values': {'title': 'Моя монета'}, 'images': []}], 'settings': {}}
            (data / 'data.json').write_text(json.dumps(original), encoding='utf-8')
            store = Storage(root, root, data)
            self.assertEqual([r['id'] for r in store.data['rubrics']], ['custom'])
            self.assertEqual(store.data['cards'], original['cards'])
            self.assertEqual(store.rubric('coins')['name'], 'Монеты')
            self.assertTrue((data / 'data.before-standard-rubrics-removal.json').exists())
            again = Storage(root, root, data)
            self.assertEqual(len(again.data['retired_rubrics']), 1)

    def test_new_storage_starts_without_cards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Storage(root, root, root / "data")
            self.assertEqual(store.data["cards"], [])
            self.assertEqual(store.data['rubrics'], [])

    def test_add_and_remove_card(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Storage(root, root, root / "data")
            store.data = {"rubrics": [{"id": "r", "name": "Тест", "icon": "○"}], "cards": [], "settings": {}}
            card = store.add_card("r", {"title": "Предмет", "description": "Описание"})
            self.assertEqual(store.card(card["id"])["values"]["title"], "Предмет")
            store.delete_card(card["id"])
            self.assertEqual(store.data["cards"], [])

    def test_duplicate_rubric_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Storage(root, root, root / "data")
            store.data = {"rubrics": [], "cards": [], "settings": {}}
            store.add_rubric("Монеты")
            with self.assertRaises(ValueError):
                store.add_rubric("монеты")

    def test_rubric_fields_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Storage(root, root, root / "data")
            store.data = {"rubrics": [], "cards": [], "settings": {}}
            first = store.add_rubric("Монеты")
            second = store.add_rubric("Марки")
            first["fields"][0]["enabled"] = False
            self.assertTrue(second["fields"][0]["enabled"])

    def test_demo_cards_are_removed_without_touching_user_cards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Storage(root, root, root / "data")
            store.data["cards"] = [
                {"id": "coin-1896", "rubric_id": "coins"},
                {"id": "user-card", "rubric_id": "coins", "values": {"title": "Моя карточка"}, "images": []},
            ]
            store._migrate()
            self.assertEqual([card["id"] for card in store.data["cards"]], ["user-card"])


if __name__ == "__main__":
    unittest.main()
