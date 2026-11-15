"""Протокол методов из статей: метод — только модель (make_model), остальное — protocol.run.
Данные — синтетический шум с заложенной связью (генератор с seed), не данные компаний (правило 7).

Запуск в окружении runner: cd runner/methods && python -m pytest test_protocol.py
"""

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
UTF8 = {**os.environ, "PYTHONUTF8": "1",
        "PYTHONPATH": os.pathsep.join(p for p in (str(HERE), os.environ.get("PYTHONPATH", "")) if p)}

# так выглядит метод, который Qwen пишет по статье: небольшая LSTM на torch, входы — последовательность
LSTM_METHOD = '''
import numpy as np
import torch
from torch import nn

TITLE = "[LSTM из статьи]"


class _Net(nn.Module):
    def __init__(self, hidden):
        super().__init__()
        self.lstm = nn.LSTM(1, hidden, batch_first=True)
        self.out = nn.Linear(hidden, 1)

    def forward(self, x):
        h, _ = self.lstm(x.unsqueeze(-1))
        return self.out(h[:, -1]).squeeze(-1)


class Model:
    def __init__(self, params, seed):
        torch.manual_seed(seed)
        self.net = _Net(int(params.get("hidden", 8)))
        self.epochs = int(params.get("epochs", 60))

    def fit(self, x, y):
        xt, yt = torch.tensor(x, dtype=torch.float32), torch.tensor(y, dtype=torch.float32)
        opt = torch.optim.Adam(self.net.parameters(), lr=0.03)
        for _ in range(self.epochs):
            opt.zero_grad()
            loss = ((self.net(xt) - yt) ** 2).mean()
            loss.backward()
            opt.step()
        return self

    def predict(self, x):
        with torch.no_grad():
            return self.net(torch.tensor(x, dtype=torch.float32)).numpy()


def make_model(params, seed):
    return Model(params, seed)


if __name__ == "__main__":
    import protocol
    raise SystemExit(protocol.run(make_model, TITLE))
'''


def _data(tmp: Path) -> Path:
    rng = np.random.default_rng(3)
    n_c, n_y = 30, 8
    x1, x2 = rng.normal(size=n_c * n_y), rng.normal(size=n_c * n_y)
    path = tmp / "panel.csv"
    pd.DataFrame({"[страна]": np.repeat([f"[страна {i}]" for i in range(n_c)], n_y), "[x1]": x1, "[x2]": x2,
                  "[y]": 0.9 * x1 + 0.2 * rng.normal(size=n_c * n_y)}).to_csv(path, index=False)
    return path


def _run(tmp: Path, method: Path, params: dict) -> dict:
    res = tmp / "res"
    done = subprocess.run(
        [sys.executable, str(method), str(tmp), str(res), "--data", str(_data(tmp)), "--params", json.dumps(params),
         "--experiment", "EXP-000", "--dataset", "DS-00"],
        cwd=HERE, env=UTF8, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(next(res.glob("*/run.json")).read_text(encoding="utf-8"))


def test_method_from_article_runs_under_the_protocol(tmp_path: Path) -> None:
    method = tmp_path / "method.py"  # как исполнитель: файл метода — отдельно, протокол — из библиотеки
    method.write_text(LSTM_METHOD, encoding="utf-8")
    run = _run(tmp_path, method, {"target": "[y]", "features": ["[x1]", "[x2]"], "group": "[страна]",
                                  "splits": 4, "seed": 1, "hidden": 6, "epochs": 80})
    s = run["summary"]
    # заложенная связь видна на странах вне обучения, на перемешанной цели — нет
    assert s["model_r2_mean"] > 0.6, s
    assert s["placebo_r2_max"] < 0.3, s
    assert s["ridge_r2_mean"] > 0.6 and s["groups"] == 30 and s["method"] == "[LSTM из статьи]"
    assert s["hyperparameters"] == {"hidden": 6, "epochs": 80}
    # всё для повтора (правило 3): seed, деление, группа, sha256 среза и окружения
    assert run["seeds"] == {"split": 1, "splits": 4, "group": "[страна]"}
    assert run["dataset"]["sha256"] and run["env_lock_sha256"]


def test_broken_model_does_not_pass_as_a_result(tmp_path: Path) -> None:
    # модель, которая предсказывает не то число строк, — NaN в R², а не «отличный результат»
    method = tmp_path / "method.py"
    method.write_text(LSTM_METHOD.replace("return self.net(torch.tensor(x, dtype=torch.float32)).numpy()",
                                          "return np.zeros(3)"), encoding="utf-8")
    run = _run(tmp_path, method, {"target": "[y]", "features": ["[x1]", "[x2]"], "splits": 3, "epochs": 2})
    s = run["summary"]
    assert s["verdict"] == "не лучше среднего" and math.isnan(s["model_r2_mean"])
