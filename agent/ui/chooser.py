"""A dialog that asks the operator to fill in whatever the command line left open."""

import sys
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

import sv_ttk

# Windows 11 paints the title bar light unless the window opts in, which leaves a white band above a dark dialog.
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
WATCH_MS = 500


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


def _watch(root: tk.Tk, note: ttk.Label, variable: tk.StringVar, describe: Callable[[str], str]):
    """Keep a field's note current while the dialog is open, asking in a background thread so a slow answer never freezes the dialog."""
    answers: list[str] = []
    worker: threading.Thread | None = None

    def tick():
        """Show the latest answer and ask again about the field's current value."""
        nonlocal worker
        if answers:
            note.configure(text=answers.pop())
        if worker is None or not worker.is_alive():
            value = variable.get()
            worker = threading.Thread(target=lambda: answers.append(describe(value)), daemon=True)
            worker.start()
        root.after(WATCH_MS, tick)

    tick()


def choose(
    languages: dict[str, str],
    options: dict[str, list[str]],
    defaults: dict[str, str],
    suggested: list[str],
    problem: Callable[[dict[str, str]], str | None],
    hints: dict[str, Callable[[str], str]],
) -> dict[str, str]:
    """Ask for the participant, the language and one value per field and return the picks, ending the run when the dialog is dismissed."""
    root = tk.Tk()
    root.title("XAI-Companion")
    root.resizable(False, False)
    # Kept above every other window, so the dialog cannot get lost behind the terminal or the Unity editor.
    root.attributes("-topmost", True)
    sv_ttk.set_theme("dark", root)

    frame = ttk.Frame(root, padding=24)
    frame.grid()
    frame.columnconfigure(1, weight=1)

    ttk.Label(frame, text="Participant ID").grid(row=0, column=0, sticky="w", padx=(0, 16), pady=6)
    participant = tk.StringVar(value=defaults["participant"])
    ttk.Entry(frame, textvariable=participant, width=12).grid(row=0, column=1, sticky="ew", pady=6)
    for column, suggestion in enumerate(suggested, start=2):
        ttk.Button(frame, text=f"Use '{suggestion}'", command=lambda s=suggestion: participant.set(s)).grid(
            row=0, column=column, sticky="ew", padx=(8, 0), pady=6
        )
    span = len(suggested) + 1

    ttk.Label(frame, text="Language").grid(row=1, column=0, sticky="w", padx=(0, 16), pady=6)
    language = tk.StringVar(value=defaults["language"])
    buttons = ttk.Frame(frame)
    buttons.grid(row=1, column=1, columnspan=span, sticky="w", pady=6)
    for column, (code, name) in enumerate(languages.items()):
        ttk.Radiobutton(buttons, text=name, value=code, variable=language).grid(
            row=0, column=column, padx=(0, 16)
        )

    variables: dict[str, tk.StringVar] = {"participant": participant, "language": language}
    for row, (field, choices) in enumerate(options.items(), start=2):
        # Field names are shown in caps so an acronym and a word sit together without one looking shouted.
        label = ttk.Label(frame, text=field.upper())
        label.grid(row=row, column=0, sticky="w", padx=(0, 16), pady=6)

        variable = tk.StringVar(value=defaults[field])
        # A read-only combobox drops the radio marks that OptionMenu puts in front of every entry. A field with one option is shown, so the dialog reads as the whole session, but cannot be opened.
        box = ttk.Combobox(
            frame,
            textvariable=variable,
            values=choices,
            state="readonly" if len(choices) > 1 else "disabled",
            width=22,
        )
        box.grid(row=row, column=1, columnspan=span, sticky="ew", pady=6)
        variables[field] = variable

        if field in hints:
            note = ttk.Label(frame, foreground="#9a9a9a")
            note.grid(row=row, column=span + 1, sticky="w", padx=(12, 0), pady=6)
            _watch(root, note, variable, hints[field])

    message = ttk.Label(frame, foreground="#ff6b6b", wraplength=320)
    message.grid(row=len(options) + 2, column=0, columnspan=span + 2, sticky="w", pady=(12, 0))

    # Values are read before the interpreter is torn down, because a Tk variable cannot be read afterwards.
    picks: dict[str, str] = {}

    def accept():
        """Keep the current picks and close the dialog, or say what is wrong with them and stay open."""
        current = {field: variable.get() for field, variable in variables.items()}
        if error := problem(current):
            message.configure(text=error)
            return
        picks.update(current)
        root.destroy()

    button = ttk.Button(frame, text="Start", command=accept, style="Accent.TButton")
    button.grid(row=len(options) + 3, column=0, columnspan=span + 2, pady=(12, 0), sticky="ew")

    # Focus rests on the button, so a read-only combobox does not open the dialog with a selection highlight on it.
    button.focus_set()
    root.bind("<Return>", lambda _: accept())
    _darken_title_bar(root)
    _centre(root)
    root.mainloop()

    # Closing the dialog is the operator declining to start a session, which ends the run the same way argparse ends it on a bad flag.
    if not picks:
        raise SystemExit("Selection cancelled.")
    return picks
