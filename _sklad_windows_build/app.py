from __future__ import annotations

import ctypes
import math
import os
import sys
import json
import queue
import threading
import uuid
import webbrowser
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import Image, ImageTk
import licensing

from storage import DEFAULT_FIELDS, DEFAULT_SETTINGS, Storage
from surfaces import RoundedButton, RoundedPanel, RoundedEntry, RoundedCombo, RoundedTabs, RoundedSlider, SlimScrollbar, RoundedPopup


ACCENTS = {
    "Синий": "blue", "Чёрный": "black", "Красный": "red", "Зелёный": "green",
    "Фиолетовый": "violet", "Янтарный": "amber", "Бирюзовый": "cyan", "Свой цвет": "custom",
}
ICONS = {
    "Монета": "coin.png", "Марка": "stamp.png", "Автомобиль": "model_car.png",
    "Открытки": "postcard.png", "Награды": "medal.png", "Книги": "book.png",
    "Пластинки": "vinyl.png", "Часы": "watch.png", "Фигурки": "figurine.png",
    "Минералы": "minerals.png", "Фото": "camera.png", "Кубки": "trophy.png",
    "Раковины": "shell.png", "Техника": "toy_robot.png", "Другое": "collection_box.png",
    "Знаки": "badge.png", "Банкноты": "banknote.png", "Карточки": "trading_cards.png",
    "Брелоки": "keychain.png", "Картины": "painting.png",
}
STATUSES = {
    "Храню": "keep", "Готов продать": "sell", "Готов обменять": "exchange",
    "Ищу такой же": "search", "Продано": "sold",
}


def resource_path(name: str = "") -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


def mix(a: str, b: str, weight: float) -> str:
    weight = max(0.0, min(1.0, weight))
    aa = tuple(int(a[i:i + 2], 16) for i in (1, 3, 5))
    bb = tuple(int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x * weight + y * (1 - weight)):02x}" for x, y in zip(aa, bb))


def is_light(color: str) -> bool:
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    return sum(channel * weight for channel, weight in zip(rgb, (.2126, .7152, .0722))) > 155


def enable_dark_titlebar(window: tk.Tk | tk.Toplevel, dark: bool) -> None:
    if os.name != "nt":
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


class Palette:
    def __init__(self, settings: dict):
        theme = settings.get("theme", "dark")
        custom = settings.get("theme_color", "#0b1316")
        self.glass = theme == "glass"
        if self.glass:
            base = custom if isinstance(custom, str) and len(custom) == 7 else "#162a44"
            light = is_light(base)
            panel = mix(base, "#ffffff", .90 if light else .86)
            text, muted = ("#17202c", "#425166") if light else ("#f5f8ff", "#b9c7da")
            border = mix(panel, "#334155" if light else "#ffffff", .76)
        elif theme == "light":
            base, panel, text, muted, border = "#f4f6f2", "#ffffff", "#19211c", "#68716b", "#cbd2cd"
        elif theme == "custom":
            base = custom if isinstance(custom, str) and len(custom) == 7 else "#102a43"
            light = is_light(base)
            panel = mix(base, "#ffffff" if light else "#071014", .76)
            text, muted = ("#172018", "#4f5d54") if light else ("#f2f5f3", "#9fa9a4")
            border = mix(base, "#5b6b63", .55)
        else:
            # Neutral blue-black values from the desktop mock-up.  The accent is
            # deliberately kept out of the panels and appears only in controls.
            base, panel, text, muted, border = "#0b1418", "#101b20", "#f1f3f2", "#a7adaf", "#2a383d"
        accent = {"blue": "#3b82f6", "black": "#252a31", "red": "#ef3340", "green": "#3da653", "violet": "#8b5cf6", "amber": "#f59e0b", "cyan": "#06b6d4"}.get(settings.get("accent"), settings.get("accent_color", "#3da653"))
        if settings.get("plain_background"):
            gradient_start = gradient_end = base
        else:
            intensity = max(0, min(100, int(settings.get("background_intensity", 68)))) / 100
            style = settings.get("background_style", "gradient")
            start_mix, end_mix = {"gradient": (.83, .97), "mesh": (.75, .93), "soft": (.92, .985)}.get(style, (.83, .97))
            start_mix = start_mix + (1 - intensity) * (1 - start_mix)
            end_mix = end_mix + (1 - intensity) * (1 - end_mix)
            gradient_start = mix(base, accent, start_mix)
            gradient_end = mix(base, "#ffffff" if is_light(base) else "#000000", end_mix)
        tone = settings.get("text_tone", "balanced")
        if tone == "soft":
            text = mix(text, muted, .78)
        elif tone == "bold":
            text = mix(text, "#ffffff" if not is_light(base) else "#000000", .82)
        self.gradient_start, self.gradient_end = gradient_start, gradient_end
        self.bg, self.sidebar, self.panel = gradient_end, mix(panel, gradient_start, .82), panel
        self.card, self.input = mix(panel, base, .91), mix(panel, base, .73)
        self.text, self.muted, self.border, self.accent = text, muted, border, accent
        self.accent_hover = mix(accent, "#ffffff" if not is_light(accent) else "#000000", .84)
        self.accent_fg = "#07110a" if is_light(accent) else "#ffffff"
        self.selected, self.danger, self.dark = mix(panel, accent, .84), "#d85353", not is_light(base)
        if self.glass:
            self.sidebar = mix(panel, base, .60)
            self.input, self.card = mix(panel, base, .85), panel
            self.selected = mix(panel, accent, .82)


class HoverButton(RoundedButton):
    pass


class ScrollFrame(tk.Frame):
    def __init__(self, master, palette: Palette):
        super().__init__(master, bg=palette.bg)
        self.canvas = tk.Canvas(self, bg=palette.bg, highlightthickness=0, bd=0)
        self.scrollbar = SlimScrollbar(self, palette, self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=palette.bg)
        self.palette = palette
        self.gradient_photo = None
        self._background_job = None
        self.gradient_id = self.canvas.create_image(0, 0, anchor="nw")
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", self._content_changed)
        self.canvas.bind("<Configure>", self._resize)
        for widget in (self.canvas, self.inner):
            widget.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

    def _content_changed(self, _event=None):
        # The decorative background must never enlarge the scrollable region.
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), self.inner.winfo_reqheight()))
        if self._background_job is None:
            self._background_job = self.after_idle(self._draw_background)

    def wheel(self, event):
        if self.scrollbar.last-self.scrollbar.first < .999:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
            return "break"

    def _resize(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)
        self._content_changed()

    def _draw_background(self):
        self._background_job = None
        width = self.canvas.winfo_width()
        height = max(self.canvas.winfo_height(), self.inner.winfo_reqheight())
        content_height = self.inner.winfo_reqheight()
        key = (width, height, content_height)
        if getattr(self, '_background_key', None) == key:
            return
        self._background_key = key
        # Start the exposed background at the content color to avoid a seam
        # below a short collection, then fade a soft glow into the empty area.
        colors = [mix(self.palette.gradient_start, self.palette.bg,
                      .3 * math.sin(math.pi * max(0, y-content_height) / max(1, height-content_height)))
                  for y in range(height)]
        pixels = [tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) for color in colors]
        strip = Image.new("RGB", (1, height))
        strip.putdata(pixels)
        self.gradient_photo = ImageTk.PhotoImage(strip.resize((max(1, width), height)))
        self.canvas.itemconfigure(self.gradient_id, image=self.gradient_photo)
        self.canvas.tag_lower(self.gradient_id)


class BaseDialog(tk.Toplevel):
    def __init__(self, app: "SKladApp", title: str, geometry: str):
        super().__init__(app.root)
        self.withdraw()
        self._previous_grab = self.grab_current()
        self._modal_owner = self._previous_grab.winfo_toplevel() if self._previous_grab is not None else app.root
        self.app, self.p = app, app.p
        self._glass = self.p.glass
        self._palette = self.p
        self.title(title)
        self.geometry(geometry)
        self.configure(bg=self.p.panel)
        self.transient(self._modal_owner)
        self.after_idle(self._show_ready)

    def _show_ready(self):
        if self.winfo_exists():
            self.deiconify()
            enable_dark_titlebar(self, self.p.dark)
            self.lift()
            self.grab_set()
            self.focus_set()

    def destroy(self):
        previous = getattr(self, '_previous_grab', None)
        if self.grab_current() is self:
            self.grab_release()
        super().destroy()
        if previous is not None and previous.winfo_exists() and previous.winfo_viewable():
            previous.lift()
            previous.grab_set()
            previous.focus_set()

    def label(self, master, text: str, size=10, bold=False, **kwargs):
        if bold and self.app.settings.get("heading_style") == "caps":
            text = text.upper()
        return tk.Label(master, text=text, bg=kwargs.pop("bg", master.cget('bg')), fg=kwargs.pop("fg", self.p.text), font=self.app.font(size, bold=bold, heading=bold), **kwargs)

    def entry(self, master, variable=None, **kwargs):
        return RoundedEntry(master, textvariable=variable, bg=self.p.input, fg=self.p.text, insertbackground=self.p.text, highlightbackground=self.p.border, highlightcolor=self.p.accent, font=self.app.font(11), **kwargs)

    def button(self, master, text: str, command, primary=False, danger=False, **kwargs):
        normal = self.p.accent if primary else self.p.panel
        hover = self.p.accent_hover if primary else self.p.selected
        fg = self.p.accent_fg if primary else (self.p.danger if danger else self.p.text)
        padx, pady = kwargs.pop("padx", 16), kwargs.pop("pady", 10)
        return HoverButton(master, text=text, command=command, normal=normal, hover=hover, fg=fg, activeforeground=fg, relief="flat", bd=0, font=self.app.font(10, bold=primary), cursor="hand2", padx=padx, pady=pady, **kwargs)


class OverlayDialog(BaseDialog):
    """Centered, frameless modal with a dimmed application backdrop."""
    def __init__(self, app, title, geometry):
        super().__init__(app, title, geometry)
        self.modal_size = tuple(map(int, geometry.split('x')))
        self.overrideredirect(True)
        self.configure(highlightthickness=1, highlightbackground=self.p.border)
        self.backdrop = tk.Toplevel(app.root)
        self.backdrop.withdraw()
        self.backdrop.overrideredirect(True)
        self.backdrop.configure(bg='#000000')
        self.backdrop.attributes('-alpha', .48)
        self.backdrop.transient(self._modal_owner)
        # Keep an explicit owner chain so Windows never raises the dimmer over
        # its dialog when a nested popup or color picker is closed.
        self.transient(self.backdrop)
        self.bind('<Escape>', lambda _e: self.destroy())
        self._overlay_binding = app.root.bind('<Configure>', self._position_overlay, add='+')

    def _position_overlay(self, event=None):
        if event is not None and event.widget is not self.app.root:
            return
        root = self.app.root
        width, height = root.winfo_width(), root.winfo_height()
        x, y = root.winfo_rootx(), root.winfo_rooty()
        position = (width, height, x, y)
        if getattr(self, '_overlay_position', None) == position:
            return
        self._overlay_position = position
        self.backdrop.geometry(f'{width}x{height}+{x}+{y}')
        w, h = min(self.modal_size[0], width-32), min(self.modal_size[1], height-32)
        self.geometry(f'{max(300,w)}x{max(300,h)}+{x+max(0,(width-w)//2)}+{y+max(0,(height-h)//2)}')

    def _show_ready(self):
        if not self.winfo_exists():
            return
        self._position_overlay()
        self.backdrop.deiconify()
        self.backdrop.lift(self._modal_owner)
        self.deiconify()
        self.lift(self.backdrop)
        self.grab_set()
        self.focus_set()

    def choose_native_file(self, chooser, **options):
        # Windows common dialogs need a normal top-level owner, not a frameless
        # Tk window owned by a translucent backdrop. Suspend our modal grab
        # while Windows owns input, and restore it even on cancel/error.
        self.grab_release()
        self.withdraw()
        self.backdrop.withdraw()
        try:
            return chooser(parent=self.app.root, **options)
        finally:
            if self.winfo_exists():
                self._position_overlay()
                self.backdrop.deiconify()
                self.backdrop.lift(self.app.root)
                self.deiconify()
                self.lift(self.backdrop)
                self.grab_set()
                self.focus_set()

    def destroy(self):
        if getattr(self, '_overlay_binding', None):
            self.app.root.unbind('<Configure>', self._overlay_binding)
            self._overlay_binding = None
        backdrop = getattr(self, 'backdrop', None)
        super().destroy()
        if backdrop is not None and backdrop.winfo_exists():
            backdrop.destroy()


