#!/usr/bin/env python3
"""
RAM Cat — menubar inference companion for Apple Silicon.

Know before you load. Emoji mood reacts to RAM pressure; spinner fires when
a model is loading; flash signals a mood change.

Moods (memory_pressure free%):
  😴  > 70%  — nothing loaded
  😸  50–70% — model running fine
  😾  30–50% — getting tight
  🙀  15–30% — swap imminent
  😱  < 15%  — you're swapping

Run:  python3 app.py
"""

import re
import sys
import time
import argparse
import subprocess
import collections
import rumps
import psutil

TOTAL_GB = psutil.virtual_memory().total / (1024 ** 3)

MOODS = [
    (70, "😴", "Sleepy — nothing loaded"),
    (50, "😸", "Comfy — model running fine"),
    (30, "😾", "Alert — getting tight"),
    (15, "🙀", "Frazzled — swap imminent"),
    (0,  "😱", "PANIC — swapping now"),
]

# (name, approx 4-bit RAM needed in GB) — covers 8 GB → 192 GB Macs
_MODEL_SIZES = [
    ("235B", 130.0),
    ("90B",   52.0),
    ("72B",   42.0),
    ("70B",   40.0),
    ("32B",   20.0),
    ("27B",   16.0),
    ("14B",    9.0),
    ("13B",    8.0),
    ("8B",     5.0),
    ("7B",     4.5),
    ("3B",     2.0),
    ("1B",     0.8),
]

_SPINNER      = "⣾⣽⣻⢿⡿⣟⣯⣷"
_FLASH_TICKS  = 6   # 6 × 150 ms = 0.9 s, 3 on/off blinks

_MLX_PROCS = (
    "mlx_lm.generate", "mlx_lm.chat", "mlx_lm.server",
    "mlx_lm/generate", "mlx_lm/chat", "mlx_lm/server",
    "mlx_vlm", "ollama",
)
_MODEL_FLAGS = ("--model", "-m")


def _noop(_):
    pass


# ─── Metrics ─────────────────────────────────────────────────────────────────

def _mac_free_pct():
    try:
        out = subprocess.check_output(
            ["memory_pressure"], timeout=3, stderr=subprocess.DEVNULL
        ).decode()
        m = re.search(r"memory free percentage:\s*(\d+)%", out, re.IGNORECASE)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    vm = psutil.virtual_memory()
    return int(vm.available / vm.total * 100)


def _mp_free_gb(free_pct):
    """Convert memory_pressure free% to GB — consistent source for fits row."""
    return free_pct / 100.0 * TOTAL_GB


def _wired_gb():
    try:
        out = subprocess.check_output(
            ["vm_stat"], timeout=3, stderr=subprocess.DEVNULL
        ).decode()
        page_size = 4096
        m = re.search(r"page size of (\d+) bytes", out)
        if m:
            page_size = int(m.group(1))
        m2 = re.search(r"Pages wired down:\s+(\d+)", out)
        if m2:
            return int(m2.group(1)) * page_size / (1024 ** 3)
    except Exception:
        pass
    return None


def _mood(free_pct):
    for threshold, emoji, label in MOODS:
        if free_pct >= threshold:
            return emoji, label
    return "😱", "PANIC — swapping now"


def _sparkline(history):
    if not history:
        return "—"
    chars = "▁▂▃▄▅▆▇█"
    return "".join(
        chars[min(int((100 - pct) / 100 * len(chars)), len(chars) - 1)]
        for pct in history
    )


def _fits_row(free_gb):
    # Show models up to total RAM, plus the next 2 that won't fit (as context).
    # This keeps the row useful on any Mac from 8 GB to 192 GB.
    parts = []
    over = 0
    for name, needed in reversed(_MODEL_SIZES):  # small → large
        if needed > TOTAL_GB:
            over += 1
            if over > 2:
                continue
        parts.append(("✓" if free_gb >= needed else "✗") + name)
    return "  ".join(parts)


def _climbing(history):
    """True when the last 3 free% readings are all declining (RAM filling up)."""
    if len(history) < 3:
        return False
    last = list(history)[-3:]
    return last[0] > last[1] > last[2]


def _extract_model_name(cmdline):
    for i, arg in enumerate(cmdline):
        if arg in _MODEL_FLAGS and i + 1 < len(cmdline):
            path = cmdline[i + 1]
            parts = path.rstrip("/").split("/")
            return "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    return None


