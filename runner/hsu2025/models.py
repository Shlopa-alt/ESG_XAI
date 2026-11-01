"""Модели Hsu et al. (2025) и модель лаборатории (MLP из постановки на с. 84–86)."""
import numpy as np
import torch
from torch import nn

torch.set_num_threads(4)

OPT = {"Adam": torch.optim.Adam, "Adagrad": torch.optim.Adagrad, "Adamax": torch.optim.Adamax,
       "NAdam": torch.optim.NAdam, "RMSprop": torch.optim.RMSprop, "SGD": torch.optim.SGD}


class LSTMReg(nn.Module):
    """LSTM -> Dropout -> Dense(1), как в разделе 3.2.1 статьи. Вход: (n, 15, 1)."""

    def __init__(self, units, dropout):
        super().__init__()
        self.lstm = nn.LSTM(1, units, batch_first=True)
        self.drop = nn.Dropout(dropout)
        self.out = nn.Linear(units, 1)

    def forward(self, x):
        h, _ = self.lstm(x)
        return self.out(self.drop(h[:, -1])).squeeze(-1)


class CNNClf(nn.Module):
    """Conv1D(k=3) -> MaxPool(2) -> Conv1D(k=3) -> MaxPool(2) -> Flatten -> Dense(32) -> sigmoid (3.2.2)."""

    def __init__(self, f1, f2, n_feat=15):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(1, f1, 3), nn.ReLU(), nn.MaxPool1d(2),
            nn.Conv1d(f1, f2, 3), nn.ReLU(), nn.MaxPool1d(2), nn.Flatten())
        with torch.no_grad():
            n = self.net(torch.zeros(1, 1, n_feat)).shape[1]
        self.head = nn.Sequential(nn.Linear(n, 32), nn.ReLU(), nn.Linear(32, 1))

    def forward(self, x):
        return self.head(self.net(x)).squeeze(-1)


class LabMLP(nn.Module):
    """Модель лаборатории, п. 3.1: h = σ(W1 X + b1), RI = W2 h + b2."""

    def __init__(self, n_in, hidden, act, dropout=0.0, n_out=1):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(n_in, hidden), {"relu": nn.ReLU(), "tanh": nn.Tanh()}[act],
                                 nn.Dropout(dropout), nn.Linear(hidden, n_out))

    def forward(self, x):
        return self.net(x).squeeze(-1)


def fit_torch(model, X, y, *, opt, lr, epochs, batch, loss="mse", wd=0.0, seed=0):
    torch.manual_seed(seed)
    X = torch.tensor(X, dtype=torch.float32)
    y = torch.tensor(y, dtype=torch.float32)
    o = OPT[opt](model.parameters(), lr=lr, weight_decay=wd)
    lf = nn.MSELoss() if loss == "mse" else nn.BCEWithLogitsLoss()
    n = len(X)
    g = torch.Generator().manual_seed(seed)
    for _ in range(epochs):
        model.train()
        perm = torch.randperm(n, generator=g)
        for i in range(0, n, batch):
            idx = perm[i:i + batch]
            o.zero_grad()
            l = lf(model(X[idx]), y[idx])
            l.backward()
            o.step()
    model.eval()
    return model


def predict_torch(model, X):
    with torch.no_grad():
        return model(torch.tensor(X, dtype=torch.float32)).numpy()


def reg_metrics(y, p):
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    return {"RMSE": float(np.sqrt(mean_squared_error(y, p))), "MAE": float(mean_absolute_error(y, p)),
            "R2": float(r2_score(y, p))}


def clf_metrics(y, p):
    from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
    tn = int(((y == 0) & (p == 0)).sum())
    fp = int(((y == 0) & (p == 1)).sum())
    return {"Accuracy": accuracy_score(y, p), "Precision": precision_score(y, p, zero_division=0),
            "Recall": recall_score(y, p, zero_division=0),
            "Specificity": tn / (tn + fp) if tn + fp else 0.0, "F1": f1_score(y, p, zero_division=0)}
