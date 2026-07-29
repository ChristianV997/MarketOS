import numpy as np
from backend.simulation.reality_gap import RealityGapEngine


def simulate_series(length=50, drift=0.0):
    base = np.linspace(1.0, 2.0 + drift, length)
    noise = np.random.normal(0, 0.1, length)
    return base + noise


def test_reality_gap_convergence():
    # Keep the convergence assertion reproducible across Python/NumPy builds.
    # The engine receives pre-generated series, so tuning cannot influence the
    # random draw itself.
    np.random.seed(0)
    engine = RealityGapEngine(window=50)

    sim_series = simulate_series(60, drift=0.2)
    real_series = simulate_series(60, drift=0.0)

    gaps = []
    params = []

    for s, r in zip(sim_series, real_series):
        gap = engine.update(s, r)
        engine.tune()
        if gap is not None:
            gaps.append(gap)
            params.append(engine.params.copy())

    assert len(gaps) > 20

    first_half = np.mean(gaps[:10])
    last_half = np.mean(gaps[-10:])

    # Fail if gap is getting worse
    assert last_half <= first_half + 0.2, "Reality gap increasing"

    # Parameter stability check
    noise_vals = [p['noise_scale'] for p in params]
    variance = np.var(noise_vals)

    assert variance < 0.1, "Parameter oscillation too high"


def test_reality_gap_tuning_is_bounded():
    engine = RealityGapEngine(window=30)

    for _ in range(20):
        engine.update(2.0, 0.9)
        prev = engine.params["noise_scale"]
        engine.tune()
        curr = engine.params["noise_scale"]
        assert abs(curr - prev) <= engine.max_step["noise_scale"] + 1e-9
