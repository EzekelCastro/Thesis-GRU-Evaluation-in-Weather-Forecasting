"""
models.py
Defines, builds, trains, and runs inference for all five models:
  • GRU          — 3-layer bidirectional, hidden=256, dropout=0.2
  • LSTM         — 3-layer bidirectional, hidden=256, dropout=0.2
  • SimpleRNN    — 3-layer unidirectional, hidden=256, dropout=0.2
  • LinearRegression (sklearn, sequences flattened)
  • ARIMA        — per-column auto_arima (AIC, seasonal=False)

GPU acceleration: CUDA > Apple MPS > CPU, auto-detected at import time.
"""

import copy
import warnings
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.linear_model import LinearRegression
from pmdarima import auto_arima

warnings.filterwarnings("ignore")


# ── Device detection ───────────────────────────────────────────────────────────

def _detect_device() -> torch.device:
    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        print(f"[Device] CUDA GPU detected: {name}")
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        print("[Device] Apple MPS detected.")
        return torch.device("mps")
    print("[Device] No GPU found - running on CPU.")
    return torch.device("cpu")


DEVICE: torch.device = _detect_device()


# ── Deep learning backbone ─────────────────────────────────────────────────────

class WeatherRNN(nn.Module):
    """
    Shared backbone for GRU / LSTM / SimpleRNN.
    Stacks `num_layers` recurrent layers with dropout, then maps the last
    hidden state through a two-layer MLP to `output_size` targets.
    """

    def __init__(
        self,
        input_size: int,
        hidden_size: int,
        output_size: int,
        num_layers: int,
        dropout: float,
        bidirectional: bool,
        rnn_type: str,  # 'GRU' | 'LSTM' | 'RNN'
    ) -> None:
        super().__init__()
        self.rnn_type = rnn_type

        rnn_cls = {"GRU": nn.GRU, "LSTM": nn.LSTM, "RNN": nn.RNN}[rnn_type]

        # dropout only applies between layers (not on the final layer output),
        # so we disable it when num_layers == 1 to silence PyTorch's warning.
        rnn_dropout = dropout if num_layers > 1 else 0.0

        self.rnn = rnn_cls(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=rnn_dropout,
            bidirectional=bidirectional,
            batch_first=True,
        )

        direction_factor = 2 if bidirectional else 1
        self.head = nn.Sequential(
            nn.Linear(hidden_size * direction_factor, 128),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(128, output_size),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, input_size)
        out, _ = self.rnn(x)       # out: (batch, seq_len, hidden * dirs)
        return self.head(out[:, -1, :])   # last time-step → predictions


# ── Factory ────────────────────────────────────────────────────────────────────

def build_model(
    model_type: str,
    input_size: int,
    output_size: int,
    hidden_size: int = 256,
    num_layers: int = 3,
    dropout: float = 0.2,
) -> nn.Module:
    """
    Construct and return a WeatherRNN moved to DEVICE.
    model_type ∈ {'GRU', 'LSTM', 'SimpleRNN'}
    GRU and LSTM get bidirectional=True; SimpleRNN stays unidirectional
    (plain tanh-RNN is numerically less stable in bidirectional stacks).
    """
    rnn_map = {"GRU": "GRU", "LSTM": "LSTM", "SimpleRNN": "RNN"}
    rnn_type = rnn_map.get(model_type, "RNN")
    bidirectional = model_type in ("GRU", "LSTM")

    model = WeatherRNN(
        input_size=input_size,
        hidden_size=hidden_size,
        output_size=output_size,
        num_layers=num_layers,
        dropout=dropout,
        bidirectional=bidirectional,
        rnn_type=rnn_type,
    )
    return model.to(DEVICE)


# ── Training loop ──────────────────────────────────────────────────────────────

