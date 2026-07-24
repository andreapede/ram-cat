# RAM Cat

**Know before you load.**

A macOS menubar companion for Apple Silicon that reacts to RAM pressure in real time — built for people running LLMs locally.

![RAM Cat demo](demo/demo-v3.gif)

---

## Why

Every time you run `mlx_lm.generate` on a 12B model you're playing RAM roulette. Will it fit? Will it swap? Will the system grind to a halt halfway through a response?

RAM Cat watches `memory_pressure` (the honest macOS metric — the same number Activity Monitor uses) and tells you exactly what's happening: a mood emoji that reacts to pressure, a loading spinner when RAM is actively filling, and a one-line answer to "can I load another model right now?"

Why not `psutil`? On macOS, `psutil.virtual_memory().available` counts reclaimable disk cache as used, so it *understates* free RAM — by 2× on a busy machine (psutil: 3.4 GB free; `memory_pressure`: 7 GB). Every number RAM Cat shows comes from `memory_pressure`, so the title bar, the free row, and the model-fit row always agree.

---

## Moods

| Title bar | Meaning |
|-----------|---------|
| `RAM 😴 11.4G · 71% free` | Idle — nothing loaded |
| `RAM 😸 9.3G · 58% free` | Comfortable — model running fine |
| `RAM 😾 6.7G · 42% free` | Alert — getting tight |
| `RAM 🙀 3.5G · 22% free` | Frazzled — swap imminent |
| `RAM 😱 1.6G · 10% free` | PANIC — you're swapping |

The title shows **free** RAM — GB (the number you budget against: "does a 5 GB model fit in 6.7 free?") plus the percentage for context, labeled so there's no free-vs-used guessing. When RAM is actively filling (model loading), a braille spinner appears: `RAM 😾⣾ 6.7G · 42% free` → `RAM 😾⣽ 6.4G · 40% free`. When the mood changes, the title blinks three times so you catch it even if you're not watching.

---

## Click to open

```
Trend:   ▁▁▂▄▅▆▇▇██
──────────────────────────────────
Free:    38%  (6.1 / 16 GB)
In use:  9.9 / 16 GB
Wired:   2.3 GB  (model weights)
Swap:    none
──────────────────────────────────
4-bit:   ✓1B  ✓3B  ✓7B  ✓8B  ✗13B  ✗14B  ✗27B  ✗32B  ✗70B   (6.1 GB free)
Running: mlx-community/gemma-4-it-4bit  [mlx_lm]
──────────────────────────────────
Quit RAM Cat
```

The **4-bit fits row** is the main feature: given current free RAM, it shows which 4-bit quantised models will load and which won't. No mental arithmetic, no trial and error.

The **sparkline** shows the last 30 seconds of pressure history (10 × 3s polls). A flat line means stable; a climbing staircase means a model is loading.

---

## Install

```bash
git clone https://github.com/robertlangdonn/ram-cat.git
cd ram-cat
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py            # terminal watch view
python app.py --menubar  # macOS menubar app
```

Requires macOS (Apple Silicon recommended). Uses the `memory_pressure` CLI which ships with macOS — no sudo, no extra dependencies.

By default RAM Cat runs **in the terminal** — the menubar app is opt-in via `--menubar`, since on a busy menu bar (or behind the notch on newer MacBook Pros) the title can get clipped off-screen.

---

## Terminal mode

Same numbers, same fits row, no menu bar needed:

```bash
python app.py                # top-style watch view, refreshes every 3s (default)
python app.py --interval 1   # faster refresh
python app.py --once         # print one snapshot and exit
python app.py --oneline      # compact single line — for status bars
```

The mood is colored (green → cyan → yellow → magenta → red as RAM tightens), and the fits row marks ✓ green / ✗ red. Colors turn off automatically when the output is piped (not a terminal); force them off with `--no-color`.

```
RAM 😴 25.3G · 79% free   (Sleepy — nothing loaded)

Trend:   ▁▁▂▄▅▆▇▇██
Free:    79%  (25.3 / 32 GB)
In use:  6.7 / 32 GB
Wired:   2.8 GB  (model weights)
Swap:    none
4-bit:   ✓1B  ✓3B  ✓7B  ✓8B  ✓13B  ✓14B  ✓27B  ✓32B  ✗70B  ✗72B   (25.3 GB free)
Running: ollama
```

`--oneline` (and `--once`) are handy for status bars — e.g. a tmux `status-right` or a Sketchybar item that shells out to `python app.py --oneline`. Add `--cli` to `--oneline` to keep a single line updating in place instead. Press `Ctrl-C` to leave any watch view.

---

## Model fit reference (4-bit)

Works on any Mac — the fits row adapts to your machine's total RAM. It lists every model size up to your installed RAM, plus the next two above it (so you know what an upgrade would buy you).

| Model size | RAM needed | Smallest Mac that runs it |
|-----------|------------|---------------------------|
| 1B        | ~0.8 GB    | any |
| 3B        | ~2 GB      | any |
| 7B        | ~4.5 GB    | 8 GB |
| 8B        | ~5 GB      | 8 GB (tight) |
| 13B       | ~8 GB      | 16 GB |
| 14B       | ~9 GB      | 16 GB |
| 27B       | ~16 GB     | 24 GB |
| 32B       | ~20 GB     | 32 GB |
| 70B       | ~40 GB     | 64 GB |
| 72B       | ~42 GB     | 64 GB |
| 90B       | ~52 GB     | 64 GB (tight) |
| 235B      | ~130 GB    | 192 GB |

Numbers are approximate (weights + a working KV cache at moderate context). RAM Cat uses live free memory to compute the ✓/✗ marks in real time — load a model and watch them flip.

---

## Detecting running models

RAM Cat scans processes for `mlx_lm.generate`, `mlx_lm.chat`, `mlx_lm.server`, `mlx_vlm`, and `ollama`. If it finds one it shows the model name (`--model` argument) in the dropdown.

---

## Roadmap

- [ ] `py2app` bundle so non-technical users can double-click
- [ ] Homebrew formula
- [ ] Alert when wired memory exceeds a threshold (model load complete signal)
- [ ] Ollama model name resolution

---

Built on Apple M3 · 16 GB · macOS. Tested with [mlx-lm](https://github.com/ml-explore/mlx-lm).