class ThemeColorDialog(BaseDialog):
    def __init__(self, owner, color):
        self.result = None
        super().__init__(owner.app, 'Выбор цвета', '460x400')
        self.transient(owner)
        self._raise_bindings = []
        for window in (owner.app.root, owner, getattr(owner, 'backdrop', None)):
            if window is not None:
                binding = window.bind('<FocusIn>', self.keep_above, add='+')
                self._raise_bindings.append((window, binding))
        self.overrideredirect(True)
        self.configure(highlightthickness=1, highlightbackground=self.p.border)
        self.geometry(f'460x400+{owner.winfo_rootx()+max(0,(owner.winfo_width()-460)//2)}+{owner.winfo_rooty()+max(0,(owner.winfo_height()-400)//2)}')
        self.label(self, 'Выбор цвета', 18, True).pack(anchor='w', padx=22, pady=18)
        self.hex_var = tk.StringVar(value=color)
        self.preview = tk.Label(self, bg=color, height=2)
        self.preview.pack(fill='x', padx=22, pady=8)
        self.entry(self, self.hex_var).pack(fill='x', padx=22, pady=8)
        self.channels = [tk.IntVar(value=int(color[i:i+2], 16)) for i in (1,3,5)]
        for label, var, channel_color in zip(('Красный', 'Зелёный', 'Синий'), self.channels, ('#ef4444', '#22c55e', '#3b82f6')):
            row = tk.Frame(self, bg=self.p.panel)
            row.pack(fill='x', padx=22, pady=4)
            self.label(row, label).pack(side='left')
            RoundedSlider(row, var, 0, 255, self.p, color=channel_color).pack(side='right')
            var.trace_add('write', self.channel_changed)
        self.hex_var.trace_add('write', self.hex_changed)
        footer = tk.Frame(self, bg=self.p.panel)
        footer.pack(fill='x', padx=22, pady=16)
        self.button(footer, 'Отмена', self.destroy).pack(side='right')
        self.button(footer, 'Выбрать', self.save, primary=True).pack(side='right', padx=8)
        self.bind('<Escape>', lambda _e: self.destroy())

    def keep_above(self, event=None):
        def raise_if_open():
            if self.winfo_exists() and self.winfo_viewable():
                self.lift()
        self.app.root.after_idle(raise_if_open)

    def destroy(self):
        for window, binding in getattr(self, '_raise_bindings', []):
            if window.winfo_exists():
                window.unbind('<FocusIn>', binding)
        self._raise_bindings = []
        super().destroy()

    def channel_changed(self, *_args):
        if getattr(self, '_changing_color', False):
            return
        self.hex_var.set('#' + ''.join(f'{var.get():02x}' for var in self.channels))

    def hex_changed(self, *_args):
        color = self.hex_var.get().strip()
        if len(color) != 7 or not color.startswith('#'):
            return
        try:
            values = [int(color[i:i+2], 16) for i in (1,3,5)]
        except ValueError:
            return
        self.preview.configure(bg=color)
        self._changing_color = True
        for var, value in zip(self.channels, values):
            var.set(value)
        self._changing_color = False

    def save(self):
        value = self.hex_var.get().strip()
        try:
            if len(value) != 7 or not value.startswith('#'):
                raise ValueError()
            int(value[1:], 16)
        except ValueError:
            messagebox.showwarning('Цвет', 'Введите цвет в формате #RRGGBB.', parent=self)
            return
        self.result = value.lower()
        self.destroy()


