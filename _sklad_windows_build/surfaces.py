"""Rounded desktop surfaces; no native white scrollbar or extra dependencies."""
import tkinter as tk
import os
from tkinter import ttk
from tkinter import font as tkfont
from PIL import Image, ImageDraw, ImageTk


def blend(a, b, amount):
    aa = tuple(int(a[i:i+2], 16) for i in (1, 3, 5))
    bb = tuple(int(b[i:i+2], 16) for i in (1, 3, 5))
    return tuple(round(x * (1-amount) + y * amount) for x, y in zip(aa, bb))


def surface(width, height, color, border, radius=12, glass=False):
    width, height = max(2, width), max(2, height)
    scale = 2
    w, h = max(2, width)*scale, max(2, height)*scale
    img = Image.new('RGBA', (w, h))
    mask = Image.new('L', (w, h))
    ImageDraw.Draw(mask).rounded_rectangle((1, 1, w-2, h-2), radius=radius*scale, fill=255)
    fill = Image.new('RGBA', (w, h), color)
    if glass:
        draw = ImageDraw.Draw(fill)
        for y in range(h):
            amount = .09 * (1-y/max(1, h-1))**3
            draw.line((0, y, w, y), fill=blend(color, '#ffffff', amount))
    img.paste(fill, (0, 0), mask)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((1, 1, w-2, h-2), radius=radius*scale, outline=border, width=scale)
    return ImageTk.PhotoImage(img.resize((width, height), Image.Resampling.LANCZOS))


class RoundedPanel(tk.Frame):
    """A frame whose geometry is hosted in an anti-aliased rounded canvas."""
    def __init__(self, master, bg, highlightbackground=None, highlightthickness=1, **kw):
        self.shell = tk.Canvas(master, bg=master.cget('bg'), bd=0, highlightthickness=0)
        self.fill = bg
        self.edge = highlightbackground or bg
        self.glass = getattr(master.winfo_toplevel(), '_glass', False)
        self.inset = 10
        self._photo = None
        super().__init__(self.shell, bg=bg, **kw)
        self._background = self.shell.create_image(0, 0, anchor='nw')
        self._content = self.shell.create_window(self.inset, self.inset, window=self, anchor='nw')
        self.bind('<Configure>', self._request)
        self.shell.bind('<Configure>', self._resize)

    def _request(self, _event=None):
        self.shell.configure(width=self.winfo_reqwidth()+2*self.inset, height=self.winfo_reqheight()+2*self.inset)

    def _resize(self, event):
        if event.width < 2 or event.height < 2:
            return
        key = (event.width, event.height, self.fill, self.edge)
        if getattr(self, '_render_key', None) == key:
            return
        self._render_key = key
        self.shell.itemconfigure(self._content, width=max(1, event.width-2*self.inset))
        # Embedded Tk children are opaque. A uniform fill avoids exposing a
        # rectangular patch against a gradient behind those children.
        self._photo = surface(event.width, event.height, self.fill, self.edge, 14, False)
        self.shell.itemconfigure(self._background, image=self._photo)

    def pack(self, **kw):
        return self.shell.pack(**kw)

    def grid(self, **kw):
        return self.shell.grid(**kw)


