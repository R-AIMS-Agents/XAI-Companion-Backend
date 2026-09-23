"""A dialog that asks the operator to fill in whatever the command line left open."""

import sys
import tkinter as tk
from tkinter import ttk

import sv_ttk

# Windows 11 paints the title bar light unless the window opts in, which leaves a white band above a dark dialog.
DWMWA_USE_IMMERSIVE_DARK_MODE = 20


def _darken_title_bar(root: tk.Tk):
    """Ask Windows to paint this window's title bar dark, and accept a light one wherever that is unavailable."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        root.update_idletasks()
        handle = ctypes.windll.user32.GetParent(root.winfo_id())
        enabled = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            handle, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(enabled), ctypes.sizeof(enabled)
        )
    except Exception:
        pass


def _centre(root: tk.Tk):
    """Place the dialog in the middle of the screen, where the operator is already looking."""
    root.update_idletasks()
    width = root.winfo_reqwidth()
    height = root.winfo_reqheight()
    x = (root.winfo_screenwidth() - width) // 2
    y = (root.winfo_screenheight() - height) // 2
    root.geometry(f"+{x}+{y}")


def choose(options: dict[str, list[str]], defaults: dict[str, str | None]) -> dict[str, str]:
    """Ask for one value per field and return the picks, raising when the dialog is dismissed."""
    root = tk.Tk()
    root.title("AI-Companion")
    root.resizable(False, False)
    sv_ttk.set_theme("dark", root)

    frame = ttk.Frame(root, padding=24)
    frame.grid()
    frame.columnconfigure(1, weight=1)

    variables: dict[str, tk.StringVar] = {}
    for row, (field, choices) in enumerate(options.items()):
        # Field names are shown in caps so an acronym and a word sit together without one looking shouted.
        label = ttk.Label(frame, text=field.upper())
        label.grid(row=row, column=0, sticky="w", padx=(0, 16), pady=6)

        variable = tk.StringVar(value=defaults.get(field) or choices[0])
        # A read-only combobox drops the radio marks that OptionMenu puts in front of every entry. A field with one option is shown, so the dialog reads as the whole session, but cannot be opened.
        box = ttk.Combobox(
            frame,
            textvariable=variable,
            values=choices,
            state="readonly" if len(choices) > 1 else "disabled",
            width=22,
        )
        box.grid(row=row, column=1, sticky="ew", pady=6)
        variables[field] = variable

    # Values are read before the interpreter is torn down, because a Tk variable cannot be read afterwards.
    picks: dict[str, str] = {}

    def accept():
        """Keep the current picks and close the dialog."""
        picks.update({field: variable.get() for field, variable in variables.items()})
        root.destroy()

    button = ttk.Button(frame, text="Start", command=accept, style="Accent.TButton")
    button.grid(row=len(options), column=0, columnspan=2, pady=(20, 0), sticky="ew")

    # Focus rests on the button, so a read-only combobox does not open the dialog with a selection highlight on it.
    button.focus_set()
    root.bind("<Return>", lambda _: accept())
    _darken_title_bar(root)
    _centre(root)
    root.mainloop()

    if not picks:
        raise RuntimeError("Selection cancelled.")
    return picks