def train_deep_model(
    model: nn.Module,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    epochs: int = 200,
    batch_size: int = 32,
    patience: int = 20,
    lr: float = 1e-3,
) -> nn.Module:
    """
    Train with Adam + ReduceLROnPlateau + early stopping.
    Gradient clipping (norm 1.0) stabilises training on long sequences.
    Best weights are restored before returning.
    """
    X_tr = torch.from_numpy(X_train).to(DEVICE)
    y_tr = torch.from_numpy(y_train).to(DEVICE)
    X_v = torch.from_numpy(X_val).to(DEVICE)
    y_v = torch.from_numpy(y_val).to(DEVICE)

    loader = DataLoader(
        TensorDataset(X_tr, y_tr),
        batch_size=batch_size,
        shuffle=True,
        drop_last=False,
    )

    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=5
    )
    criterion = nn.MSELoss()

    best_val_loss = float("inf")
    best_state: dict | None = None
    patience_ctr = 0

    for epoch in range(1, epochs + 1):
        # ── Training pass ──
        model.train()
        for X_batch, y_batch in loader:
            optimizer.zero_grad()
            loss = criterion(model(X_batch), y_batch)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

        # ── Validation pass ──
        model.eval()
        with torch.no_grad():
            val_loss = criterion(model(X_v), y_v).item()
        scheduler.step(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            patience_ctr = 0
        else:
            patience_ctr += 1

        if patience_ctr >= patience:
            print(f"      Early stop at epoch {epoch}  (best val MSE: {best_val_loss:.6f})")
            break

        if epoch % 25 == 0:
            print(f"      Epoch {epoch:>3}/{epochs}  val_MSE={val_loss:.6f}")

    # Restore best checkpoint
    if best_state is not None:
        model.load_state_dict({k: v.to(DEVICE) for k, v in best_state.items()})

    return model


def predict_deep(model: nn.Module, X: np.ndarray) -> np.ndarray:
    """Run inference and return a (N, n_outputs) numpy array."""
    model.eval()
    with torch.no_grad():
        preds = model(torch.from_numpy(X).to(DEVICE)).cpu().numpy()
    return preds


# ── Linear Regression ─────────────────────────────────────────────────────────

def train_linear_regression(
    X_train: np.ndarray, y_train: np.ndarray
) -> LinearRegression:
    """Flatten the sequence dimension and fit a multivariate LinearRegression."""
    lr = LinearRegression()
    lr.fit(X_train.reshape(len(X_train), -1), y_train)
    return lr


def predict_linear_regression(
    model: LinearRegression, X: np.ndarray
) -> np.ndarray:
    return model.predict(X.reshape(len(X), -1))


# ── ARIMA ─────────────────────────────────────────────────────────────────────

def train_all_arima(train_df, columns: list) -> dict:
    """
    Fit one auto_arima model per target column on the (scaled) training series.
    Uses AIC criterion with stepwise search, max_p=max_q=5, seasonal=False.
    """
    models = {}
    for col in columns:
        print(f"      Fitting ARIMA for '{col}' ...", end=" ", flush=True)
        m = auto_arima(
            train_df[col].values,
            seasonal=False,
            stepwise=True,
            max_p=5,
            max_q=5,
            information_criterion="aic",
            error_action="ignore",
            suppress_warnings=True,
        )
        print(f"order={m.order}")
        models[col] = m
    return models


def predict_arima(
    arima_models: dict,
    test_df_len: int,
    seq_len: int,
    columns: list,
    test_series: np.ndarray | None = None,
) -> np.ndarray:
    """
    Rolling 1-step-ahead ARIMA forecast aligned with y_test.

    When test_series (shape: test_df_len × n_cols, scaled) is supplied, each
    column's model is deep-copied then updated with test[0:seq_len] (matching
    the context window DL models see), followed by n_out rolling 1-step-ahead
    predictions where the true test value is fed back after each step.  This
    prevents the long-horizon mean-reversion / sign-divergence artefact.

    The originals in arima_models are never modified (safe for the 7-day
    forecast which calls update() on them later).

    Falls back to bulk forecasting + [0, 1] clipping when rolling fails.
    Returns shape (test_df_len - seq_len, n_cols).
    """
    n_out = test_df_len - seq_len
    col_preds = []

    for j, col in enumerate(columns):
        preds_for_col: list[float] = []

        if test_series is not None:
            try:
                m = copy.deepcopy(arima_models[col])
                # Provide the same context window the DL models see at step 0
                m.update(test_series[:seq_len, j].tolist(), refit=False)
                # Rolling 1-step-ahead through the full evaluation window
                for i in range(n_out):
                    fc = float(np.clip(m.predict(n_periods=1)[0], 0.0, 1.0))
                    preds_for_col.append(fc)
                    m.update([float(test_series[seq_len + i, j])], refit=False)
            except Exception:
                # Fallback: bulk forecast with clipping
                preds_for_col = list(
                    np.clip(
                        arima_models[col].predict(n_periods=test_df_len)[seq_len:],
                        0.0, 1.0,
                    )
                )
        else:
            preds_for_col = list(
                np.clip(
                    arima_models[col].predict(n_periods=test_df_len)[seq_len:],
                    0.0, 1.0,
                )
            )

        col_preds.append(np.array(preds_for_col, dtype=np.float32))

    return np.column_stack(col_preds).astype(np.float32)