def _running_model():
    try:
        for proc in psutil.process_iter(["cmdline"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                cmd_str = " ".join(cmdline)
                if not any(p in cmd_str for p in _MLX_PROCS):
                    continue
                label = "ollama" if "ollama" in cmd_str else "mlx_lm"
                return label, _extract_model_name(cmdline)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return None, None


def _label(text):
    return rumps.MenuItem(text, callback=_noop)


def _set_title(item, text):
    """Assign a menu item's title only if it changed — skips redundant redraws."""
    if item.title != text:
        item.title = text


# ─── CLI ─────────────────────────────────────────────────────────────────────

_ANSI = {
    "green": "92", "cyan": "96", "yellow": "93",
    "magenta": "95", "red": "91", "dim": "2", "bold": "1",
}


def _color(text, *names, enabled=True):
    if not enabled or not names:
        return text
    codes = ";".join(_ANSI[n] for n in names)
    return f"\033[{codes}m{text}\033[0m"


def _mood_color(free_pct):
    """ANSI color name matching the mood thresholds in MOODS."""
    if free_pct >= 70:
        return "green"
    if free_pct >= 50:
        return "cyan"
    if free_pct >= 30:
        return "yellow"
    if free_pct >= 15:
        return "magenta"
    return "red"


def _cli_frame(history, color=False, oneline=False):
    """Build the same status the menubar shows, as terminal text."""
    free_pct   = _mac_free_pct()
    history.append(free_pct)
    mp_free_gb = _mp_free_gb(free_pct)
    emoji, label = _mood(free_pct)
    mc = _mood_color(free_pct)

    if oneline:
        line = f"RAM {emoji} {mp_free_gb:.1f}G · {free_pct}% free"
        return _color(line, mc, "bold", enabled=color)

    used_gb = TOTAL_GB - mp_free_gb
    wired = _wired_gb()
    swap  = psutil.swap_memory()
    proc_label, model_name = _running_model()

    fits = _fits_row(mp_free_gb)
    if color:
        fits = fits.replace("✓", _color("✓", "green")).replace("✗", _color("✗", "red", "dim"))

    running = (
        f"Running: {model_name}  [{proc_label}]" if model_name
        else f"Running: {proc_label}" if proc_label
        else "Idle"
    )
    header = _color(
        f"RAM {emoji} {mp_free_gb:.1f}G · {free_pct}% free", mc, "bold", enabled=color
    )
    return "\n".join([
        f"{header}   ({label})",
        "",
        f"Trend:   {_sparkline(history)}",
        f"Free:    {free_pct}%  ({mp_free_gb:.1f} / {TOTAL_GB:.0f} GB)",
        f"In use:  {used_gb:.1f} / {TOTAL_GB:.0f} GB",
        f"Wired:   {wired:.1f} GB  (model weights)" if wired else "Wired:   —",
        f"Swap:    {swap.used / (1024**3):.1f} GB used" if swap.used > 0 else "Swap:    none",
        f"4-bit:   {fits}   ({mp_free_gb:.1f} GB free)",
        running,
    ])


def run_cli(once=False, interval=3.0, oneline=False, color=None):
    """Terminal front-end — for when the menubar title is hidden by the notch."""
    if color is None:
        color = sys.stdout.isatty()
    history = collections.deque(maxlen=10)
    if once:
        print(_cli_frame(history, color=color, oneline=oneline))
        return
    try:
        while True:
            frame = _cli_frame(history, color=color, oneline=oneline)
            if oneline:
                sys.stdout.write("\r\033[2K" + frame)
            else:
                sys.stdout.write("\033[2J\033[H" + frame + "\n\n(Ctrl-C to quit)\n")
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        if oneline:
            sys.stdout.write("\n")


# ─── App ─────────────────────────────────────────────────────────────────────

class RamCatApp(rumps.App):
    def __init__(self):
        super().__init__("", quit_button=None)
        self._history     = collections.deque(maxlen=10)
        self._spinner_idx = 0
        self._flash_count = 0

        free_pct  = _mac_free_pct()
        mp_free_gb = _mp_free_gb(free_pct)
        used_gb   = TOTAL_GB - mp_free_gb
        emoji, _  = _mood(free_pct)
        self._history.append(free_pct)

        self._cur_emoji   = emoji
        self._cur_pct     = free_pct
        self._cur_free_gb = mp_free_gb
        self._cur_loading = False

        self._last_title  = f"RAM {emoji} {mp_free_gb:.1f}G · {free_pct}% free"
        self.title = self._last_title

        wired = _wired_gb()
        self._spark_item = _label(f"Trend:   {_sparkline(self._history)}")
        self._free_item  = _label(f"Free:    {free_pct}%  ({mp_free_gb:.1f} / {TOTAL_GB:.0f} GB)")
        self._used_item  = _label(f"In use:  {used_gb:.1f} / {TOTAL_GB:.0f} GB")
        self._wired_item = _label(
            f"Wired:   {wired:.1f} GB  (model weights)" if wired else "Wired:   —"
        )
        self._swap_item  = _label("Swap:    none")
        self._fits_item  = _label(
            f"4-bit:   {_fits_row(mp_free_gb)}   ({mp_free_gb:.1f} GB free)"
        )
        self._model_item = _label("Idle")
        self._quit_item  = rumps.MenuItem("Quit RAM Cat", callback=self._quit)

        self.menu = [
            self._spark_item,
            rumps.separator,
            self._free_item,
            self._used_item,
            self._wired_item,
            self._swap_item,
            rumps.separator,
            self._fits_item,
            self._model_item,
            rumps.separator,
            self._quit_item,
        ]

    @rumps.timer(3)
    def poll(self, _):
        """Slow poll — updates metrics and menu text."""
        free_pct   = _mac_free_pct()
        mp_free_gb = _mp_free_gb(free_pct)
        used_gb    = TOTAL_GB - mp_free_gb
        emoji, _   = _mood(free_pct)
        self._history.append(free_pct)

        # Trigger flash when mood emoji changes
        if emoji != self._cur_emoji:
            self._flash_count = _FLASH_TICKS

        self._cur_emoji   = emoji
        self._cur_pct     = free_pct
        self._cur_free_gb = mp_free_gb
        self._cur_loading = _climbing(self._history)

        swap = psutil.swap_memory()
        wired = _wired_gb()

        proc_label, model_name = _running_model()
        running = (
            f"Running: {model_name}  [{proc_label}]" if model_name
            else f"Running: {proc_label}" if proc_label
            else "Idle"
        )

        # Assign only when the text changed — a menu item .title write is a
        # redraw, and most polls leave several rows unchanged.
        _set_title(self._spark_item, f"Trend:   {_sparkline(self._history)}")
        _set_title(self._free_item,  f"Free:    {free_pct}%  ({mp_free_gb:.1f} / {TOTAL_GB:.0f} GB)")
        _set_title(self._used_item,  f"In use:  {used_gb:.1f} / {TOTAL_GB:.0f} GB")
        _set_title(self._wired_item,
            f"Wired:   {wired:.1f} GB  (model weights)" if wired else "Wired:   —")
        _set_title(self._swap_item,
            f"Swap:    {swap.used / (1024**3):.1f} GB used" if swap.used > 0 else "Swap:    none")
        _set_title(self._fits_item,
            f"4-bit:   {_fits_row(mp_free_gb)}   ({mp_free_gb:.1f} GB free)")
        _set_title(self._model_item, running)

    @rumps.timer(0.15)
    def animate(self, _):
        """Fast tick — handles title bar flash and loading spinner.

        Only rewrites the title when it actually changes: when idle (no flash,
        no spinner) the title is static, so this tick becomes a no-op instead of
        forcing a menubar redraw ~7×/s.
        """
        emoji  = self._cur_emoji
        free_g = self._cur_free_gb
        pct    = self._cur_pct

        if self._flash_count > 0:
            show = self._flash_count % 2 == 0
            title = f"RAM {emoji} {free_g:.1f}G · {pct}% free" if show else f"RAM     {free_g:.1f}G · {pct}% free"
            self._flash_count -= 1
        elif self._cur_loading:
            frame = _SPINNER[self._spinner_idx % len(_SPINNER)]
            title = f"RAM {emoji}{frame} {free_g:.1f}G · {pct}% free"
            self._spinner_idx += 1
        else:
            title = f"RAM {emoji} {free_g:.1f}G · {pct}% free"

        if title != self._last_title:
            self.title = title
            self._last_title = title

    def _quit(self, _):
        rumps.quit_application()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="RAM Cat — RAM-pressure companion for local LLMs. "
                    "Runs in the terminal by default; pass --menubar for the menubar app.",
    )
    parser.add_argument(
        "--menubar", action="store_true",
        help="Launch the macOS menubar app. Without this, RAM Cat runs in the terminal.",
    )
    parser.add_argument(
        "--cli", action="store_true",
        help="Terminal watch view (this is the default when --menubar is not given).",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Print a single snapshot and exit (implies --cli).",
    )
    parser.add_argument(
        "--interval", type=float, default=3.0,
        help="Seconds between refreshes in --cli mode (default: 3).",
    )
    parser.add_argument(
        "--oneline", action="store_true",
        help="Compact single-line output (for tmux, Sketchybar, etc.). "
             "Prints once unless combined with --cli.",
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Disable ANSI colors (colors are on by default in a terminal).",
    )
    args = parser.parse_args()

    if args.menubar:
        RamCatApp().run()
    else:
        once  = args.once or (args.oneline and not args.cli)
        color = False if args.no_color else None
        run_cli(once=once, interval=args.interval, oneline=args.oneline, color=color)
