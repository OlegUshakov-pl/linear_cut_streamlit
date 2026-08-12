# Linear Cutting Calculator (Streamlit)

## Features

- Accounts for **end trimming** and **tool width (kerf)**
- Optimizes the number of bars (ILP + heuristic)
- Visual bar cutting diagrams
- Export results to CSV
- Works fully offline

## Installation and usage

```bash
cd linear_cut_streamlit
install.bat
.\.venv\Scripts\streamlit run app.py
```

Or manually:

```bash
cd linear_cut_streamlit
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\streamlit run app.py
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
