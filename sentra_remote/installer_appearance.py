"""Native installer artwork, DPI support and an explicit dark/light switch."""
from pathlib import Path
import os
import sys


def enable_native_dpi():
    if os.name != "nt":
        return
    import ctypes
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SENTRA.Setup")


def artwork():
    root = Path(__file__).resolve().parents[1] / "sentra_canvas"
    image = root / "assets/blue.png"
    if not image.is_file():
        image = root / "desktop_ui/src/assets/opendots/blue.png"
    return image, root / "assets/SENTRA-DOT.ico"


def dot_image(root, logical_size=112):
    from PIL import Image, ImageTk
    source, _ = artwork()
    scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
    size = round(logical_size * scale)
    with Image.open(source) as image:
        return ImageTk.PhotoImage(image.resize((size, size), Image.Resampling.LANCZOS), master=root)


def apply_window_identity(root):
    _, icon = artwork()
    root.iconbitmap(default=str(icon))
    if os.name != "nt":
        return
    import ctypes
    import subprocess
    from sentra_canvas.native_brand import _window_taskbar_properties
    root.update_idletasks()
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    command = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "sentra_remote.installer"]
    _window_taskbar_properties(hwnd, icon, app_id="SENTRA.Setup", display_name="SENTRA Setup",
                               relaunch_command=subprocess.list2cmdline(command))


# Keys are the design's light colors. Retain the originals so switching themes
# never accumulates lossy color substitutions or rebuilds active form controls.
DARK = {
    "#ffffff": "#14171d", "#101b32": "#edf1f7", "#5d6c84": "#a2adbf",
    "#e3eaf3": "#303744", "#0875ed": "#398bfa", "#cbd6e5": "#3c4656",
    "#f7f9fd": "#1b2029", "#d3ddeb": "#3c4656", "#f0f6ff": "#263246",
    "#f5f7fa": "#20252e", "#a5c9f4": "#284c78", "#0064d5": "#5b9fff",
    "#e6ebf2": "#272e39", "#d5deeb": "#404b5e", "#f6f9fe": "#101319",
    "#d6e2f3": "#2b3443", "#dfe7f2": "#283243", "#edf4ff": "#141d2a",
    "#e3efff": "#19263b",
}


def theme_controller(root, style):
    originals = []
    def collect(widget):
        colors = {key: widget.cget(key) for key in ("background", "foreground", "insertbackground",
                  "selectbackground", "selectforeground", "highlightbackground", "highlightcolor") if key in widget.keys()}
        items = []
        if widget.winfo_class() == "Canvas":
            for item in widget.find_all():
                options = widget.itemconfigure(item)
                items.extend((item, key, widget.itemcget(item, key)) for key in ("fill", "outline") if key in options)
        originals.append((widget, colors, items))
        for child in widget.winfo_children():
            collect(child)
    collect(root)

    def apply(theme):
        dark = theme == "dark"
        color = lambda value: DARK.get(str(value).lower(), value) if dark else value
        for widget, colors, items in originals:
            if colors:
                widget.configure(**{key: color(value) for key, value in colors.items()})
            for item, key, value in items:
                widget.itemconfigure(item, **{key: color(value)})
        bg, ink, line, blue = map(color, ("#ffffff", "#101b32", "#cbd6e5", "#0875ed"))
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=ink)
        for name in ("TEntry", "TCombobox"):
            style.configure(name, fieldbackground=bg, foreground=ink, background=color("#f7f9fd"),
                            bordercolor=line, lightcolor=line, darkcolor=line, insertcolor=ink, arrowcolor=ink)
        style.map("TCombobox", fieldbackground=[("readonly", bg)], foreground=[("readonly", ink)])
        style.configure("TCheckbutton", background=bg, foreground=ink, indicatorbackground=color("#f7f9fd"),
                        indicatorforeground=ink)
        style.map("TCheckbutton", background=[("active", bg)], indicatorbackground=[("selected", blue)])
        style.configure("Setup.TButton", background=bg, foreground=ink, bordercolor=color("#d3ddeb"),
                        lightcolor=bg, darkcolor=bg, focuscolor=blue)
        style.map("Setup.TButton", background=[("active", color("#f0f6ff")), ("disabled", color("#f5f7fa"))],
                  foreground=[("disabled", color("#5d6c84"))])
        style.configure("Primary.TButton", background=blue, foreground="#ffffff", bordercolor=blue, lightcolor=blue, darkcolor=blue)
        style.map("Primary.TButton", background=[("disabled", color("#a5c9f4")), ("active", color("#0064d5"))], foreground=[("disabled", "#ffffff")])
        style.configure("Setup.Horizontal.TProgressbar", troughcolor=color("#e6ebf2"), background=blue,
                        bordercolor=color("#e6ebf2"), lightcolor=blue, darkcolor=blue)
        style.configure("Vertical.TScrollbar", background=color("#d5deeb"), troughcolor=bg, bordercolor=bg, arrowcolor=ink)
        root.option_add("*TCombobox*Listbox.background", bg)
        root.option_add("*TCombobox*Listbox.foreground", ink)
        if os.name == "nt":
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
            for attribute, value in ((20, int(dark)), (35, 0x001d1714 if dark else 0x00ffffff),
                                     (36, 0x00f7f1ed if dark else 0x00321b10)):
                number = ctypes.c_int(value)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(number), ctypes.sizeof(number))
        return color
    return apply
