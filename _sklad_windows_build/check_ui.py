"""Isolated rendering smoke checks. Never opens the user's collection."""
import os
import tempfile
from copy import deepcopy
from unittest.mock import patch

with tempfile.TemporaryDirectory(prefix='sklad-ui-') as folder:
    os.environ['SKLAD_DATA_DIR'] = folder
    from app import SKladApp, SettingsDialog, RubricDialog, CardDialog, CardViewDialog, PurchaseDialog
    app = SKladApp()
    failures = []
    app.root.report_callback_exception = lambda kind, value, tb: failures.append(str(value))
    app.root.update()
    assert not app.store.data['cards']
    assert not app.store.data['rubrics']
    assert app.usage_caption.get() == 'Заполнено 0 из 10'
    assert not app.scroll.scrollbar.winfo_manager(), 'Empty archive must not show a scrollbar'
    for theme in ('dark', 'light', 'custom', 'glass'):
        app.settings['theme'] = theme
        app.apply_settings()
        app.root.update()
        purchase = PurchaseDialog(app)
        app.root.update()
        assert purchase.winfo_width() >= 600
        purchase.destroy()
        for dialog_type in (SettingsDialog, RubricDialog, CardDialog):
            dialog = dialog_type(app)
            app.root.update()
            assert dialog.winfo_width() > 600
            backdrop = getattr(dialog, 'backdrop', None)
            if dialog_type in (SettingsDialog, CardDialog):
                assert dialog.overrideredirect()
                assert backdrop.winfo_ismapped()
            dialog.destroy()
            if backdrop is not None:
                assert not backdrop.winfo_exists()
        card = {'id': 'qa-card', 'rubric_id': 'coins', 'values': {'title': 'Проверка карточки', 'material': 'Серебро'}, 'images': []}
        app.store.data['cards'] = [card]
        app.refresh()
        app.root.update()
        assert not app.scroll.scrollbar.winfo_manager(), 'One card must not show a scrollbar'
        assert app.usage_caption.get() == 'Заполнено 1 из 10'
        assert app.usage_bar.winfo_manager() == 'grid'
        with patch.object(app.store, 'is_licensed', return_value=True):
            app.refresh()
            app.root.update()
            assert not app.usage_bar.winfo_manager(), 'Paid version must not show the free quota or Buy button'
        app.refresh()
        dialog = CardViewDialog(app, card)
        app.root.update()
        dialog.destroy()
        app.store.data['cards'] = [dict(deepcopy(card), id=f'qa-{n}') for n in range(36)]
        app.refresh()
        app.root.update()
        assert app.scroll.scrollbar.winfo_manager(), 'Overflow must remain scrollable'
        app.search_var.set('no-matching-cards')
        app.root.update()
        assert not app.scroll.scrollbar.winfo_manager(), 'Scrollbar must hide after filtering'
        app.search_var.set('')
        app.store.data['cards'] = []
        app.refresh()
        app.root.update()
    rubric = app.store.add_rubric('Проверка меню')
    app.refresh()
    app.root.update()
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    dots = [widget for widget in descendants(app.rubric_nav) if getattr(widget, 'caption', '') == '⋮']
    assert len(dots) == 1, 'Only actual rubrics must have an actions button'
    original_rows = [row for row, paint in app.nav_rows]
    app.select_rubric(rubric['id'])
    assert [row for row, paint in app.nav_rows] == original_rows
    assert all(row.winfo_exists() for row in original_rows)
    app.root.update()
    assert all(row.shell.winfo_height() < 100 for row in original_rows)
    app.select_rubric('all')
    row = dots[0].master
    dots[0].event_generate('<Enter>')
    app.root.update()
    assert row.fill == app.p.selected, 'Hover must highlight the entire rubric'
    assert int(dots[0].cget('borderwidth')) == 0
    with patch.object(app, 'select_rubric') as select:
        row.shell.event_generate('<ButtonRelease-1>', x=5, y=5)
        select.assert_called_once_with(rubric['id'])
    for theme in ('dark', 'light', 'custom', 'glass'):
        app.settings['theme'] = theme
        app.apply_settings()
        app.root.update()
        dots = [widget for widget in descendants(app.rubric_nav) if getattr(widget, 'caption', '') == '⋮']
        dots[0].command()
        app.root.update()
        menu = app._rubric_popup
        assert menu.winfo_width() < 280 and menu.winfo_height() < 140, 'Actions popup must fit its two entries'
        assert [button.caption for button in menu.buttons] == ['Редактировать', 'Удалить']
        assert menu._palette is app.p
        with patch.object(app, 'edit_rubric') as edit:
            menu.buttons[0].invoke()
            edit.assert_called_once_with(rubric['id'])
        assert not menu.winfo_exists()
    app.store.add_card(rubric['id'], {'title': 'Сохранить'})
    with patch('app.messagebox.showinfo') as info:
        app.delete_rubric(rubric['id'])
        info.assert_called_once()
    assert app.store.rubric(rubric['id'])
    app.store.delete_card(app.store.data['cards'][0]['id'])
    with patch('app.messagebox.askyesno', return_value=False):
        app.delete_rubric(rubric['id'])
    assert app.store.rubric(rubric['id'])
    app.selected_rubric = rubric['id']
    with patch('app.messagebox.askyesno', return_value=True):
        app.delete_rubric(rubric['id'])
    assert app.store.rubric(rubric['id']) is None
    assert app.selected_rubric == 'all'
    from types import SimpleNamespace
    dialog = RubricDialog(app)
    app.root.update()
    original = [field['id'] for field in dialog.fields]
    source = dialog.field_rows[1]
    target = dialog.field_rows[3]
    dialog.start_field_drag(SimpleNamespace(y_root=source.shell.winfo_rooty(), y=10, widget=source), 1, False)
    dialog.drag_field(SimpleNamespace(y_root=target.shell.winfo_rooty() + target.shell.winfo_height() // 2))
    app.root.update()
    ghost = dialog._field_drag['ghost']
    assert ghost.winfo_ismapped(), 'Grabbed field must be visible above the list'
    first_y = ghost.winfo_y()
    dialog.drag_field(SimpleNamespace(y_root=target.shell.winfo_rooty() + target.shell.winfo_height() // 2 + 3))
    app.root.update()
    assert ghost.winfo_y() == first_y + 3, 'Grabbed field must follow the pointer'
    dialog.finish_field_drag(None)
    assert not ghost.winfo_exists(), 'Drop must remove the floating field'
    app.root.update()
    assert dialog.fields[3]['id'] == original[1], 'Dragging must reorder the fields'
    dialog.move_field(3, -1)
    assert dialog.fields[2]['id'] == original[1], 'Arrow click must still move a field'
    before_cancel = [field['id'] for field in dialog.fields]
    source = dialog.field_rows[1]
    dialog.start_field_drag(SimpleNamespace(y_root=source.shell.winfo_rooty(), y=10, widget=source), 1, False)
    dialog.drag_field(SimpleNamespace(y_root=source.shell.winfo_rooty() + 80))
    ghost = dialog._field_drag['ghost']
    dialog.cancel_field_drag()
    assert not ghost.winfo_exists()
    assert [field['id'] for field in dialog.fields] == before_cancel
    dialog.destroy()
    from app import ListOptionsDialog
    owner = RubricDialog(app)
    app.root.update()
    owner.new_field_entry.editor.insert(0, 'Новое поле')
    owner.new_field_entry.editor.focus_set()
    app.root.update()
    assert owner.grab_current() is owner
    assert owner.new_field.get() == 'Новое поле'
    owner.add_field_button.invoke()
    app.root.update()
    assert any(field['label'] == 'Новое поле' for field in owner.fields)
    options = ListOptionsDialog(owner)
    app.root.update()
    assert len(options.option_vars) == 3
    options.option_vars[0].set('Первый')
    options.option_vars[1].set('Второй')
    options.add_option('Третий')
    options.save()
    assert options.result == ['Первый', 'Второй', 'Третий']
    owner.destroy()
    rubric = app.store.add_rubric('Список')
    field = {'id': 'choice', 'label': 'Выбор', 'type': 'select', 'enabled': True, 'options': options.result}
    rubric['fields'].append(field)
    app.store.save()
    card = app.store.add_card(rubric['id'], {'title': 'Тест', 'choice': 'Второй'})
    editor = CardDialog(app, card)
    app.root.update()
    assert not hasattr(editor, 'status_var')
    assert editor.value_vars['choice'].get() == 'Второй'
    editor.value_vars['choice'].set('Третий')
    from pathlib import Path
    from PIL import Image
    paths = []
    for n, color in enumerate(('red', 'green', 'blue')):
        path = Path(folder) / f'photo-{n}.png'
        Image.new('RGB', (80, 60), color).save(path)
        paths.append(str(path))
    editor.image_paths = paths[:2]
    editor.images_dirty = True
    editor.render_fields()
    def cancel_file_picker(**kwargs):
        assert kwargs['parent'] is app.root
        assert not editor.winfo_viewable()
        assert editor.grab_current() is not editor
        return ()
    with patch('app.filedialog.askopenfilenames', side_effect=cancel_file_picker):
        editor.add_images()
    app.root.update()
    assert editor.winfo_viewable() and editor.grab_current() is editor
    assert editor.image_paths == paths[:2]
    with patch('app.filedialog.askopenfilenames', return_value=(paths[2],)):
        editor.add_images()
    app.root.update()
    assert editor.winfo_viewable() and editor.grab_current() is editor
    assert editor.image_paths == paths
    editor.remove_image(2)
    def failed_picker(**kwargs):
        raise OSError('test chooser failure')
    try:
        editor.choose_native_file(failed_picker)
    except OSError:
        pass
    app.root.update()
    assert editor.winfo_viewable() and editor.grab_current() is editor
    editor.move_image(1, -1)
    assert editor.image_paths == [paths[1], paths[0]]
    with patch('app.filedialog.askopenfilename', return_value=paths[2]):
        editor.replace_image(0)
    assert editor.image_paths[0] == paths[2]
    editor.remove_image(1)
    assert len(editor.image_previews) == 1
    editor.save()
    view = CardViewDialog(app, card)
    app.root.update()
    original_editor = CardDialog
    def cancel_editor(*args, **kwargs):
        dialog = original_editor(*args, **kwargs)
        def verify_editor():
            assert dialog.winfo_viewable()
            assert dialog.grab_current() is dialog
            assert not view.winfo_viewable()
            dialog.destroy()
        dialog.after(200, verify_editor)
        return dialog
    with patch('app.CardDialog', side_effect=cancel_editor):
        view.edit()
    app.root.update()
    assert view.winfo_viewable() and view.grab_current() is view
    view.destroy()
    app.card_menu(card)
    app.root.update()
    assert [button.caption for button in app._card_popup.buttons] == ['Открыть', 'Редактировать', 'Удалить']
    app._card_popup.dismiss()
    assert app.store.card(card['id'])['values']['choice'] == 'Третий'
    saved_image = app.store.resolve_image(app.store.card(card['id'])['images'][0])
    with Image.open(saved_image) as photo:
        assert photo.getpixel((0, 0)) == (0, 0, 255)
    from app import ThemeColorDialog
    settings = SettingsDialog(app)
    app.root.update()
    from surfaces import RoundedCombo
    theme_combo = next(widget for widget in descendants(settings)
                       if isinstance(widget, RoundedCombo) and 'Стеклянная' in widget.values)
    for theme_label in ('Светлая', 'Стеклянная', 'Свой цвет', 'Тёмная'):
        theme_combo.open_menu()
        app.root.update()
        popup = theme_combo._menu
        choice = next(widget for widget in descendants(popup) if getattr(widget, 'caption', '') == theme_label)
        choice.invoke()
        app.root.update()
        assert settings.winfo_viewable(), 'Settings must remain visible after choosing a theme'
        assert settings.grab_current() is settings, 'Theme popup must return input to settings'
        assert theme_combo.get() == theme_label
    colors = ThemeColorDialog(settings, '#123456')
    app.root.update()
    assert colors.winfo_viewable() and colors.grab_current() is colors
    from surfaces import RoundedSlider
    sliders = [widget for widget in descendants(colors) if isinstance(widget, RoundedSlider)]
    assert [slider.color for slider in sliders] == ['#ef4444', '#22c55e', '#3b82f6']
    assert str(colors.transient()) == str(settings)
    settings.event_generate('<FocusIn>')
    app.root.update()
    assert colors.winfo_viewable() and colors.grab_current() is colors
    colors.channels[0].set(255)
    assert colors.hex_var.get() == '#ff3456'
    colors.hex_var.set('#abcdef')
    assert [v.get() for v in colors.channels] == [171, 205, 239]
    colors.save()
    app.root.update()
    assert settings.winfo_viewable() and settings.grab_current() is settings
    assert colors.result == '#abcdef'
    settings.destroy()
    app.refresh()
    app.root.update()
    assert app.add_tile.winfo_ismapped()
    with patch.object(app, 'add_card') as add:
        app.add_tile.event_generate('<ButtonRelease-1>', x=10, y=10)
        add.assert_called_once()
    editor = CardDialog(app, app.store.card(card['id']))
    app.root.update()
    description = editor.text_fields['description']
    description.delete('1.0', 'end')
    description.insert('1.0', 'Текст после вставки без KeyRelease')
    editor.render_fields()
    assert editor.value_vars['description'].get() == 'Текст после вставки без KeyRelease'
    editor.save()
    assert app.store.card(card['id'])['values']['description'] == 'Текст после вставки без KeyRelease'
    for geometry in ('1040x680', '1280x720', '1500x920'):
        app.root.geometry(geometry)
        app.root.update()
        for theme in ('dark', 'light', 'custom', 'glass'):
            app.settings['theme'] = theme
            app.apply_settings()
            app.root.update()
            frames = [w for w in app.scroll.inner.winfo_children() if isinstance(w, __import__('tkinter').Canvas) and w is not app.add_tile]
            if frames:
                assert abs(app.add_tile.winfo_height() - frames[0].winfo_height()) <= 2, 'Add tile must match a card'
            for cls in (CardDialog, SettingsDialog):
                modal = cls(app)
                app.root.update()
                assert modal.winfo_height() <= app.root.winfo_height(), (geometry, cls.__name__, modal.winfo_height())
                modal.destroy()
                app.root.update()
                assert app.root.grab_current() is None
    app.root.geometry('1500x920')
    app.settings['view'] = 'grid'
    app.settings['theme'] = 'custom'
    sizes = []
    for color in ('#994400', '#657b16', '#123456', '#eeeeee'):
        app.settings['theme_color'] = color
        app.apply_settings()
        app.root.update()
        sizes.append((app.add_tile.winfo_width(), app.add_tile.winfo_height()))
        for view_mode in ('list', 'grid', 'list', 'grid'):
            app.set_view(view_mode)
            app.root.update()
            assert app.scroll._background_key[2] == app.scroll.inner.winfo_reqheight()
        assert (app.add_tile.winfo_width(), app.add_tile.winfo_height()) == sizes[-1]
    assert len(set(sizes)) == 1, sizes
    settings = SettingsDialog(app)
    app.root.update()
    from surfaces import RoundedTabs
    tabs = next(w for w in descendants(settings) if isinstance(w, RoundedTabs))
    for index in (4, 1, 2, 0, 3, 4):
        tabs.select(index)
        app.root.update()
        assert tabs.pages[index].winfo_width() == tabs.body.winfo_width()
        assert tabs.pages[index].winfo_height() == tabs.body.winfo_height()
    for widget in descendants(tabs.pages[4]):
        if isinstance(widget, __import__('tkinter').Label):
            assert widget.cget('bg') == widget.master.cget('bg')
    settings.destroy()
    app.root.destroy()
    assert not failures, failures
    print('Four themes, all dialogs, empty/single/overflow/search states: OK')