class PurchaseDialog(BaseDialog):
    def __init__(self, app):
        super().__init__(app, 'Полная версия СКлад', '600x540')
        self.pending_path = app.store.data_dir / 'purchase.json'
        try:
            self.pending = json.loads(self.pending_path.read_text('utf-8'))
        except (OSError, ValueError):
            self.pending = {}
        self.busy = False
        self.results = queue.Queue()
        self.email = tk.StringVar(value=self.pending.get('email', ''))
        self.code = tk.StringVar(value=self.pending.get('purchase_code', ''))
        self.info = tk.StringVar(value='До 10 карточек бесплатно. Безлимит — навсегда.\nБез подписки и автоматических списаний.')
        box = tk.Frame(self, bg=self.p.panel, padx=28, pady=24)
        box.pack(fill='both', expand=True)
        self.label(box, 'Полная версия — 299 ₽', 22, True).pack(anchor='w', pady=(0, 12))
        self.label(box, '', wraplength=530, justify='left', textvariable=self.info).pack(anchor='w', pady=(0, 18))
        self.label(box, 'Электронная почта для чека').pack(anchor='w')
        self.entry(box, self.email).pack(fill='x', pady=(6, 12))
        self.button(box, 'Купить за 299 ₽', self.buy, primary=True).pack(fill='x')
        self.label(box, 'Код покупки — сохраните для восстановления', size=9).pack(anchor='w', pady=(20, 4))
        self.entry(box, self.code).pack(fill='x', pady=(0, 10))
        self.button(box, 'Проверить оплату / восстановить', self.check).pack(fill='x')
        row = tk.Frame(box, bg=self.p.panel)
        row.pack(fill='x', pady=12)
        self.button(row, 'Загрузить лицензию', self.import_license).pack(side='left')
        self.button(row, 'Сохранить лицензию', self.export_license).pack(side='right')
        self.button(box, 'Закрыть', self.destroy).pack(anchor='e')
        if app.store.is_licensed():
            self.info.set('Полная версия активирована. Лимита карточек нет.\nСохраните лицензию для переноса или переустановки.')

    def run(self, endpoint, data):
        if self.busy:
            return
        self.busy = True
        self.info.set('Связываемся с сервером…')
        def worker():
            try:
                self.results.put((licensing.request(endpoint, data), None))
            except Exception as exc:
                self.results.put((None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self.poll)

    def poll(self):
        try:
            result, error = self.results.get_nowait()
        except queue.Empty:
            self.after(100, self.poll)
            return
        self.busy = False
        if error:
            self.info.set(error)
            return
        if result.get('license'):
            try:
                licensing.activate(result['license'], self.app.store.data_dir, self.app.store.bundled_assets)
            except (ValueError, OSError) as exc:
                self.info.set(str(exc))
                return
            self.info.set('Полная версия активирована навсегда. Спасибо!\nСохраните лицензию для переустановки.')
            self.app.refresh()
        elif result.get('checkout_url'):
            url = result['checkout_url']
            if not licensing.safe_checkout(url):
                self.info.set('Сервер вернул неизвестный адрес оплаты.')
                return
            webbrowser.open(url)
            self.info.set('Оплатите в открывшемся браузере, затем нажмите\n«Проверить оплату». Повторно платить не нужно.')
        elif result.get('status') == 'canceled':
            self.pending = {}
            self.code.set('')
            licensing.save_json(self.pending_path, {})
            self.info.set('Оплата отменена. При желании можно начать новую покупку.')
        else:
            self.info.set('Подтверждение ещё не получено.\nПосле оплаты повторите проверку через несколько секунд.')

    def buy(self):
        if self.busy:
            return
        if self.app.store.is_licensed():
            self.info.set('Полная версия уже активирована. Повторная покупка не нужна.')
            return
        email = self.email.get().strip()
        if '@' not in email or len(email) > 254:
            self.info.set('Введите электронную почту для чека.')
            return
        # Persist before networking: retries reuse the same idempotent order.
        self.pending = {'email': email,
                        'purchase_code': self.pending.get('purchase_code') or str(uuid.uuid4())}
        self.email.set(self.pending['email'])
        self.code.set(self.pending['purchase_code'])
        licensing.save_json(self.pending_path, self.pending)
        self.run('purchase', self.pending)

    def check(self):
        try:
            code = str(uuid.UUID(self.code.get().strip()))
        except ValueError:
            self.info.set('Сначала начните покупку или вставьте сохранённый код.')
            return
        self.run('status', {'purchase_code': code})

    def import_license(self):
        path = filedialog.askopenfilename(parent=self, title='Открыть лицензию', filetypes=[('Лицензия СКлад', '*.json')])
        if not path:
            return
        try:
            licensing.activate(json.loads(Path(path).read_text('utf-8')), self.app.store.data_dir, self.app.store.bundled_assets)
            self.info.set('Полная версия активирована навсегда.')
            self.app.refresh()
        except (OSError, ValueError) as exc:
            messagebox.showerror('Лицензия', str(exc), parent=self)

    def export_license(self):
        if not self.app.store.is_licensed():
            self.info.set('Сначала активируйте полную версию.')
            return
        path = filedialog.asksaveasfilename(parent=self, initialfile='SKlad-license.json', defaultextension='.json', filetypes=[('Лицензия СКлад', '*.json')])
        if path:
            try:
                licensing.save_json(path, json.loads((self.app.store.data_dir / 'license.json').read_text('utf-8')))
            except OSError as exc:
                messagebox.showerror('Лицензия', str(exc), parent=self)


class ListOptionsDialog(BaseDialog):
    def __init__(self, owner, options=None):
        self.result = None
        self.option_vars = []
        super().__init__(owner.app, 'Пункты списка', '500x460')
        self.transient(owner)
        self.label(self, 'Пункты списка', 18, True).pack(anchor='w', padx=24, pady=18)
        scroll = ScrollFrame(self, self.p)
        scroll.pack(fill='both', expand=True, padx=24)
        self.options_box = scroll.inner
        self.add_button = self.button(self.options_box, 'Добавить', self.add_option)
        self.add_button.pack(fill='x', pady=8)
        for value in options if options is not None else ['', '', '']:
            self.add_option(value)
        footer = tk.Frame(self, bg=self.p.panel)
        footer.pack(fill='x', padx=24, pady=18)
        self.button(footer, 'Отмена', self.destroy).pack(side='right')
        self.button(footer, 'Сохранить', self.save, primary=True).pack(side='right', padx=8)

    def add_option(self, value=''):
        var = tk.StringVar(value=value)
        self.option_vars.append(var)
        row = tk.Frame(self.options_box, bg=self.p.panel)
        row.pack(fill='x', pady=4, before=self.add_button)
        self.entry(row, var).pack(side='left', fill='x', expand=True)
        def remove():
            self.option_vars.remove(var)
            row.destroy()
        self.button(row, 'Удалить', remove, danger=True, padx=8).pack(side='right', padx=(6, 0))

    def save(self):
        values = [var.get().strip() for var in self.option_vars if var.get().strip()]
        if not values:
            messagebox.showwarning('Список', 'Введите хотя бы один пункт.', parent=self)
            return
        if len({value.casefold() for value in values}) != len(values):
            messagebox.showwarning('Список', 'Пункты не должны повторяться.', parent=self)
            return
        self.result = values
        self.destroy()


class RubricDialog(BaseDialog):
    def __init__(self, app: "SKladApp", rubric: dict | None = None):
        self.rubric = rubric
        self.result = False
        self.fields = deepcopy(rubric.get("fields", DEFAULT_FIELDS) if rubric else DEFAULT_FIELDS)
        self.icon_file = rubric.get("icon", "collection_box.png") if rubric else "collection_box.png"
        super().__init__(app, "Настройка полей рубрики", "760x720")
        self.minsize(680, 620)
        self._build()

    def _build(self):
        header = tk.Frame(self, bg=self.p.panel, padx=26, pady=20)
        header.pack(fill="x")
        self.label(header, "Настройка полей рубрики", 20, True).pack(side="left")
        self.name_var = tk.StringVar(value=self.rubric.get("name", "") if self.rubric else "")
        form = tk.Frame(self, bg=self.p.panel, padx=26)
        form.pack(fill="x")
        self.label(form, "Название рубрики", fg=self.p.muted).grid(row=0, column=0, sticky="w", pady=(0, 5))
        name = self.entry(form, self.name_var)
        name.grid(row=1, column=0, sticky="ew", ipady=8, padx=(0, 12))
        form.grid_columnconfigure(0, weight=1)
        intro = tk.Frame(self, bg=self.p.panel, padx=26)
        intro.pack(fill="x", pady=(20, 10))
        self.label(intro, "Поля карточки", 12, True).pack(side="left")
        self.label(intro, "Включайте, меняйте порядок и добавляйте свои поля", 9, fg=self.p.muted).pack(side="right")
        self.field_scroll = ScrollFrame(self, self.p)
        self.field_scroll.canvas.configure(bg=self.p.panel)
        self.field_scroll.inner.configure(bg=self.p.panel)
        self.field_scroll.pack(fill="both", expand=True, padx=26)
        self.rows = tk.Frame(self.field_scroll.inner, bg=self.p.panel)
        self.rows.pack(fill="both", expand=True)
        sources = [r["name"] for r in self.app.store.data["rubrics"] if not self.rubric or r["id"] != self.rubric["id"]]
        if sources:
            copy_row = tk.Frame(self, bg=self.p.panel, padx=26)
            copy_row.pack(fill="x", pady=(10, 0))
            self.copy_var = tk.StringVar(value=sources[0])
            self.label(copy_row, "Скопировать набор полей из другой рубрики", 9, fg=self.p.muted).pack(side="left")
            self.button(copy_row, "Копировать", self.copy_fields, padx=12, pady=7).pack(side="right")
            RoundedCombo(copy_row, textvariable=self.copy_var, values=sources, state="readonly", width=18).pack(side="right", padx=8)
        add = tk.Frame(self, bg=self.p.panel, padx=26, pady=12)
        add.pack(fill="x")
        self.new_field = tk.StringVar()
        self.new_field_entry = self.entry(add, self.new_field)
        self.new_field_entry.pack(side="left", fill="x", expand=True, ipady=8)
        self.new_field_entry.editor.bind('<Return>', lambda _e: self.add_field())
        self.new_type = tk.StringVar(value="Обычное")
        RoundedCombo(add, textvariable=self.new_type, values=["Обычное", "Многострочное", "Список"], state="readonly", width=15).pack(side="left", padx=8)
        self.add_field_button = self.button(add, "Добавить поле", self.add_field)
        self.add_field_button.pack(side="left")
        footer = tk.Frame(self, bg=self.p.panel, padx=26, pady=18)
        footer.pack(fill="x")
        if self.rubric:
            self.button(footer, "Удалить рубрику", self.delete, danger=True).pack(side="left")
        self.button(footer, "Отмена", self.destroy).pack(side="right")
        self.button(footer, "Сохранить", self.save, primary=True).pack(side="right", padx=8)
        self.render_fields()
        name.focus_set()

    def render_fields(self):
        for child in self.rows.winfo_children():
            child.destroy()
        self.field_rows = []
        for index, field in enumerate(self.fields):
            row = RoundedPanel(self.rows, bg=self.p.input, highlightbackground=self.p.border, padx=4, pady=2)
            row.pack(fill="x", pady=4)
            self.field_rows.append(row)
            enabled = tk.BooleanVar(value=field.get("enabled", True))
            field["_enabled_var"] = enabled
            tk.Checkbutton(row, variable=enabled, bg=self.p.input, activebackground=self.p.input, selectcolor=self.p.panel, fg=self.p.text).pack(side="left")
            text = tk.Frame(row, bg=self.p.input)
            text.pack(side="left", fill="x", expand=True, padx=8)
            self.label(text, field["label"], 10, True, bg=self.p.input).pack(anchor="w")
            kind = f'Список · {len(field.get("options", []))} пунктов' if field['type'] == 'select' else "Изображения" if field["type"] == "image" else "Многострочное" if field["type"] == "textarea" else "Обычное поле"
            self.label(text, kind, 8, bg=self.p.input, fg=self.p.muted).pack(anchor="w")
            if not field.get("required"):
                self.button(row, "Удалить", lambda i=index: self.remove_field(i), danger=True, padx=9, pady=5).pack(side="right")
            if field['type'] == 'select':
                self.button(row, 'Пункты…', lambda i=index: self.edit_options(i), padx=9, pady=5).pack(side='right')
            handle = tk.Canvas(row, width=34, height=40, bg=self.p.input, bd=0, highlightthickness=0, cursor='hand2', takefocus=1)
            handle.pack(side='right', padx=5)
            def draw_handle(event=None, control=handle):
                from surfaces import surface
                control._photo = surface(34, 40, self.p.panel, self.p.border, 10, self.p.glass)
                control.delete('all')
                control.create_image(0, 0, image=control._photo, anchor='nw')
                control.create_line(11, 15, 17, 9, 23, 15, fill=self.p.text, width=2, capstyle='round', joinstyle='round')
                control.create_line(11, 25, 17, 31, 23, 25, fill=self.p.text, width=2, capstyle='round', joinstyle='round')
            handle.bind('<Configure>', draw_handle)
            handle.bind('<ButtonPress-1>', lambda e, i=index: self.start_field_drag(e, i))
            handle.bind('<B1-Motion>', self.drag_field)
            handle.bind('<ButtonRelease-1>', self.finish_field_drag)
            handle.bind('<Up>', lambda e, i=index: self.move_field(i, -1))
            handle.bind('<Down>', lambda e, i=index: self.move_field(i, 1))
            # Labels and unused row space are also drag handles; form controls are not.
            for widget in [row, text, *text.winfo_children()]:
                widget.bind('<ButtonPress-1>', lambda e, i=index: self.start_field_drag(e, i, False))
                widget.bind('<B1-Motion>', self.drag_field)
                widget.bind('<ButtonRelease-1>', self.finish_field_drag)

    def start_field_drag(self, event, index, clickable=True):
        row = self.field_rows[index].shell
        self._field_drag = {'index': index, 'target': index, 'start': event.y_root,
                            'moving': False, 'clickable': clickable,
                            'widget': event.widget, 'cursor': event.widget.cget('cursor'),
                            'offset_x': getattr(event, 'x_root', row.winfo_rootx()) - row.winfo_rootx(),
                            'offset_y': event.y_root - row.winfo_rooty(),
                            'step': -1 if event.y < event.widget.winfo_height() / 2 else 1}
        self._field_drag['escape'] = self.bind('<Escape>', self.cancel_field_drag, add='+')

    def create_field_ghost(self, state):
        from surfaces import surface
        row = self.field_rows[state['index']].shell
        field = self.fields[state['index']]
        width, height = row.winfo_width(), row.winfo_height()
        # A separate composited window avoids moving a child HWND over sibling
        # canvases (which leaves stale backing-store fragments on Windows).
        window = tk.Toplevel(self)
        window.withdraw()
        window.overrideredirect(True)
        window.transient(self)
        if os.name == 'nt':
            window.attributes('-disabled', True)
            window.attributes('-toolwindow', True)
        window.configure(bg=self.p.panel)
        window.geometry(f'{width}x{height}')
        ghost = tk.Canvas(window, width=width, height=height, bg=self.p.panel,
                          bd=0, highlightthickness=0, cursor='fleur')
        ghost.pack()
        ghost._photo = surface(width, height, self.p.selected, self.p.accent, 14, self.p.glass)
        ghost.create_image(0, 0, image=ghost._photo, anchor='nw')
        variable = field.get('_enabled_var')
        enabled = variable.get() if variable is not None else field.get('enabled', True)
        ghost.create_text(24, height/2, text='☑' if enabled else '☐', fill=self.p.text, font=self.app.font(10))
        ghost.create_text(46, height/2-10, text=field['label'], anchor='w', fill=self.p.text, font=self.app.font(10, bold=True))
        kind = 'Изображения' if field['type'] == 'image' else 'Многострочное' if field['type'] == 'textarea' else 'Обычное поле'
        ghost.create_text(46, height/2+10, text=kind, anchor='w', fill=self.p.muted, font=self.app.font(8))
        handle_x = width - (110 if not field.get('required') else 32)
        for sign in (-1, 1):
            center = height/2 + sign*9
            ghost.create_line(handle_x-6, center-sign*3, handle_x, center+sign*3,
                              handle_x+6, center-sign*3, fill=self.p.text, width=2)
        if not field.get('required'):
            ghost.create_text(width-46, height/2, text='Удалить', fill=self.p.danger, font=self.app.font(9))
        state['ghost'] = window
        state['highlighted'] = None
        state['widget'].configure(cursor='fleur')

    def clear_field_drag(self, state):
        if state.get('ghost') is not None:
            state['ghost'].destroy()
        if state['widget'].winfo_exists():
            state['widget'].configure(cursor=state['cursor'])
        self.unbind('<Escape>', state['escape'])

    def cancel_field_drag(self, event=None):
        state = getattr(self, '_field_drag', None)
        self._field_drag = None
        if state:
            self.clear_field_drag(state)
            self._sync_enabled()
            self.render_fields()
        return 'break'

    def drag_field(self, event):
        state = getattr(self, '_field_drag', None)
        if not state or abs(event.y_root - state['start']) < 5 and not state['moving']:
            return
        if not state['moving']:
            self.create_field_ghost(state)
            state['moving'] = True
        ghost = state['ghost']
        row = self.field_rows[state['index']].shell
        x = getattr(event, 'x_root', row.winfo_rootx() + state['offset_x']) - state['offset_x']
        y = event.y_root - state['offset_y']
        ghost.geometry(f'+{max(0, x)}+{max(0, y)}')
        if not ghost.winfo_ismapped():
            ghost.deiconify()
            ghost.lift()
        canvas = self.field_scroll.canvas
        if event.y_root < canvas.winfo_rooty() + 24:
            canvas.yview_scroll(-1, 'units')
        elif event.y_root > canvas.winfo_rooty() + canvas.winfo_height() - 24:
            canvas.yview_scroll(1, 'units')
        state['target'] = min(range(len(self.field_rows)), key=lambda i: abs(
            event.y_root - self.field_rows[i].shell.winfo_rooty() - self.field_rows[i].shell.winfo_height() / 2))
        if state['highlighted'] != state['target']:
            from types import SimpleNamespace
            for i in (state['highlighted'], state['target']):
                if i is None:
                    continue
                row = self.field_rows[i]
                row.edge = self.p.accent if i == state['target'] else self.p.border
                row._resize(SimpleNamespace(width=row.shell.winfo_width(), height=row.shell.winfo_height()))
            state['highlighted'] = state['target']

    def finish_field_drag(self, event):
        state = getattr(self, '_field_drag', None)
        self._field_drag = None
        if not state:
            return
        self.clear_field_drag(state)
        if state['moving']:
            self._sync_enabled()
            field = self.fields.pop(state['index'])
            self.fields.insert(state['target'], field)
            self.render_fields()
        elif state['clickable']:
            self.move_field(state['index'], state['step'])

    def _sync_enabled(self):
        for field in self.fields:
            variable = field.pop("_enabled_var", None)
            if variable is not None:
                field["enabled"] = bool(variable.get())

    def move_field(self, index: int, step: int):
        new = index + step
        if 0 <= new < len(self.fields):
            self._sync_enabled()
            self.fields[index], self.fields[new] = self.fields[new], self.fields[index]
            self.render_fields()

    def remove_field(self, index: int):
        self._sync_enabled()
        self.fields.pop(index)
        self.render_fields()

    def add_field(self):
        name = self.new_field.get().strip()
        if not name:
            return
        if any(field["label"].casefold() == name.casefold() for field in self.fields):
            messagebox.showwarning("Поле", "Поле с таким названием уже существует", parent=self)
            return
        field = {"id": f"custom_{os.urandom(6).hex()}", "label": name, "type": {'Многострочное': 'textarea', 'Список': 'select'}.get(self.new_type.get(), 'text'), "enabled": True, "custom": True}
        if field['type'] == 'select':
            dialog = ListOptionsDialog(self)
            self.wait_window(dialog)
            self.grab_set()
            if dialog.result is None:
                return
            field['options'] = dialog.result
        self._sync_enabled()
        self.fields.append(field)
        self.new_field.set("")
        self.render_fields()
        self.field_scroll.canvas.yview_moveto(1)

    def edit_options(self, index):
        dialog = ListOptionsDialog(self, self.fields[index].get('options', []))
        self.wait_window(dialog)
        self.grab_set()
        if dialog.result is not None:
            self._sync_enabled()
            self.fields[index]['options'] = dialog.result
            self.render_fields()

    def copy_fields(self):
        source = next((r for r in self.app.store.data["rubrics"] if r["name"] == self.copy_var.get()), None)
        if source:
            self._sync_enabled()
            self.fields = deepcopy(source.get("fields", DEFAULT_FIELDS))
            self.render_fields()

    def save(self):
        self._sync_enabled()
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Рубрика", "Введите название рубрики", parent=self)
            return
        try:
            if self.rubric:
                self.app.store.update_rubric(self.rubric["id"], name, self.icon_file, self.fields)
            else:
                rubric = self.app.store.add_rubric(name)
                self.app.store.update_rubric(rubric["id"], name, self.icon_file, self.fields)
                self.app.selected_rubric = rubric["id"]
        except ValueError as exc:
            messagebox.showwarning("Рубрика", str(exc), parent=self)
            return
        self.result = True
        self.destroy()

    def delete(self):
        if not messagebox.askyesno("Удалить рубрику", f"Удалить «{self.rubric['name']}»?", parent=self):
            return
        try:
            self.app.store.delete_rubric(self.rubric["id"])
        except ValueError as exc:
            messagebox.showwarning("Рубрика", str(exc), parent=self)
            return
        self.app.selected_rubric = "all"
        self.result = True
        self.destroy()


class CardDialog(OverlayDialog):
    def __init__(self, app: "SKladApp", card: dict | None = None, rubric_id: str | None = None):
        self.card = card
        self.result = False
        self.image_paths = list(card.get("images", [])) if card else []
        self.images_dirty = False
        self.value_vars: dict[str, tk.StringVar] = {}
        super().__init__(app, "Редактировать карточку" if card else "Добавить карточку", "720x780")
        self.minsize(620, 660)
        current = card.get("rubric_id") if card else rubric_id
        rubric = app.store.rubric(current or "") or (app.store.data["rubrics"][0] if app.store.data["rubrics"] else None)
        self.rubric_var = tk.StringVar(value=rubric["name"] if rubric else "")
        self.available_rubrics = list(app.store.data['rubrics'])
        if card and rubric and rubric not in self.available_rubrics:
            self.available_rubrics.insert(0, rubric)
        self._build()

    def _build(self):
        header = tk.Frame(self, bg=self.p.panel, padx=26, pady=20)
        header.pack(fill="x")
        self.label(header, "Редактировать карточку" if self.card else "Новая карточка", 20, True).pack(side="left")
        selector = tk.Frame(self, bg=self.p.panel, padx=26)
        selector.pack(fill="x")
        self.label(selector, "Рубрика", fg=self.p.muted).grid(row=0, column=0, sticky="w")
        names = [r["name"] for r in self.available_rubrics]
        rubric_combo = RoundedCombo(selector, textvariable=self.rubric_var, values=names, state="readonly")
        rubric_combo.grid(row=1, column=0, sticky="ew", ipady=6)
        rubric_combo.bind("<<ComboboxSelected>>", lambda _e: self.render_fields())
        selector.grid_columnconfigure(0, weight=1)
        self.form_scroll = ScrollFrame(self, self.p)
        self.form_scroll.canvas.configure(bg=self.p.panel)
        self.form_scroll.inner.configure(bg=self.p.panel)
        self.form_scroll.pack(fill="both", expand=True, padx=26, pady=16)
        self.form = tk.Frame(self.form_scroll.inner, bg=self.p.panel)
        self.form.pack(fill="both", expand=True)
        footer = tk.Frame(self, bg=self.p.panel, padx=26, pady=18)
        footer.pack(fill="x")
        self.button(footer, "Отмена", self.destroy).pack(side="right")
        self.button(footer, "Сохранить", self.save, primary=True).pack(side="right", padx=8)
        self.render_fields()

    def current_rubric(self):
        return next((r for r in self.available_rubrics if r["name"] == self.rubric_var.get()), None)

    def render_fields(self):
        self.sync_text_fields()
        previous = {key: variable.get() for key, variable in self.value_vars.items()}
        self.value_vars.clear()
        self.text_fields = {}
        for child in self.form.winfo_children():
            child.destroy()
        rubric = self.current_rubric()
        if not rubric:
            return
        source = (self.card or {}).get("values", {})
        row = 0
        for field in rubric.get("fields", DEFAULT_FIELDS):
            if not field.get("enabled", True):
                continue
            if field["type"] == "image":
                self.label(self.form, "Фото — до 5 изображений", fg=self.p.muted).grid(row=row, column=0, sticky="w", pady=(0, 6))
                controls = tk.Frame(self.form, bg=self.p.panel)
                controls.grid(row=row + 1, column=0, sticky="ew", pady=(0, 14))
                self.image_previews = []
                for index, path in enumerate(self.image_paths):
                    item = tk.Frame(controls, bg=self.p.panel, padx=4, pady=4)
                    item.grid(row=index//3, column=index%3, sticky='nw')
                    photo = self.app.photo(self.app.store.resolve_image(path) or resource_path('assets/no-photo.png'), (140, 90))
                    self.image_previews.append(photo)
                    tk.Label(item, image=photo, bg=self.p.input).pack()
                    self.label(item, 'Главное фото' if index == 0 else f'Фото {index+1}', 9, fg=self.p.accent if index == 0 else self.p.muted).pack(pady=3)
                    actions = tk.Frame(item, bg=self.p.panel)
                    actions.pack()
                    self.button(actions, '←', lambda i=index: self.move_image(i, -1), padx=7, pady=4).pack(side='left')
                    self.button(actions, '→', lambda i=index: self.move_image(i, 1), padx=7, pady=4).pack(side='left')
                    self.button(actions, '×', lambda i=index: self.remove_image(i), danger=True, padx=7, pady=4).pack(side='left')
                    self.button(item, 'Заменить', lambda i=index: self.replace_image(i), padx=10, pady=4).pack(fill='x', pady=3)
                self.button(controls, 'Добавить фото', self.add_images, padx=12, pady=7).grid(row=(len(self.image_paths)+2)//3, column=0, columnspan=3, sticky='w', pady=8)
                row += 2
                continue
            value = previous.get(field["id"], source.get(field["id"], ""))
            variable = tk.StringVar(value=value)
            self.value_vars[field["id"]] = variable
            self.label(self.form, field["label"], fg=self.p.muted).grid(row=row, column=0, sticky="w", pady=(0, 5))
            if field['type'] == 'select':
                options = list(field.get('options', []))
                if value and value not in options:
                    options.insert(0, value)  # Preserve older selections after options are edited.
                RoundedCombo(self.form, textvariable=variable, values=[''] + options, state='readonly').grid(row=row + 1, column=0, sticky='ew', pady=(0, 13))
            elif field["type"] == "textarea":
                text = tk.Text(self.form, height=4, bg=self.p.input, fg=self.p.text, insertbackground=self.p.text, relief="flat", highlightthickness=self.app.focus_width, highlightbackground=self.p.border, highlightcolor=self.p.accent, wrap="word", font=self.app.font(10))
                text.insert("1.0", value)
                self.text_fields[field['id']] = text
                text.bind("<KeyRelease>", lambda _e, v=variable, w=text: v.set(w.get("1.0", "end-1c")))
                text.grid(row=row + 1, column=0, sticky="ew", pady=(0, 13))
            else:
                self.entry(self.form, variable).grid(row=row + 1, column=0, sticky="ew", ipady=8, pady=(0, 13))
            row += 2
        self.form.grid_columnconfigure(0, weight=1)

    def sync_text_fields(self):
        # Read the widget itself, including paste/undo changes without KeyRelease.
        for key, widget in getattr(self, 'text_fields', {}).items():
            if widget.winfo_exists() and key in self.value_vars:
                self.value_vars[key].set(widget.get('1.0', 'end-1c'))

    def add_images(self):
        remaining = 5 - len(self.image_paths)
        if remaining <= 0:
            messagebox.showinfo("Фото", "Можно добавить не более 5 изображений", parent=self)
            return
        paths = self.choose_native_file(filedialog.askopenfilenames, title="Выберите изображения", filetypes=[("Изображения", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Все файлы", "*.*")])
        for path in paths[:remaining]:
            self.image_paths.append(path)
        if paths:
            self.images_dirty = True
            self.render_fields()

    def move_image(self, index, step):
        target = index + step
        if 0 <= target < len(self.image_paths):
            self.image_paths[index], self.image_paths[target] = self.image_paths[target], self.image_paths[index]
            self.images_dirty = True
            self.render_fields()

    def replace_image(self, index):
        path = self.choose_native_file(filedialog.askopenfilename, title='Заменить фото', filetypes=[('Изображения', '*.png *.jpg *.jpeg *.webp *.bmp')])
        if path:
            self.image_paths[index] = path
            self.images_dirty = True
            self.app.photo_cache.clear()
            self.render_fields()

    def remove_image(self, index):
        self.image_paths.pop(index)
        self.images_dirty = True
        self.render_fields()

    def save(self):
        rubric = self.current_rubric()
        if not rubric:
            return
        self.sync_text_fields()
        values = dict((self.card or {}).get("values", {}))
        values.update({key: value.get().strip() for key, value in self.value_vars.items()})
        if not values.get("title"):
            messagebox.showwarning("Карточка", "Введите наименование", parent=self)
            return
        try:
            if self.card:
                self.app.store.update_card(self.card["id"], rubric["id"], values, self.image_paths if self.images_dirty else None, self.card.get('status', 'keep'))
            else:
                self.app.store.add_card(rubric["id"], values, self.image_paths)
        except ValueError as exc:
            messagebox.showinfo('Карточка', str(exc), parent=self)
            return
        except OSError as exc:
            messagebox.showerror('Не удалось сохранить', f'Проверьте доступ к файлам и свободное место на диске.\n{exc}', parent=self)
            return
        self.result = True
        self.destroy()


class CardViewDialog(BaseDialog):
    def __init__(self, app: "SKladApp", card: dict):
        self.card, self.index, self.photo_ref = card, 0, None
        super().__init__(app, card.get("values", {}).get("title", "Карточка"), "1040x700")
        self.overrideredirect(True)
        self.configure(bg="#010203")
        if os.name == "nt":
            self.attributes('-transparentcolor', '#010203')
        self.backdrop = tk.Toplevel(app.root)
        self.backdrop.overrideredirect(True)
        self.backdrop.configure(bg='#000000')
        self.backdrop.attributes('-alpha', .48)
        self.backdrop.transient(app.root)
        self.backdrop.bind('<Button-1>', lambda e: self.destroy())
        self.bind('<Escape>', lambda e: self.destroy())
        self.bind('<Button-1>', self._outside)
        self.bind('<Left>', lambda e: self.previous())
        self.bind('<Right>', lambda e: self.next())
        self._parent_binding = app.root.bind('<Configure>', self._position, add='+')
        self._build()
        self._position()
        self.lift()
        self.grab_set()
        self.focus_set()

    def _outside(self, event):
        if not (self.winfo_rootx() <= event.x_root < self.winfo_rootx()+self.winfo_width()
                and self.winfo_rooty() <= event.y_root < self.winfo_rooty()+self.winfo_height()):
            self.destroy()

    def _position(self, event=None):
        if event is not None and event.widget is not self.app.root:
            return
        root = self.app.root
        width, height = root.winfo_width(), root.winfo_height()
        x, y = root.winfo_rootx(), root.winfo_rooty()
        position = (width, height, x, y)
        if getattr(self, '_last_position', None) == position:
            return
        self._last_position = position
        self.backdrop.geometry(f'{width}x{height}+{x}+{y}')
        self.backdrop.lift(root)
        w, h = min(1100, width-48), min(790, height-48)
        self.geometry(f'{w}x{h}+{x+(width-w)//2}+{y+(height-h)//2}')
        self.lift(self.backdrop)

    def destroy(self):
        if hasattr(self, '_parent_binding'):
            self.app.root.unbind('<Configure>', self._parent_binding)
            self._parent_binding = None
        if hasattr(self, 'backdrop') and self.backdrop.winfo_exists():
            self.backdrop.destroy()
        super().destroy()

    def _build(self):
        outer = RoundedPanel(self, bg=self.p.panel, highlightbackground=self.p.border, padx=14, pady=14)
        outer.pack(fill="both", expand=True)
        # The modal fills its allocated height, while ordinary panels size to contents.
        outer.shell.bind('<Configure>', lambda e: outer.shell.itemconfigure(outer._content, height=max(1, e.height-20)), add='+')
        outer.grid_columnconfigure(0, weight=3)
        outer.grid_columnconfigure(1, weight=2)
        outer.grid_rowconfigure(0, weight=1)
        left = tk.Frame(outer, bg=self.p.panel)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 22))
        self.image_label = tk.Label(left, bg=self.p.panel)
        self.image_label.pack(fill="both", expand=True, padx=16, pady=16)
        nav = tk.Frame(left, bg=self.p.panel)
        nav.pack(fill="x", padx=16, pady=(0, 14))
        self.button(nav, "Назад", self.previous, padx=14, pady=6).pack(side="left")
        self.counter = self.label(nav, "", 9, bg=self.p.panel, fg=self.p.muted)
        self.counter.pack(side="left", expand=True)
        self.button(nav, "Далее", self.next, padx=14, pady=6).pack(side="right")
        thumbs = tk.Frame(left, bg=self.p.panel)
        thumbs.pack(fill='x', padx=16, pady=(0, 10))
        for index, path in enumerate(self.card.get('images', [])):
            photo = self.app.photo(self.app.store.resolve_image(path) or resource_path('assets/no-photo.png'), (56, 48))
            tk.Button(thumbs, image=photo, command=lambda i=index: self.select_image(i), bg=self.p.panel, activebackground=self.p.selected, bd=0, relief='flat').pack(side='left', padx=4)
        right = tk.Frame(outer, bg=self.p.panel)
        right.grid(row=0, column=1, sticky="nsew")
        values = self.card.get("values", {})
        self.label(right, values.get("title", "Без названия"), 22, True, wraplength=380, justify="left").pack(anchor="w")
        rubric = self.app.store.rubric(self.card["rubric_id"])
        self.label(right, rubric['name'] if rubric else 'Без рубрики', 10, fg=self.p.accent).pack(anchor="w", pady=(9, 22))
        details = ScrollFrame(right, self.p)
        details.canvas.configure(bg=self.p.panel)
        details.inner.configure(bg=self.p.panel)
        details.palette = deepcopy(self.p)
        details.palette.bg = details.palette.gradient_start = details.palette.gradient_end = self.p.panel
        details.pack(fill="both", expand=True)
        known = set()
        for field in (rubric or {}).get("fields", []):
            if field["type"] == "image" or not field.get("enabled", True) or field["id"] == "title":
                continue
            known.add(field["id"])
            self._detail(details.inner, field["label"], values.get(field["id"], ""))
        for key, value in values.items():
            if key not in known and key != "title" and value:
                self._detail(details.inner, {"year": "Год"}.get(key, key.capitalize()), value)
        actions = tk.Frame(right, bg=self.p.panel)
        actions.pack(fill="x", pady=(18, 0))
        self.button(actions, "Удалить", self.delete, danger=True).pack(side="left")
        self.button(actions, "Закрыть", self.destroy).pack(side="right")
        self.button(actions, "Редактировать", self.edit, primary=True).pack(side="right", padx=8)
        self.show_image()
        self.image_label.bind('<Configure>', lambda e: self.show_image())

    def select_image(self, index):
        self.index = index
        self.show_image()

    def _detail(self, master, label, value):
        display = value or ("—" if self.app.settings.get("empty_fields") == "dash" else "")
        if not display and self.app.settings.get("empty_fields") == "hide":
            return
        box = tk.Frame(master, bg=self.p.panel, pady=7)
        box.pack(fill="x")
        self.label(box, label, 9, fg=self.p.muted).pack(anchor="w")
        self.label(box, display, 11, wraplength=370, justify="left").pack(anchor="w", pady=(3, 0))

    def show_image(self):
        images = self.card.get("images", [])
        if not images or self.app.settings.get("thumbnails") == "hidden":
            path, total = resource_path("assets/no-photo.png"), 0
        else:
            self.index %= len(images)
            path = self.app.store.resolve_image(images[self.index]) or resource_path("assets/no-photo.png")
            total = len(images)
        width, height = self.image_label.winfo_width(), self.image_label.winfo_height()
        width, height = (max(80, width-12), max(80, height-12)) if width > 20 else (430, 420)
        # A fixed requested size prevents the image resize from growing the modal.
        self.image_label.configure(width=1, height=1)
        canvas = Image.new('RGBA', (width, height), self.p.panel)
        try:
            with Image.open(path) as source:
                photo = source.convert('RGBA')
                photo.thumbnail((width, height), Image.Resampling.LANCZOS)
                canvas.alpha_composite(photo, ((width-photo.width)//2, (height-photo.height)//2))
        except OSError:
            pass
        self.photo_ref = ImageTk.PhotoImage(canvas)
        self.image_label.configure(image=self.photo_ref)
        self.counter.configure(text=f"{self.index + 1} / {total}" if total else "Нет изображения")

    def previous(self):
        self.index -= 1
        self.show_image()

    def next(self):
        self.index += 1
        self.show_image()

    def edit(self):
        self.grab_release()
        self.withdraw()
        self.backdrop.withdraw()
        dialog = CardDialog(self.app, self.card)
        self.wait_window(dialog)
        if dialog.result:
            self.destroy()
            self.app.refresh()
        else:
            self.backdrop.deiconify()
            self.deiconify()
            self.lift(self.backdrop)
            self.grab_set()
            self.focus_set()

    def delete(self):
        title = self.card.get("values", {}).get("title", "карточку")
        if messagebox.askyesno("Удалить карточку", f"Удалить «{title}»?", parent=self):
            self.app.store.delete_card(self.card["id"])
            self.destroy()
            self.app.refresh()


class ExportDialog(BaseDialog):
    def __init__(self, app):
        super().__init__(app, 'Экспорт коллекции', '580x350')
        self.scope = tk.StringVar(value='Текущий список (рубрика и поиск)')
        self.kind = tk.StringVar(value='PDF')
        content = tk.Frame(self, bg=self.p.panel, padx=28, pady=24)
        content.pack(fill='both', expand=True)
        self.label(content, 'Экспорт коллекции', 20, True).pack(anchor='w', pady=(0, 18))
        RoundedCombo(content, textvariable=self.scope, values=['Текущий список (рубрика и поиск)', 'Весь архив'], width=40).pack(fill='x', pady=6)
        RoundedCombo(content, textvariable=self.kind, values=['PDF', 'Excel (.xlsx)'], width=40).pack(fill='x', pady=6)
        self.label(content, 'PDF — изображения и поля. Excel — таблица полей и пути к фото.', 9, fg=self.p.muted, wraplength=490).pack(anchor='w', pady=12)
        self.button(content, 'Сохранить файл', self.save_export, primary=True).pack(side='right', pady=8)
        self.button(content, 'Отмена', self.destroy).pack(side='right', padx=10, pady=8)

    def save_export(self):
        from exports import export_collection
        cards = self.app.store.data['cards'] if self.scope.get() == 'Весь архив' else self.app.filtered_cards()
        kind = 'pdf' if self.kind.get() == 'PDF' else 'xlsx'
        if not cards:
            messagebox.showinfo('Экспорт', 'В выбранном списке нет карточек.', parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, title='Сохранить экспорт', defaultextension='.'+kind,
                                          initialfile='Коллекция.'+kind, filetypes=[(self.kind.get(), '*.'+kind)])
        if not path:
            return
        try:
            self.configure(cursor='watch')
            self.update_idletasks()
            export_collection(self.app.store, cards, path, kind)
        except Exception as exc:
            messagebox.showerror('Экспорт не завершён', str(exc), parent=self)
        else:
            messagebox.showinfo('Экспорт готов', f'Сохранено карточек: {len(cards)}\n{path}', parent=self)
            self.destroy()
        finally:
            if self.winfo_exists():
                self.configure(cursor='')


class SettingsDialog(OverlayDialog):
    def __init__(self, app: "SKladApp"):
        self.vars: dict[str, object] = {}
        super().__init__(app, "Настройки", "920x760")
        self.minsize(780, 640)
        self._build()

    def _build(self):
        header = tk.Frame(self, bg=self.p.panel, padx=26, pady=20)
        header.pack(fill="x")
        self.label(header, "Настройки", 22, True).pack(side="left")
        self.label(header, "Все параметры доступны без тарифа", 9, fg=self.p.muted).pack(side="right")
        notebook = RoundedTabs(self)
        notebook.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        appearance, typography = self._tab(notebook, "Оформление"), self._tab(notebook, "Типографика")
        layout, comfort = self._tab(notebook, "Макет"), self._tab(notebook, "Удобство")
        license_tab = self._tab(notebook, 'Лицензия')
        self.license_status = tk.StringVar()
        self.label(license_tab, '', textvariable=self.license_status, size=16, bold=True).pack(anchor='w', padx=14, pady=18)
        self.label(license_tab, 'Полная версия — 299 ₽ один раз.\nБез подписки и ограничения количества карточек.', justify='left').pack(anchor='w', padx=14, pady=8)
        self.button(license_tab, 'Покупка и восстановление лицензии', self.manage_license, primary=True).pack(anchor='w', padx=14, pady=18)
        self.update_license_status()
        self._combo(appearance, "Тема", "theme", [("Тёмная", "dark"), ("Светлая", "light"), ("Стеклянная", "glass"), ("Свой цвет", "custom")])
        self._color(appearance, "Цвет собственной темы", "theme_color")
        self._combo(appearance, "Акцентный цвет", "accent", list(ACCENTS.items()))
        self._color(appearance, "Свой акцентный цвет", "accent_color")
        self._combo(appearance, "Фон страниц", "background_style", [("Градиент", "gradient"), ("Сеточный свет", "mesh"), ("Мягкий туман", "soft")])
        self._scale(appearance, "Интенсивность фона", "background_intensity", 0, 100)
        self._combo(appearance, "Внешний вид карточек", "card_style", [("Объёмные", "elevated"), ("Плоские", "flat"), ("С контуром", "outline")])
        self._scale(typography, "Размер шрифта, %", "font_scale", 85, 160)
        self._combo(typography, "Шрифт интерфейса", "font_family", [(x, x) for x in ["Segoe UI", "Arial", "Montserrat", "Roboto", "Playfair Display", "Lato"]])
        self._combo(typography, "Межстрочный интервал", "line_height", [("Компактный", "compact"), ("Стандартный", "normal"), ("Свободный", "relaxed")])
        self._combo(typography, "Насыщенность текста", "body_weight", [("Обычная", "regular"), ("Усиленная", "medium"), ("Жирная", "strong")])
        self._combo(typography, "Семейство заголовков", "heading_font", [("Современные", "sans"), ("Классические", "serif"), ("Акцентные", "display")])
        self._combo(typography, "Стиль заголовков", "heading_style", [("Нейтральные", "minimal"), ("С акцентом", "soft"), ("Капс", "caps")])
        self._combo(typography, "Цвет заголовков", "heading_color", [("Авто", "auto"), ("Акцент", "accent"), ("Мягкий", "muted")])
        self._combo(typography, "Тональность текста", "text_tone", [("Сбалансированная", "balanced"), ("Мягкая", "soft"), ("Насыщенная", "bold")])
        self._combo(layout, "Плотность интерфейса", "density", [("Компактная", "compact"), ("Стандартная", "cozy"), ("Воздушная", "spacious")])
        self._combo(layout, "Ширина боковой панели", "sidebar_size", [("Узкая", "narrow"), ("Стандартная", "normal"), ("Расширенная", "wide")])
        self._combo(layout, "Поведение верхней панели", "topbar_mode", [("Всегда на виду", "floating"), ("Статично вверху", "static"), ("Скрыть панель", "hidden")])
        self._combo(layout, "Размер карточек", "card_size", [("Маленькие", "small"), ("Средние", "medium"), ("Крупные", "large")])
        self._combo(layout, "Пустые поля", "empty_fields", [("Показывать прочерк", "dash"), ("Скрывать", "hide")])
        self._combo(layout, "Миниатюры", "thumbnails", [("Показывать", "always"), ("Скрывать", "hidden")])
        self._check(comfort, "Снизить анимации", "reduce_motion", "Интерфейс использует минимум движения")
        self._check(comfort, "Сильный контур фокуса", "focus_strong", "Повышает заметность активных полей")
        self._check(comfort, "Упростить фон", "plain_background", "Убирает цветовые эффекты фона")
        self._check(comfort, "Показывать подсказки", "show_hints", "Оставляет пояснения в интерфейсе")
        footer = tk.Frame(self, bg=self.p.panel, padx=26, pady=16)
        footer.pack(fill="x")
        self.button(footer, "Сбросить оформление", self.reset).pack(side="left")
        self.button(footer, "Отмена", self.destroy).pack(side="right")
        self.button(footer, "Применить", self.save, primary=True).pack(side="right", padx=8)

    def update_license_status(self):
        self.license_status.set('Полная версия активирована навсегда' if self.app.store.is_licensed()
                               else f'Бесплатная версия · Заполнено {len(self.app.store.data["cards"])} из 10')

    def manage_license(self):
        dialog = PurchaseDialog(self.app)
        dialog.transient(self)
        self.wait_window(dialog)
        if self.winfo_exists():
            self.grab_set()
            self.update_license_status()

    def _tab(self, notebook, title):
        outer = tk.Frame(notebook, bg=self.p.bg)
        notebook.add(outer, text=title)
        scroll = ScrollFrame(outer, self.p)
        scroll.pack(fill="both", expand=True, padx=12, pady=12)
        return scroll.inner

    def _row(self, parent, label, description=""):
        row = RoundedPanel(parent, bg=self.p.panel, highlightbackground=self.p.border, padx=8, pady=4)
        row.pack(fill="x", pady=5)
        text = tk.Frame(row, bg=self.p.panel)
        text.pack(side="left", fill="x", expand=True)
        self.label(text, label, 10, True).pack(anchor="w")
        if description:
            self.label(text, description, 8, fg=self.p.muted).pack(anchor="w", pady=(3, 0))
        return row

    def _combo(self, parent, label, key, options):
        row = self._row(parent, label)
        labels, reverse = [name for name, _ in options], {value: name for name, value in options}
        var = tk.StringVar(value=reverse.get(self.app.settings.get(key), labels[0]))
        self.vars[key] = (var, dict(options))
        RoundedCombo(row, textvariable=var, values=labels, state="readonly", width=24).pack(side="right", padx=(16, 0))

    def _scale(self, parent, label, key, low, high):
        row = self._row(parent, label)
        var = tk.IntVar(value=int(self.app.settings.get(key, low)))
        self.vars[key] = var
        RoundedSlider(row, var, low, high, self.p).pack(side="right")

    def _color(self, parent, label, key):
        row = self._row(parent, label)
        var = tk.StringVar(value=self.app.settings.get(key, "#3da653"))
        self.vars[key] = var
        preview = RoundedButton(row, text=var.get(), normal=var.get(), hover=var.get(), fg="#ffffff" if not is_light(var.get()) else "#000000", width=12, padx=8, pady=7)
        preview.pack(side="right")
        def choose():
            dialog = ThemeColorDialog(self, var.get())
            self.wait_window(dialog)
            self.grab_set()
            color = dialog.result
            if color:
                var.set(color)
                preview.caption, preview.hover = color, color
                preview.foreground = "#ffffff" if not is_light(color) else "#000000"
                preview.configure(bg=color)
        preview.command = choose

    def _check(self, parent, label, key, description):
        row = self._row(parent, label, description)
        var = tk.BooleanVar(value=bool(self.app.settings.get(key, False)))
        self.vars[key] = var
        tk.Checkbutton(row, variable=var, bg=self.p.panel, activebackground=self.p.panel, selectcolor=self.p.input).pack(side="right")

    def values(self):
        result = {}
        for key, value in self.vars.items():
            if isinstance(value, tuple):
                variable, mapping = value
                result[key] = mapping[variable.get()]
            else:
                result[key] = value.get()
        return result

    def save(self):
        self.app.store.data["settings"].update(self.values())
        self.app.store.save()
        self.destroy()
        self.app.apply_settings()

    def reset(self):
        if messagebox.askyesno("Сбросить оформление", "Вернуть стандартные настройки интерфейса?", parent=self):
            self.app.store.data["settings"] = deepcopy(DEFAULT_SETTINGS)
            self.app.store.save()
            self.destroy()
            self.app.apply_settings()


class SKladApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("СКлад")
        self.root.geometry("1500x920")
        self.root.minsize(1040, 680)
        self.store = Storage(resource_path(), resource_path("assets"))
        self.settings = self.store.data["settings"]
        self.selected_rubric = "all"
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self.on_search_change)
        self.photo_cache, self.resize_after = {}, None
        self.apply_settings(initial=True)
        self.root.bind("<Control-f>", lambda _e: self.focus_search())
        self.root.bind("<Control-n>", lambda _e: self.add_card())
        self.root.bind("<Configure>", self.on_resize)
        self.root.bind_all("<MouseWheel>", self.scroll_under_pointer, add="+")

    def scroll_under_pointer(self, event):
        widget = event.widget
        while widget is not None:
            if isinstance(widget, ScrollFrame):
                return widget.wheel(event)
            widget = getattr(widget, "master", None)

    @property
    def focus_width(self):
        return 2 if self.settings.get("focus_strong") else 1

    def font(self, size: int, bold=False, heading=False):
        scale = max(.85, min(1.6, float(self.settings.get("font_scale", 100)) / 100))
        family = self.settings.get("font_family", "Segoe UI")
        if heading:
            family = {"serif": "Georgia", "display": "Palatino Linotype"}.get(self.settings.get("heading_font"), family)
        weight = "bold" if bold or self.settings.get("body_weight") == "strong" else "normal"
        return (family, max(8, round(size * scale)), weight)

    def spacing(self, value: int) -> int:
        return max(1, round(value * {"compact": .82, "normal": 1.0, "relaxed": 1.24}.get(self.settings.get("line_height"), 1.0)))

    def heading_fg(self):
        return {"accent": self.p.accent, "muted": self.p.muted}.get(self.settings.get("heading_color"), self.p.text)

    def apply_settings(self, initial=False):
        self.settings = self.store.data["settings"]
        self.p = Palette(self.settings)
        self.root._glass = self.p.glass
        self.root._palette = self.p
        self.photo_cache.clear()
        self.root.configure(bg=self.p.bg)
        self.root.option_add("*Font", self.font(10))
        self.configure_styles()
        self.set_icon()
        for child in self.root.winfo_children():
            child.destroy()
        self.build()
        self.root.after(40, lambda: enable_dark_titlebar(self.root, self.p.dark))

    def configure_styles(self):
        # ttk renders a combobox popup as a separate Tk listbox on Windows;
        # option database rules are required in addition to the ttk style.
        themed_options = {
            "*TCombobox*Listbox.background": self.p.input,
            "*TCombobox*Listbox.foreground": self.p.text,
            "*TCombobox*Listbox.selectBackground": self.p.accent,
            "*TCombobox*Listbox.selectForeground": self.p.accent_fg,
            "*TCombobox*Listbox.font": self.font(10),
            "*Menu.background": self.p.panel,
            "*Menu.foreground": self.p.text,
            "*Menu.activeBackground": self.p.accent,
            "*Menu.activeForeground": self.p.accent_fg,
            "*Menu.selectColor": self.p.accent,
        }
        for pattern, value in themed_options.items():
            self.root.option_add(pattern, value, "interactive")
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=self.p.input, background=self.p.input, foreground=self.p.text, arrowcolor=self.p.text, bordercolor=self.p.border, darkcolor=self.p.input, lightcolor=self.p.input, selectbackground=self.p.input, selectforeground=self.p.text)
        style.map("TCombobox", fieldbackground=[("readonly", self.p.input), ("disabled", self.p.panel)], background=[("readonly", self.p.input), ("active", self.p.selected)], foreground=[("readonly", self.p.text), ("disabled", self.p.muted)], arrowcolor=[("readonly", self.p.text), ("active", self.p.accent)])
        style.configure("TNotebook", background=self.p.panel, borderwidth=0, bordercolor=self.p.border, lightcolor=self.p.panel, darkcolor=self.p.panel)
        style.configure("TNotebook.Tab", background=self.p.input, foreground=self.p.text, padding=(18, 9), bordercolor=self.p.border, lightcolor=self.p.panel, darkcolor=self.p.panel)
        style.map("TNotebook.Tab", background=[("selected", self.p.accent)], foreground=[("selected", self.p.accent_fg)])
        style.configure("Vertical.TScrollbar", background=self.p.panel, troughcolor=self.p.bg, arrowcolor=self.p.muted, bordercolor=self.p.bg)

    def set_icon(self):
        # Keep the native title bar visually clean: the product mark is not
        # repeated inside the application window.
        self.icon_photo = ImageTk.PhotoImage(Image.new("RGBA", (32, 32), (0, 0, 0, 0)))
        self.root.iconphoto(True, self.icon_photo)

    def build(self):
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        widths = {"narrow": 270, "normal": 340, "wide": 400}
        self.sidebar = tk.Frame(self.root, width=widths.get(self.settings.get("sidebar_size"), 340), bg=self.p.sidebar, highlightthickness=1, highlightbackground=self.p.border)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.pack_propagate(False)
        self.main = tk.Frame(self.root, bg=self.p.gradient_end)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        hidden = self.settings.get("topbar_mode") == "hidden"
        self.main.grid_rowconfigure(0 if hidden else 1, weight=1)
        self.build_sidebar()
        if not hidden:
            self.build_toolbar()
        self.scroll = ScrollFrame(self.main, self.p)
        self.scroll.grid(row=0 if hidden else 1, column=0, sticky="nsew", padx=(20, 18), pady=(10, 18))
        self.refresh()

    def button(self, master, text, command, primary=False, normal=None, hover=None, **kwargs):
        normal = normal or (self.p.accent if primary else self.p.panel)
        hover = hover or (self.p.accent_hover if primary else self.p.selected)
        fg = self.p.accent_fg if primary else self.p.text
        return HoverButton(master, text=text, command=command, normal=normal, hover=hover, fg=fg, activeforeground=fg, relief="flat", bd=0, font=self.font(10, bold=primary), cursor="hand2", **kwargs)

    def build_sidebar(self):
        pad = self.spacing({"compact": 20, "cozy": 28, "spacious": 36}.get(self.settings.get("density"), 28))
        self.button(self.sidebar, "Создать рубрику", self.add_rubric, primary=True, padx=16, pady=14).pack(fill="x", padx=pad, pady=(30, 30))
        tk.Label(self.sidebar, text="РУБРИКИ", bg=self.p.sidebar, fg=self.p.muted, font=self.font(9)).pack(anchor="w", padx=pad, pady=(0, 8))
        self.rubric_nav = tk.Frame(self.sidebar, bg=self.p.sidebar)
        self.rubric_nav.pack(fill="both", expand=True)
        bottom = tk.Frame(self.sidebar, bg=self.p.sidebar, bd=0, highlightthickness=0, padx=14, pady=14)
        bottom.pack(fill="x", side="bottom")
        self.button(bottom, "Настройки", self.open_settings, normal=self.p.sidebar, hover=self.p.selected, anchor="w", padx=pad, pady=20).pack(fill="x")

    def build_toolbar(self):
        pad = self.spacing({"compact": 16, "cozy": 24, "spacious": 32}.get(self.settings.get("density"), 24))
        toolbar = tk.Frame(self.main, bg=self.p.gradient_start, height=80, highlightthickness=1, highlightbackground=self.p.border)
        self.toolbar = toolbar
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_propagate(False)
        toolbar.grid_columnconfigure(0, weight=1)
        search = RoundedPanel(toolbar, bg=self.p.input, highlightbackground=self.p.border)
        search.grid(row=0, column=0, sticky="w", padx=(28, 12), pady=(13, 12))
        tk.Label(search, text="⌕", bg=self.p.input, fg=self.p.text, font=self.font(17)).pack(side="left", padx=(8, 2))
        self.search_entry = tk.Entry(search, textvariable=self.search_var, width=25, bg=self.p.input, fg=self.p.text, insertbackground=self.p.text, relief="flat", bd=0, font=self.font(11))
        self.search_entry.pack(side="left", padx=(2, 6), ipady=3)
        self.search_placeholder = tk.Label(search, text="Поиск по архиву", bg=self.p.input, fg=self.p.muted, font=self.font(11), cursor="xterm")
        self.search_placeholder.place(x=48, rely=.5, anchor="w")
        self.search_placeholder.bind("<Button-1>", lambda _e: self.search_entry.focus_set())
        self.update_search_placeholder()
        self.usage_caption = tk.StringVar()
        self.usage_bar = tk.Frame(toolbar, bg=self.p.gradient_start)
        tk.Label(self.usage_bar, textvariable=self.usage_caption, bg=self.p.gradient_start, fg=self.p.text, font=self.font(10)).pack(side='left', padx=(0, 10))
        self.button(self.usage_bar, 'Купить', lambda: PurchaseDialog(self), primary=True, padx=14, pady=9).pack(side='left')
        toolbar.bind('<Configure>', lambda _event: self.layout_usage())
        menu_button = self.button(toolbar, 'Меню ⋮', lambda: self.toolbar_menu(menu_button), padx=16, pady=10)
        menu_button.grid(row=0, column=2, padx=(12, 22))

    def toolbar_menu(self, anchor):
        RoundedPopup(self.root, self.p, [
            ('Экспорт данных', None, False),
            ('Экспорт', lambda: ExportDialog(self), False),
            ('Вид карточек', None, False),
            ('Плитка' + (' ✓' if self.settings.get('view') == 'grid' else ''), lambda: self.set_view('grid'), False),
            ('Список' + (' ✓' if self.settings.get('view') == 'list' else ''), lambda: self.set_view('list'), False),
        ], anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height(), font=self.font(10))

    def layout_usage(self):
        if self.store.is_licensed():
            self.usage_bar.grid_remove()
            self.toolbar.configure(height=80)
        elif self.toolbar.winfo_width() < 740 * self.settings.get('font_scale', 100) / 100:
            self.usage_bar.grid(row=1, column=0, columnspan=5, sticky='e', padx=22, pady=(0, 10))
            self.toolbar.configure(height=124)
        else:
            self.usage_bar.grid(row=0, column=1, columnspan=1, sticky='e', padx=8, pady=0)
            self.toolbar.configure(height=80)

    def update_search_placeholder(self):
        if hasattr(self, "search_placeholder"):
            if self.search_var.get():
                self.search_placeholder.place_forget()
            else:
                self.search_placeholder.place(x=48, rely=.5, anchor="w")

    def on_search_change(self, *_args):
        self.update_search_placeholder()
        self.render_cards()

    def focus_search(self):
        if hasattr(self, "search_entry"):
            self.search_entry.focus_set()

    def on_resize(self, event):
        if event.widget is not self.root or not hasattr(self, "scroll"):
            return
        size = (event.width, event.height)
        if getattr(self, '_root_size', None) == size:
            return
        self._root_size = size
        if self.resize_after:
            self.root.after_cancel(self.resize_after)
        self.resize_after = self.root.after(180, self.render_cards)

    def run(self):
        self.root.mainloop()

    def refresh(self):
        if hasattr(self, 'usage_caption'):
            self.usage_caption.set(f'Заполнено {len(self.store.data["cards"])} из 10')
            self.layout_usage()
        self.render_nav()
        self.render_cards()

    def render_nav(self):
        self.nav_rows = []
        for child in self.rubric_nav.winfo_children():
            child.destroy()
        self.nav_item("all", "collection_box.png", "Все предметы", len(self.store.data["cards"]))
        for rubric in self.store.data["rubrics"]:
            self.nav_item(rubric["id"], rubric.get("icon", "collection_box.png"), rubric["name"], sum(c["rubric_id"] == rubric["id"] for c in self.store.data["cards"]))

    def nav_item(self, rubric_id, icon_file, name, count):
        active = rubric_id == self.selected_rubric
        bg = self.p.selected if active else self.p.sidebar
        row = RoundedPanel(self.rubric_nav, bg=bg, highlightbackground=self.p.accent if active else bg)
        row.pack(fill="x", padx=12, pady=3)
        btn = tk.Label(row, text=name, anchor="w", bg=bg, fg=self.p.text, bd=0, font=self.font(11), padx=10, pady=7, cursor="hand2", takefocus=1)
        btn.pack(side="left", fill="both", expand=True)
        widgets = [row.shell, row, btn]
        more = None
        if rubric_id != "all":
            more = tk.Label(row, text='⋮', bg=bg, fg=self.p.muted, font=self.font(16),
                            bd=0, highlightthickness=0, padx=3, pady=0, cursor='hand2', takefocus=1)
            more.caption = '⋮'
            more.command = lambda: self.rubric_menu(None, rubric_id, more)
            more.pack(side='right', padx=(2, 4))
            more.bind('<ButtonRelease-1>', lambda _e: more.command())
            more.bind('<Return>', lambda _e: more.command())
            more.bind('<space>', lambda _e: more.command())
        counter = tk.Label(row, text=str(count), bg=bg, fg=self.p.text, font=self.font(10), padx=10 if rubric_id != 'all' else 22, cursor='hand2')
        counter.pack(side="right", fill="y")
        widgets.append(counter)
        def paint(over):
            if not row.winfo_exists():
                return
            active = rubric_id == self.selected_rubric
            color = self.p.selected if active or over else self.p.sidebar
            edge = self.p.accent if active else color
            if row.fill == color and row.edge == edge:
                return
            row.fill = color
            row.edge = edge
            for widget in [row, btn, counter] + ([more] if more else []):
                widget.configure(bg=color)
            from types import SimpleNamespace
            row._resize(SimpleNamespace(width=row.shell.winfo_width(), height=row.shell.winfo_height()))
        def leave(_event):
            def check():
                if row.winfo_exists():
                    x, y = row.winfo_pointerxy()
                    paint(row.shell.winfo_rootx() <= x < row.shell.winfo_rootx() + row.shell.winfo_width()
                          and row.shell.winfo_rooty() <= y < row.shell.winfo_rooty() + row.shell.winfo_height())
            self.root.after_idle(check)
        for widget in widgets:
            widget.bind('<ButtonRelease-1>', lambda _e: self.select_rubric(rubric_id))
        btn.bind('<Return>', lambda _e: self.select_rubric(rubric_id))
        btn.bind('<space>', lambda _e: self.select_rubric(rubric_id))
        for widget in widgets + ([more] if more else []):
            widget.bind('<Enter>', lambda _e: paint(True))
            widget.bind('<Leave>', leave)
            widget.bind('<FocusIn>', lambda _e: paint(True))
            widget.bind('<FocusOut>', leave)
            if rubric_id != 'all':
                widget.bind('<Button-3>', lambda e: self.rubric_menu(e, rubric_id))
        row.shell.configure(height=max(btn.winfo_reqheight(), more.winfo_reqheight() if more else 0) + 20)
        self.nav_rows.append((row, paint))

    def select_rubric(self, rubric_id):
        if self.selected_rubric == rubric_id:
            return
        self.selected_rubric = rubric_id
        # Selection changes colors only; keep the existing navigation widgets
        # and their measured geometry instead of destroying and rebuilding them.
        for row, paint in self.nav_rows:
            paint(False)
        self.render_cards()

    def filtered_cards(self):
        query = self.search_var.get().strip().casefold()
        cards = self.store.data["cards"]
        if self.selected_rubric != "all":
            cards = [card for card in cards if card["rubric_id"] == self.selected_rubric]
        if query:
            cards = [card for card in cards if query in " ".join(str(v) for v in card.get("values", {}).values()).casefold()]
        mode = self.settings.get("sort", "created")
        if mode == "title":
            cards = sorted(cards, key=lambda c: c.get("values", {}).get("title", "").casefold())
        elif mode == "rubric":
            cards = sorted(cards, key=lambda c: (self.store.rubric(c["rubric_id"]) or {}).get("name", "").casefold())
        return cards

    def render_cards(self):
        if not hasattr(self, "scroll"):
            return
        for child in self.scroll.inner.winfo_children():
            child.destroy()
        for col in range(self.scroll.inner.grid_size()[0]):
            self.scroll.inner.grid_columnconfigure(col, weight=0, minsize=0, uniform='')
        cards = self.filtered_cards()
        if self.settings.get("view") == "list":
            for card in cards:
                self.list_card(card)
            self.add_card_tile(list_view=True)
            return
        # Use the stable root and configured sidebar dimensions. A freshly
        # rebuilt main frame still reports 1px even in an idle callback.
        width = max(self.root.winfo_width() - int(self.sidebar.cget('width')) - 54, 650)
        target = {"small": 235, "medium": 285, "large": 350}.get(self.settings.get("card_size"), 285)
        columns = max(2, min(5, width // target))
        for col in range(columns):
            self.scroll.inner.grid_columnconfigure(col, weight=1, uniform="cards")
        first_frame = None
        for index, card in enumerate(cards):
            frame = self.grid_card(card, index // columns, index % columns)
            first_frame = first_frame or frame
        self.add_card_tile(len(cards) // columns, len(cards) % columns)
        if first_frame is not None:
            tile = self.add_tile
            # The add tile must not impose its default height on the row.
            tile.configure(height=1)
            def match_height():
                if tile.winfo_exists() and first_frame.winfo_exists():
                    tile.configure(height=first_frame.shell.winfo_height())
            first_frame.shell.bind('<Configure>', lambda _event: match_height(), add='+')
            self.root.after_idle(match_height)

    def add_card_tile(self, row=0, column=0, list_view=False):
        from surfaces import surface
        size = {'small': 205, 'medium': 250, 'large': 305}.get(self.settings.get('card_size'), 250)
        tile = tk.Canvas(self.scroll.inner, bg=self.p.bg, width=size+20, height=82 if list_view else size+100,
                         bd=0, highlightthickness=0, cursor='hand2', takefocus=1)
        self.add_tile = tile
        gap = self.spacing({'compact': 5, 'cozy': 7, 'spacious': 11}.get(self.settings.get('density'), 7))
        if list_view:
            tile.pack(fill='x', pady=gap)
        else:
            tile.grid(row=row, column=column, sticky='nsew', padx=gap, pady=gap)
        def draw(event=None, hover=False):
            w, h = tile.winfo_width(), tile.winfo_height()
            if w < 2 or h < 2:
                return
            tile._photo = surface(w, h, self.p.selected if hover else self.p.bg, self.p.accent if hover else self.p.border, 14)
            tile.delete('all')
            tile.create_image(0, 0, image=tile._photo, anchor='nw')
            tile.create_text(w/2, h/2, text='+', fill=self.p.accent, font=self.font(36))
        tile.bind('<Configure>', draw)
        tile.bind('<Enter>', lambda e: draw(e, True))
        tile.bind('<Leave>', draw)
        tile.bind('<ButtonRelease-1>', lambda e: self.add_card())
        tile.bind('<Return>', lambda e: self.add_card())
        tile.bind('<space>', lambda e: self.add_card())

    def card_border(self):
        style = self.settings.get("card_style", "outline")
        return (0, self.p.bg) if style == "flat" else (2 if style == "elevated" else 1, self.p.border)

    def grid_card(self, card, row, column):
        thickness, border = self.card_border()
        gap = self.spacing({"compact": 5, "cozy": 7, "spacious": 11}.get(self.settings.get("density"), 7))
        image_size = {"small": 205, "medium": 250, "large": 305}.get(self.settings.get("card_size"), 250)
        frame = RoundedPanel(self.scroll.inner, bg=self.p.card, highlightbackground=border)
        frame.grid(row=row, column=column, sticky="nsew", padx=gap, pady=gap)
        images = card.get("images", [])
        path = self.store.resolve_image(images[0]) if images and self.settings.get("thumbnails") != "hidden" else resource_path("assets/no-photo.png")
        photo = self.photo(path or resource_path("assets/no-photo.png"), (image_size, image_size))
        tk.Button(frame, image=photo, command=lambda: CardViewDialog(self, card), bg=self.p.input, activebackground=self.p.input, relief="flat", bd=0, cursor="hand2").pack(fill="x")
        info = tk.Frame(frame, bg=self.p.card, padx=self.spacing(14), pady=self.spacing(11))
        info.pack(fill="both", expand=True)
        title = card.get("values", {}).get("title", "Без названия")
        tk.Button(info, text=title, command=lambda: CardViewDialog(self, card), bg=self.p.card, fg=self.p.text, activebackground=self.p.card, activeforeground=self.p.text, anchor="w", relief="flat", bd=0, font=self.font(10, True), cursor="hand2").pack(fill="x")
        rubric = self.store.rubric(card["rubric_id"])
        details = card.get("values", {}).get("description") or card.get("values", {}).get("material", "")
        tk.Label(info, text=f"{rubric['name'] if rubric else 'Без рубрики'}  ·  {details}".rstrip(" · "), bg=self.p.card, fg=self.p.muted, anchor="w", font=self.font(9)).pack(fill="x", pady=(5, 0))
        more = tk.Button(info, text="Ещё", command=lambda: self.card_menu(card, more), bg=self.p.card, fg=self.p.muted, activebackground=self.p.selected, activeforeground=self.p.text, relief="flat", bd=0, font=self.font(9), cursor="hand2")
        more.place(relx=1, rely=0, anchor="ne")
        return frame

    def list_card(self, card):
        row = RoundedPanel(self.scroll.inner, bg=self.p.bg, highlightbackground=self.p.border, padx=4, pady=2)
        row.pack(fill="x", pady=3)
        images = card.get("images", [])
        path = self.store.resolve_image(images[0]) if images and self.settings.get("thumbnails") != "hidden" else resource_path("assets/no-photo.png")
        photo = self.photo(path or resource_path("assets/no-photo.png"), (62, 62))
        tk.Button(row, image=photo, command=lambda: CardViewDialog(self, card), bg=self.p.input, relief="flat", bd=0).pack(side="left")
        values = card.get("values", {})
        text = tk.Frame(row, bg=self.p.bg)
        text.pack(side="left", fill="x", expand=True, padx=15)
        tk.Button(text, text=values.get("title", "Без названия"), command=lambda: CardViewDialog(self, card), bg=self.p.bg, fg=self.p.text, activebackground=self.p.bg, activeforeground=self.p.text, anchor="w", relief="flat", bd=0, font=self.font(10, True)).pack(fill="x")
        rubric = self.store.rubric(card["rubric_id"])
        tk.Label(text, text=f"{rubric['name'] if rubric else 'Без рубрики'}  ·  {values.get('description', '')}", bg=self.p.bg, fg=self.p.muted, anchor="w", font=self.font(9)).pack(fill="x")
        more = self.button(row, "Ещё", lambda: self.card_menu(card, more), normal=self.p.bg, padx=12, pady=7)
        more.pack(side="right")
        def open_row(_event=None):
            CardViewDialog(self, card)
            return 'break'
        def bind_row(widget):
            if widget is more:
                return
            widget.configure(cursor='hand2')
            widget.bind('<ButtonRelease-1>', open_row)
            for child in widget.winfo_children():
                bind_row(child)
        bind_row(row.shell)
        row.shell.configure(takefocus=1)
        row.shell.bind('<Return>', open_row)
        row.shell.bind('<space>', open_row)

    def photo(self, path: Path, size: tuple[int, int]):
        key = (str(path), size, self.p.input)
        if key in self.photo_cache:
            return self.photo_cache[key]
        canvas = Image.new("RGBA", size, self.p.input)
        try:
            image = Image.open(path).convert("RGBA")
            image.thumbnail((size[0] - 16, size[1] - 16), Image.Resampling.LANCZOS)
            canvas.alpha_composite(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
        except OSError:
            pass
        result = ImageTk.PhotoImage(canvas)
        self.photo_cache[key] = result
        return result

    def set_view(self, view):
        self.settings["view"] = view
        self.store.save()
        self.render_cards()
        if hasattr(self, "grid_btn"):
            for button, active in ((self.grid_btn, view == "grid"), (self.list_btn, view == "list")):
                button.normal = self.p.accent if active else self.p.panel
                button.configure(bg=button.normal)

    def change_sort(self):
        self.settings["sort"] = {"Сначала новые": "created", "По названию": "title", "По рубрикам": "rubric"}[self.sort_var.get()]
        self.store.save()
        self.render_cards()

    def add_rubric(self):
        dialog = RubricDialog(self)
        self.root.wait_window(dialog)
        if dialog.result:
            self.refresh()

    def edit_rubric(self, rubric_id):
        rubric = self.store.rubric(rubric_id)
        if rubric:
            dialog = RubricDialog(self, rubric)
            self.root.wait_window(dialog)
            if dialog.result:
                self.refresh()

    def rubric_menu(self, event, rubric_id, anchor=None):
        if getattr(self, '_rubric_popup', None) is not None and self._rubric_popup.winfo_exists():
            self._rubric_popup.dismiss()
        x, y = (anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height()) if anchor else (event.x_root, event.y_root)
        self._rubric_popup = RoundedPopup(self.root, self.p, [
            ('Редактировать', lambda: self.edit_rubric(rubric_id), False),
            ('Удалить', lambda: self.delete_rubric(rubric_id), True),
        ], x, y, font=self.font(10))

    def delete_rubric(self, rubric_id):
        rubric = self.store.rubric(rubric_id)
        if not rubric:
            return
        if any(card['rubric_id'] == rubric_id for card in self.store.data['cards']):
            messagebox.showinfo('Удалить рубрику', 'Сначала перенесите или удалите карточки этой рубрики. Карточки не будут удалены автоматически.', parent=self.root)
            return
        if not messagebox.askyesno('Удалить рубрику', f'Удалить рубрику «{rubric["name"]}»?', parent=self.root):
            return
        try:
            self.store.delete_rubric(rubric_id)
        except ValueError as exc:
            messagebox.showwarning('Рубрика', str(exc), parent=self.root)
            return
        if self.selected_rubric == rubric_id:
            self.selected_rubric = 'all'
        self.refresh()

    def add_card(self):
        if not self.store.can_add_card():
            PurchaseDialog(self)
            return
        if not self.store.data["rubrics"]:
            messagebox.showinfo("Карточка", "Сначала создайте рубрику", parent=self.root)
            return
        dialog = CardDialog(self, rubric_id=self.selected_rubric if self.selected_rubric != "all" else None)
        self.root.wait_window(dialog)
        if dialog.result:
            self.photo_cache.clear()
            self.refresh()

    def edit_card(self, card):
        dialog = CardDialog(self, card)
        self.root.wait_window(dialog)
        if dialog.result:
            self.photo_cache.clear()
            self.refresh()

    def card_menu(self, card, anchor=None):
        self._card_popup = RoundedPopup(self.root, self.p, [
            ('Открыть', lambda: CardViewDialog(self, card), False),
            ('Редактировать', lambda: self.edit_card(card), False),
            ('Удалить', lambda: self.delete_card(card), True),
        ], *self.root.winfo_pointerxy(), font=self.font(10), anchor=anchor)

    def delete_card(self, card):
        title = card.get("values", {}).get("title", "карточку")
        if messagebox.askyesno("Удалить карточку", f"Удалить «{title}»?", parent=self.root):
            self.store.delete_card(card["id"])
            self.refresh()

    def open_settings(self):
        SettingsDialog(self)


if __name__ == "__main__":
    SKladApp().run()
