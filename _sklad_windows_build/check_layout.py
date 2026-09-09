import os
import tempfile
with tempfile.TemporaryDirectory() as folder:
    os.environ['SKLAD_DATA_DIR'] = folder
    from app import SKladApp
    app = SKladApp()
    app.root.geometry('1500x920')
    rubric = app.store.add_rubric('Test')
    app.store.add_card(rubric['id'], {'title': 'Test'})
    app.root.update()
    for color in ('#994400', '#657b16', '#123456'):
        app.settings.update(theme='custom', theme_color=color, view='grid')
        app.apply_settings()
        app.root.update()
        print('theme', color, app.main.winfo_width(), app.scroll.inner.grid_size(), app.add_tile.winfo_width(), app.add_tile.winfo_height(), flush=True)
        for mode in ('list', 'grid', 'grid'):
            app.set_view(mode)
            app.root.update()
            print(mode, app.main.winfo_width(), app.scroll.inner.grid_size(), app.add_tile.winfo_width(), app.add_tile.winfo_height(), flush=True)
    from app import SettingsDialog
    from surfaces import RoundedTabs
    dialog = SettingsDialog(app)
    app.root.update()
    tabs = next(w for w in dialog.winfo_children() if isinstance(w, RoundedTabs))
    assert tabs.selected_index == 0
    for index in (0, 4, 2, 1, 3, 0):
        tabs.select(index)
        app.root.update()
        # Tk reports siblings in stacking order: the selected page is highest.
        pages = [w for w in tabs.winfo_children() if w in tabs.pages]
        assert pages[-1] is tabs.pages[index]
    dialog.destroy()
    app.set_view('list')
    app.root.update()
    from unittest.mock import patch
    import tkinter as tk
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    more = next(w for w in descendants(app.scroll.inner) if getattr(w, 'caption', '') == 'Ещё')
    row = more.master
    with patch('app.CardViewDialog') as opened:
        for widget in (row.shell, row, next(w for w in descendants(row) if isinstance(w, tk.Label))):
            widget.event_generate('<ButtonRelease-1>', x=2, y=2)
        assert opened.call_count == 3
        more.invoke()
        app.root.update()
        assert opened.call_count == 3
    popup = app._card_popup
    assert popup.winfo_rooty() >= more.winfo_rooty()+more.winfo_height()
    assert popup.winfo_rootx() >= app.root.winfo_rootx()
    assert popup.winfo_rootx()+popup.winfo_width() <= app.root.winfo_rootx()+app.root.winfo_width()
    assert popup.winfo_rooty()+popup.winfo_height() <= app.root.winfo_rooty()+app.root.winfo_height()
    popup.dismiss()
    app.root.destroy()
