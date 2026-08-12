[Cutting Calculator](./image.png)

# Linear Cutting Calculator (Streamlit)

Modern replacement for the old Excel linear cutting stock calculator (version Bakanov 1.03).
Available in three languages: **English**, **Russian**, **Polish**.

## Language versions

| File      | Language | UI |
|-----------|----------|-----|
| `app.py`  | English  | English |
| `app_ru.py` | Russian | Русский |
| `app_pl.py` | Polish  | Polski |

## Features

- Accounts for **end trimming** and **tool width (kerf)**
- Optimizes the number of bars (ILP + heuristic)
- Visual bar cutting diagrams
- Export results to CSV
- Works fully offline

## Installation

```bash
install.bat
```

The script creates a virtual environment in `.venv`, upgrades pip
and installs all dependencies from `requirements.txt`.

## Usage

| Script        | Language | App file |
|---------------|----------|----------|
| `start.bat`   | English  | `app.py` |
| `start_ru.bat`| Russian  | `app_ru.py` |
| `start_pl.bat`| Polish   | `app_pl.py` |

Double-click the desired script, or run manually:

```bash
.\.venv\Scripts\streamlit run app.py        # English
.\.venv\Scripts\streamlit run app_ru.py     # Russian
.\.venv\Scripts\streamlit run app_pl.py     # Polish
```

## Parameters

| Parameter | Description |
|-----------|-------------|
| Bar length | Standard profile length |
| End trim | Cut from the end of the bar |
| Tool width | Kerf — added to each piece |
| Minimum useful remnant | Informational only |

## Optimization methods

- **Auto** — chooses ILP or fast FFD depending on task size
- **ILP** — mathematical optimization (PuLP + CBC), close to optimal
- **First Fit Decreasing** — very fast heuristic algorithm

## Example from the old Excel

In the sidebar there is a "Load example from old Excel" button — fills in data from the V1.03 file (bar 2000 mm, kerf 5 mm).

---

Version 1.0
