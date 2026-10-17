"""A tiny fake of the parts of tkinter that fkeyautomator.ui uses.

The sandbox this project was built in has no Tk, so this lets the UI code
(build, click handlers, re-drawing) be executed and checked for logic errors.
It does NOT check how anything looks.
"""
import types


class TclError(Exception):
    pass


class Event:
    def __init__(self, x=1, y=1, delta=0):
        self.x, self.y, self.delta = x, y, delta


class _Var:
    def __init__(self, master=None, value=None, name=None):
        self._v = value
        self._traces = []

    def get(self):
        return self._v

    def set(self, value):
        self._v = value
        for cb in list(self._traces):
            cb("v", "", "write")

    def trace_add(self, mode, cb):
        self._traces.append(cb)


class StringVar(_Var):
    def __init__(self, master=None, value="", name=None):
        super().__init__(master, str(value))

    def set(self, value):
        super().set(str(value))


class BooleanVar(_Var):
    def __init__(self, master=None, value=False, name=None):
        super().__init__(master, bool(value))

    def set(self, value):
        super().set(bool(value))


class Widget:
    def __init__(self, master=None, **kw):
        self.master = master
        self._children = []
        if master is not None and hasattr(master, "_children"):
            master._children.append(self)
        self.opts = dict(kw)
        self.bindings = {}
        self.items = 0
        self.texts = []

    # configuration / geometry
    def configure(self, **kw):
        self.opts.update(kw)

    config = configure

    def cget(self, key):
        return self.opts[key]

    def pack(self, **kw):
        self.pack_opts = kw

    def pack_propagate(self, *args):
        pass

    def grid(self, **kw):
        self.grid_opts = kw

    def grid_columnconfigure(self, index, **kw):
        pass

    def bind(self, sequence, func):
        self.bindings[sequence] = func

    def register(self, func):
        return "cmd%d" % id(func)

    def winfo_width(self):
        return 100

    def winfo_height(self):
        return 40

    def winfo_reqwidth(self):
        return 460

    def winfo_reqheight(self):
        return 700

    def winfo_children(self):
        return list(self._children)

    def winfo_exists(self):
        return True

    def focus_get(self):
        return None

    def lift(self):
        pass

    def deiconify(self):
        pass

    def focus_set(self):
        pass

    # canvas drawing: just count items
    def delete(self, *a):
        self.items = 0
        self.texts = []

    def _item(self, *a, **kw):
        self.items += 1
        if "text" in kw:
            self.texts.append(kw["text"])
        return self.items

    create_polygon = create_oval = create_rectangle = create_line = create_text = _item
    create_window = _item

    def bbox(self, tag):
        return (0, 0, 460, 700)

    def yview(self, *args):
        pass

    def yview_scroll(self, number, what):
        self.last_scroll = (number, what)

    def itemconfigure(self, item, **kw):
        pass

    def coords(self, item, *coords):
        pass


class Tk(Widget):
    def __init__(self):
        super().__init__()
        self.after_calls = []
        self.destroyed = False
        self.geometry_value = None
        self.protocols = {}

    def title(self, t):
        self.opts["title"] = t

    def resizable(self, *a):
        pass

    def minsize(self, *a):
        pass

    def iconbitmap(self, path):
        raise TclError("no icon in stub")

    def protocol(self, name, func):
        self.protocols[name] = func

    def update_idletasks(self):
        pass

    def winfo_fpixels(self, spec):
        return 144.0          # 150 % scaling, to exercise px()

    def winfo_reqwidth(self):
        return 460

    def winfo_reqheight(self):
        return 700

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080

    def winfo_x(self):
        return 321

    def winfo_y(self):
        return 123

    def geometry(self, value):
        self.geometry_value = value

    def state(self):
        return "normal"

    def after(self, ms, func=None):
        self.after_calls.append((ms, func))
        return len(self.after_calls)

    def mainloop(self):
        pass

    def destroy(self):
        self.destroyed = True


class Toplevel(Tk):
    def __init__(self, master=None):
        super().__init__()
        self.master = master
        if master is not None:
            master._children.append(self)


class Listbox(Widget):
    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self.values = []
        self.selected = ()

    def delete(self, first, last=None):
        if first == 0 and (last == "end" or last is None):
            self.values.clear()
            self.selected = ()
        elif isinstance(first, int):
            self.values.pop(first)

    def insert(self, index, value):
        self.values.append(value)

    def selection_set(self, index):
        self.selected = (index,)

    def curselection(self):
        return self.selected

    def activate(self, index):
        pass


class Treeview(Widget):
    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self.rows = {}
        self.selected = ()

    def heading(self, column, **kw):
        pass

    def column(self, column, **kw):
        pass

    def insert(self, parent, index, iid=None, values=()):
        iid = str(iid if iid is not None else len(self.rows))
        self.rows[iid] = values
        return iid

    def get_children(self):
        return tuple(self.rows)

    def delete(self, *items):
        for item in items:
            self.rows.pop(str(item), None)

    def selection(self):
        return self.selected

    def selection_set(self, item):
        self.selected = (str(item),)

    def identify_row(self, y):
        return ""

    def identify_column(self, x):
        return "#1"


class Style:
    def __init__(self, master=None):
        pass

    def theme_use(self, *args):
        pass

    def configure(self, *args, **kw):
        pass

    def map(self, *args, **kw):
        pass


def make_module():
    mod = types.ModuleType("tkinter")
    mod.TclError = TclError
    mod.Tk = Tk
    for name in ("Frame", "Label", "Entry", "Canvas", "Scrollbar", "Radiobutton", "Checkbutton"):
        mod.__dict__[name] = type(name, (Widget,), {})
    mod.Toplevel = Toplevel
    mod.Listbox = Listbox
    mod.Scrollbar.set = lambda self, *args: None
    mod.StringVar = StringVar
    mod.BooleanVar = BooleanVar
    ttk = types.ModuleType("tkinter.ttk")
    ttk.Style = Style
    ttk.Treeview = Treeview
    mod.ttk = ttk
    mod.filedialog = types.ModuleType("tkinter.filedialog")
    mod.filedialog.askopenfilename = lambda **kw: ""
    mod.filedialog.asksaveasfilename = lambda **kw: ""
    mod.messagebox = types.ModuleType("tkinter.messagebox")
    mod.messagebox.askyesno = lambda *a, **kw: True
    mod.messagebox.showerror = lambda *a, **kw: None
    mod.simpledialog = types.ModuleType("tkinter.simpledialog")
    mod.simpledialog.askinteger = lambda *a, **kw: None
    return mod
