# THIS IS THE OFFICIAL REPOSITORY OF THE SYSTEM FOR THESIS TITLED: EVALUATING THE PERFORMANCE OF GATED RECURRENT UNITS FOR MULTI-PARAMETER WEATHER FORECASTING

# IN PARTIAL FULFILMENT OF THE REQUIREMENTS FOR THE DEGREEE: BACHELOR OF SCIENCE IN COMPUTER SCIENCE

# UNIVERSITY OF THE CORDILLERAS, GOVERNOR PACK ROAD, BAGUIO CITY, BENGUET, PHILIPPINES
# COLLEGE OF COMPUTER SCIENCE AND INFORMATION TECHNOLOGY (CITCS)

# MEMBERS:
# EZEKIEL MENDOZA CASTRO
# DEVIN JOSHUA SOCALO MILLAN
# JERIC ESCAÑO MONDOÑEDO


This System Compares **GRU, LSTM, SimpleRNN, Linear Regression, and ARIMA** for predicting
rainfall, temperature, wind speed, and pressure at **Baguio City** and **Manila**
using Meteostat daily weather data.

---

## Requirements

Before you begin, make sure the following are installed on your machine:

| Tool | Download Link |
|---|---|
| Python 3.10 – 3.13 | https://www.python.org/downloads/ |
| Git | https://git-scm.com/downloads |
| VS Code | https://code.visualstudio.com/ |

> **GPU (optional but recommended):** If you have an NVIDIA GPU, install the
> [CUDA Toolkit](https://developer.nvidia.com/cuda-downloads) so training runs faster.

---

## Step-by-Step Setup

### Step 1 — Clone the repository

Open a terminal (PowerShell or Git Bash) and run:

```bash
git clone https://github.com/EzekelCastro/Thesis-GRU-Evaluation-in-Weather-Forecasting.git
```

Then open the cloned folder in VS Code:

```bash
cd Thesis-GRU-Evaluation-in-Weather-Forecasting
code .
```

---

### Step 2 — Open the VS Code terminal

Inside VS Code, open the integrated terminal:
- **Windows:** `Ctrl + `` ` (backtick) or go to **Terminal → New Terminal**

All commands from this point are typed in that terminal.

---

### Step 3 — Create a virtual environment

```bash
python -m venv .venv
```

Then activate it:

- **PowerShell:**
  ```powershell
  .venv\Scripts\Activate.ps1
  ```
- **Git Bash / Command Prompt:**
  ```bash
  .venv\Scripts\activate
  ```

> You should see `(.venv)` at the start of your terminal prompt when it's active.

---

### Step 4 — Install dependencies

```bash
pip install -r requirements.txt
```

---

### Step 5 — Install PyTorch

**Option A — You have an NVIDIA GPU (recommended):**

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu126
```

> This downloads ~2 GB. Wait for it to finish.

**Option B — CPU only (no GPU):**

```bash
pip install torch
```

---

### Step 6 — Run the web app

```bash
python -m streamlit run app.py
```

Streamlit will print a local URL like:

```
Local URL: http://localhost:8501
```

Open that link in your browser. You should see the app's welcome screen.

---

### Step 7 — Using the app

1. In the **sidebar**, choose your date range, stations, and models.
2. Click **Run Analysis**.
3. Wait for training to finish (progress is shown live).
4. Switch between the **Predictions** and **Metrics** tabs to explore results.

> Training all 5 models on GPU takes ~2–5 minutes.
> On CPU it takes ~15–30 minutes depending on your machine.

---

## Alternative: Run via command line (no browser)

If you prefer the terminal-only version, run:

```bash
python main.py
```

Results are saved as PNG files inside the `plots/` folder.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `python` not found | Use `python3` instead, or check your Python installation |
| `.venv\Scripts\Activate.ps1` blocked | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` in PowerShell |
| GPU not detected | Make sure you installed the CUDA version of PyTorch (Step 5 Option A) |
| `meteostat` returns no data | Check your internet connection; Meteostat requires network access |
| Port 8501 already in use | Run `python -m streamlit run app.py --server.port 8502` |

---

## Project Structure

```
├── app.py              # Streamlit web UI
├── main.py             # Command-line entry point
├── data_fetch.py       # Meteostat data fetching
├── preprocessing.py    # Cleaning, scaling, sequence generation
├── models.py           # GRU, LSTM, RNN, Linear Regression, ARIMA
├── evaluation.py       # Metrics: Accuracy, MSE, MAE, R²
├── visualization.py    # Matplotlib plots (used by main.py)
├── requirements.txt    # Python dependencies
└── plots/              # Generated PNG outputs (git-ignored)
```