class RoundedButton(tk.Canvas):
    def __init__(self, master, normal, hover, text='', command=None, fg='#ffffff', font=None, width=0, padx=16, pady=10, anchor='center', **kw):
        for key in ('activeforeground', 'relief', 'bd', 'activebackground'):
            kw.pop(key, None)
        self.normal, self.hover = normal, hover
        self.command, self.caption, self.foreground = command, text, fg
        self.typeface = tkfont.Font(master, font=font)
        self.padx, self.anchor = padx, anchor
        self.glass = getattr(master.winfo_toplevel(), '_glass', False)
        self._over, self._focused, self._photo = False, False, None
        super().__init__(master, bg=master.cget('bg'), highlightthickness=0, bd=0,
                         width=max(self.typeface.measure(text), self.typeface.measure('0')*width)+2*padx,
                         height=self.typeface.metrics('linespace')+2*pady, takefocus=1, **kw)
        self.bind('<Configure>', self._draw)
        self.bind('<Enter>', lambda e: self._set_hover(True))
        self.bind('<Leave>', lambda e: self._set_hover(False))
        self.bind('<ButtonRelease-1>', lambda e: self.invoke() if 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height() else None)
        self.bind('<space>', lambda e: self.invoke())
        self.bind('<Return>', lambda e: self.invoke())
        self.bind('<FocusIn>', lambda e: self._focus(True))
        self.bind('<FocusOut>', lambda e: self._focus(False))

    def _focus(self, value):
        self._focused = value
        self._draw()

    def _set_hover(self, value):
        self._over = value
        self._draw()

    def invoke(self):
        if self.command:
            return self.command()

    def configure(self, cnf=None, **kw):
        if 'bg' in kw:
            self.normal = kw.pop('bg')
        result = super().configure(cnf, **kw)
        if hasattr(self, '_over'):
            self._draw()
        return result

    def _draw(self, _event=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        color = self.hover if self._over else self.normal
        border = self.foreground if self._focused else '#%02x%02x%02x' % blend(color, '#ffffff', .23 if self.glass else .10)
        key = (w, h, color, border, self.glass)
        if getattr(self, '_surface_key', None) != key:
            self._photo = surface(w, h, color, border, min(12, h//2), self.glass)
            self._surface_key = key
        self.delete('all')
        self.create_image(0, 0, image=self._photo, anchor='nw')
        self.create_text(self.padx if self.anchor == 'w' else w/2, h/2, text=self.caption, fill=self.foreground, font=self.typeface, anchor='w' if self.anchor == 'w' else 'center')


class RoundedPopup(tk.Toplevel):
    """Themed action menu with rounded, transparent corners."""
    def __init__(self, parent, palette, items, x, y, font=None, anchor=None):
        super().__init__(parent)
        self.withdraw()
        self.previous_grab = parent.grab_current()
        self.previous_focus = parent.focus_get()
        self.overrideredirect(True)
        self.configure(bg='#010203' if os.name == 'nt' else palette.panel)
        self._glass, self._palette = palette.glass, palette
        if os.name == 'nt':
            self.attributes('-transparentcolor', '#010203')
        panel = RoundedPanel(self, bg=palette.panel, highlightbackground=palette.border)
        panel.pack(fill='both', expand=True)
        self.buttons = []
        section_height = 0
        for label, command, danger in items:
            if command is None:
                if self.buttons:
                    tk.Frame(panel, bg=palette.border, height=1).pack(fill='x', pady=(6, 4))
                    section_height += 11
                heading = tk.Label(panel, text=label, bg=palette.panel, fg=palette.muted, anchor='w', font=font, padx=8)
                heading.pack(fill='x', pady=(4, 5))
                section_height += heading.winfo_reqheight() + 9
                continue
            button = RoundedButton(panel, text=label, normal=palette.panel,
                                   hover=palette.selected, fg=palette.danger if danger else palette.text,
                                   font=font, anchor='w', padx=14, pady=9,
                                   command=lambda action=command: self.choose(action))
            button.pack(fill='x', pady=2)
            self.buttons.append(button)
        self.update_idletasks()
        # A withdrawn Canvas still reports Tk's default 394x276 request.
        # Derive popup geometry from its actual actions instead.
        width = max(180, max((b.winfo_reqwidth() for b in self.buttons), default=160) + 20)
        height = 20 + section_height + sum(b.winfo_reqheight() + 4 for b in self.buttons)
        x = max(0, min(x, self.winfo_screenwidth() - width - 8))
        y = max(0, min(y, self.winfo_screenheight() - height - 8))
        if anchor is not None:
            owner = parent.winfo_toplevel()
            left, top = owner.winfo_rootx()+8, owner.winfo_rooty()+8
            right = owner.winfo_rootx()+owner.winfo_width()-8
            bottom = owner.winfo_rooty()+owner.winfo_height()-8
            x = max(left, min(anchor.winfo_rootx()+anchor.winfo_width()-width, right-width))
            y = anchor.winfo_rooty()+anchor.winfo_height()+4
            if y+height > bottom:
                # At the bottom edge use the space above, never cover the trigger.
                y = anchor.winfo_rooty()-height-4
            y = max(top, min(y, bottom-height))
        self.geometry(f'{width}x{height}+{x}+{y}')
        self.bind('<Escape>', lambda _e: self.dismiss())
        self.bind('<Button-1>', self.outside_click)
        self.bind('<Down>', lambda _e: self.step(1))
        self.bind('<Up>', lambda _e: self.step(-1))
        self.bind('<Tab>', lambda _e: self.step(1))
        self.deiconify()
        self.lift()
        self.grab_set()
        if self.buttons:
            self.buttons[0].focus_set()

    def step(self, offset):
        current = self.focus_get()
        index = self.buttons.index(current) if current in self.buttons else 0
        self.buttons[(index + offset) % len(self.buttons)].focus_set()
        return 'break'

    def outside_click(self, event):
        if not (self.winfo_rootx() <= event.x_root < self.winfo_rootx() + self.winfo_width()
                and self.winfo_rooty() <= event.y_root < self.winfo_rooty() + self.winfo_height()):
            self.dismiss()

    def dismiss(self):
        if not self.winfo_exists():
            return
        self.grab_release()
        self.destroy()
        if self.previous_grab is not None and self.previous_grab.winfo_exists():
            self.previous_grab.grab_set()
        if self.previous_focus is not None and self.previous_focus.winfo_exists():
            self.previous_focus.focus_set()

    def choose(self, action):
        self.dismiss()
        action()


class SlimScrollbar(tk.Canvas):
    def __init__(self, master, palette, command):
        super().__init__(master, width=8, bg=palette.bg, bd=0, highlightthickness=0)
        self.command, self.color = command, palette.muted
        self.first, self.last = 0., 1.
        self.bind('<Configure>', lambda e: self.draw())
        self.bind('<Button-1>', self.jump)
        self.bind('<B1-Motion>', self.jump)

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        if self.last-self.first >= .999:
            self.pack_forget()
        elif not self.winfo_manager():
            self.pack(side='right', fill='y')
        self.draw()

    def draw(self):
        self.delete('all')
        h = self.winfo_height()
        a, b = self.first*h+3, max(self.first*h+23, self.last*h-3)
        self.create_line(4, a, 4, b, width=4, fill=self.color, capstyle='round')

    def jump(self, event):
        self.command('moveto', max(0, min(1, event.y/max(1, self.winfo_height())-(self.last-self.first)/2)))


class RoundedEntry(RoundedPanel):
    def __init__(self, master, **kw):
        bg = kw.pop('bg')
        border = kw.pop('highlightbackground', bg)
        focus = kw.pop('highlightcolor', border)
        kw.pop('highlightthickness', None)
        kw.pop('relief', None)
        super().__init__(master, bg=bg, highlightbackground=border)
        self.editor = tk.Entry(self, bg=bg, relief='flat', bd=0, **kw)
        self.editor.pack(fill='both', expand=True)
        self.shell.bind('<Button-1>', lambda _e: self.editor.focus_set())
        self.bind('<Button-1>', lambda _e: self.editor.focus_set())
        self.editor.bind('<FocusIn>', lambda e: self._edge(focus))
        self.editor.bind('<FocusOut>', lambda e: self._edge(border))

    def _edge(self, color):
        self.edge = color
        self.shell.event_generate('<Configure>')

    def focus_set(self):
        self.editor.focus_set()

    def get(self):
        return self.editor.get()


class RoundedCombo(RoundedButton):
    def __init__(self, master, **kw):
        palette = master.winfo_toplevel()._palette
        self.variable = kw.pop('textvariable', None) or tk.StringVar(master)
        self.values = kw.pop('values', [])
        kw.pop('state', None)
        super().__init__(master, normal=palette.input, hover=palette.selected,
                         text=self.variable.get(), fg=palette.text, command=self.open_menu,
                         font=kw.pop('font', None), anchor='w', **kw)
        self._trace = self.variable.trace_add('write', self._changed)
        self.bind('<Down>', lambda e: self.open_menu())
        self.bind('<Destroy>', self._cleanup, add='+')

    def _changed(self, *_args):
        self.caption = self.variable.get()
        self._draw()

    def _cleanup(self, event):
        if event.widget is self:
            self.variable.trace_remove('write', self._trace)

    def open_menu(self):
        palette = self.winfo_toplevel()._palette
        if hasattr(self, '_menu') and self._menu.winfo_exists():
            return
        previous_grab = self.grab_current()
        menu = self._menu = tk.Toplevel(self.winfo_toplevel())
        menu.withdraw()
        menu.transient(self.winfo_toplevel())
        menu.overrideredirect(True)
        menu.configure(bg='#010203')
        menu._glass, menu._palette = self.glass, palette
        if os.name == 'nt':
            menu.attributes('-transparentcolor', '#010203')
        panel = RoundedPanel(menu, bg=palette.input, highlightbackground=palette.border)
        panel.pack(fill='both', expand=True)
        def dismiss():
            if menu.winfo_exists():
                menu.grab_release()
                menu.destroy()
            if previous_grab is not None and previous_grab.winfo_exists():
                previous_grab.lift()
                previous_grab.grab_set()
                self.focus_set()
        def choose(value):
            dismiss()
            self.select(value)
        buttons = []
        for value in self.values:
            button = RoundedButton(panel, text=value, normal=palette.selected if value == self.get() else palette.input,
                                   hover=palette.selected, fg=palette.text, font=self.typeface,
                                   anchor='w', pady=7, command=lambda v=value: choose(v))
            button.pack(fill='x', pady=2)
            buttons.append(button)
        menu.update_idletasks()
        w = max(self.winfo_width(), max((button.winfo_reqwidth() for button in buttons), default=160)+20)
        h = 20 + sum(button.winfo_reqheight()+4 for button in buttons)
        x = min(self.winfo_rootx(), self.winfo_screenwidth()-w-8)
        y = min(self.winfo_rooty()+self.winfo_height()+4, self.winfo_screenheight()-h-8)
        menu.geometry(f'{w}x{h}+{max(0,x)}+{max(0,y)}')
        menu.bind('<Escape>', lambda e: dismiss())
        menu.bind('<Button-1>', lambda e: dismiss() if not (0 <= e.x_root-menu.winfo_rootx() < w and 0 <= e.y_root-menu.winfo_rooty() < h) else None)
        menu.deiconify()
        menu.lift()
        menu.grab_set()
        if buttons:
            buttons[0].focus_set()

    def select(self, value):
        self.variable.set(value)
        self.event_generate('<<ComboboxSelected>>')

    def get(self):
        return self.variable.get()


class RoundedTabs(tk.Frame):
    def __init__(self, master):
        self.palette = master._palette
        super().__init__(master, bg=self.palette.panel)
        self.bar = tk.Frame(self, bg=self.palette.panel)
        self.bar.pack(fill='x', pady=(0, 12))
        self.body = tk.Frame(self, bg=self.palette.bg)
        self.body.pack(fill='both', expand=True)
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(0, weight=1)
        self.pages, self.buttons = [], []
        self.selected_index = 0

    def add(self, page, text):
        index = len(self.pages)
        self.pages.append(page)
        page.grid(in_=self.body, row=0, column=0, sticky='nsew')
        button = RoundedButton(self.bar, normal=self.palette.input, hover=self.palette.selected,
                               text=text, fg=self.palette.text, command=lambda: self.select(index))
        button.pack(side='left', padx=(0, 8))
        self.buttons.append(button)
        self.select(self.selected_index)

    def select(self, index):
        self.selected_index = index
        for i, page in enumerate(self.pages):
            self.buttons[i].configure(bg=self.palette.accent if i == index else self.palette.input)
            self.buttons[i].foreground = self.palette.accent_fg if i == index else self.palette.text
            self.buttons[i]._draw()
        self.pages[index].tkraise()


class RoundedSlider(tk.Canvas):
    def __init__(self, master, variable, low, high, palette, color=None):
        super().__init__(master, bg=palette.panel, width=250, height=40, highlightthickness=0, takefocus=1)
        self.variable, self.low, self.high, self.palette = variable, low, high, palette
        self.color = color or palette.accent
        self.thumb_color = color or palette.text
        self._trace = variable.trace_add('write', self.draw)
        self.bind('<Destroy>', self.cleanup, add='+')
        self.bind('<Configure>', self.draw)
        self.bind('<Button-1>', self.move)
        self.bind('<B1-Motion>', self.move)
        self.bind('<Left>', lambda e: self.set(self.variable.get()-1))
        self.bind('<Right>', lambda e: self.set(self.variable.get()+1))

    def set(self, value):
        self.variable.set(max(self.low, min(self.high, round(value))))
        self.draw()

    def move(self, event):
        self.focus_set()
        self.set(self.low+(self.high-self.low)*(event.x-12)/max(1, self.winfo_width()-64))

    def cleanup(self, event):
        if event.widget is self:
            self.variable.trace_remove('write', self._trace)

    def draw(self, *_args):
        self.delete('all')
        end = max(20, self.winfo_width()-52)
        x = 12+(end-12)*(self.variable.get()-self.low)/max(1, self.high-self.low)
        self.create_line(12, 20, end, 20, fill=self.palette.input, width=6, capstyle='round')
        self.create_line(12, 20, x, 20, fill=self.color, width=6, capstyle='round')
        self.create_oval(x-7, 13, x+7, 27, fill=self.thumb_color, outline=self.palette.text)
        self.create_text(end+30, 20, text=str(self.variable.get()), fill=self.palette.text)
