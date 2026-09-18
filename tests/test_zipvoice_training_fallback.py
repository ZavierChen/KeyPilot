from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _scaling_module():
    torch = pytest.importorskip("torch")
    path = Path(__file__).parents[1] / "work" / "ZipVoice" / "zipvoice" / "models" / "modules" / "scaling.py"
    if not path.is_file():
        pytest.skip("Optional local ZipVoice training checkout is not distributed with the application")
    spec = importlib.util.spec_from_file_location("zipvoice_stable_scaling", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return torch, module


def test_swoosh_fallback_has_finite_extreme_gradients():
    torch, scaling = _scaling_module()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    x = torch.tensor([-1000.0, -100.0, 0.0, 100.0, 1000.0], device=device, requires_grad=True)
    (scaling.SwooshLForward(x) + scaling.SwooshRForward(x)).sum().backward()
    assert torch.isfinite(x.grad).all()


def test_swoosh_fallback_matches_stable_definition():
    torch, scaling = _scaling_module()
    x = torch.linspace(-20.0, 20.0, 1001)
    expected_l = torch.nn.functional.softplus(x - 4.0) - 0.08 * x - 0.035
    expected_r = torch.nn.functional.softplus(x - 1.0) - 0.08 * x - 0.313261687
    assert torch.allclose(scaling.SwooshLForward(x), expected_l)
    assert torch.allclose(scaling.SwooshRForward(x), expected_r)
