# Weather Model Comparison Project

## Overview

A Python app that fetches weather data from Meteostat and compares
GRU, LSTM, RNN, Linear Regression, and ARIMA model predictions for
Baguio City (Station ID: 98328) and Manila (Station ID: 98425).

## Target variables

- Rainfall (prcp), Temperature (tavg), Wind Speed (wspd), Pressure (pres)

## Project structure

- main.py          → Entry point
- data_fetch.py    → Meteostat API calls (Jan 1 2020 to today, dynamic)
- preprocessing.py → Cleaning, interpolation, IQR outlier removal, scaling
- models.py        → All 5 model definitions
- evaluation.py    → MSE, MAE, R², Accuracy metrics
- visualization.py → Color-coded matplotlib comparison graphs

## Key rules

- Always auto-detect GPU at startup: CUDA → MPS → CPU
- Never hardcode dates — always fetch from 2020-01-01 to today dynamically
- Deep learning models: 3 stacked layers, hidden_size=256, epochs=200
- Early stopping patience=20 on all neural network models
- ARIMA: use auto_arima (pmdarima) to auto-select best p,d,q
- Do not add new packages without updating requirements.txt

## Python version

Python 3.10+
