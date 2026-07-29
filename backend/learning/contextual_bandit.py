"""Backend wrapper for the LinUCB contextual bandit from core/.

Provides a single module-level bandit instance pre-configured with the
feature vector used by the execution loop, and a convenience function
``select_arm`` / ``record_reward`` for easy wiring.
"""
import numpy as np

from core.contextual_bandit import LinUCB

# Feature vector: [velocity, acceleration, trend, capital_norm, regime_int]
_N_FEATURES = 5
_ARMS = ["scale", "hold", "pause", "launch_new", "kill"]

# Singleton instance shared across the backend process
_bandit: LinUCB = LinUCB(n_features=_N_FEATURES, arms=_ARMS, alpha=1.0)


def _encode_context(state) -> list:
    """Extract a numeric feature vector from a SystemState-like object."""
    history = [r.get("roas", 0.0) for r in getattr(state.event_log, "rows", [])[-10:]]

    def _velocity(h):
        if len(h) < 2:
            return 0.0
        return float(h[-1] - h[0]) / max(len(h) - 1, 1)

    def _acceleration(h):
        if len(h) < 3:
            return 0.0
        mid = len(h) // 2
        first_half = h[:mid] or [0.0]
        second_half = h[mid:] or [0.0]
        return float(sum(second_half) / len(second_half) - sum(first_half) / len(first_half))

    _REGIME_MAP = {"growth": 1, "stable": 0, "volatile": -1, "decay": -2, "unknown": 0}

    vel = _velocity(history)
    acc = _acceleration(history)
    trend = float(getattr(state, "trend", 0.0))
    capital = min(1.0, max(-1.0, (getattr(state, "capital", 1000.0) - 1000.0) / 1000.0))
    regime_raw = getattr(state, "detected_regime", "unknown")
    regime_int = float(_REGIME_MAP.get(regime_raw, 0)) / 2.0  # normalise to [-1, 1]

    return [vel, acc, trend, capital, regime_int]


def select_arm(state) -> str:
    """Choose the best action arm given the current system state context."""
    x = _encode_context(state)
    return _bandit.choose(x)


def record_reward(arm: str, state, reward: float) -> None:
    """Update the LinUCB parameters after observing a reward."""
    x = _encode_context(state)
    _bandit.update(arm, x, reward)


def bandit_instance() -> LinUCB:
    """Expose the underlying LinUCB for serialisation / inspection."""
    return _bandit


# ─────────────────────────────────────────────────────────────────────────────
# Per-product contextual bandit for variant/product scoring (Phase 3)
# ─────────────────────────────────────────────────────────────────────────────

from collections import deque


class ProductContextualBandit:
    """LinUCB extended for per-product/variant scoring with product context features."""

    def __init__(self, n_features: int = 10, alpha: float = 1.0, max_history: int = 500):
        """
        Args:
            n_features: feature dimension for product context
            alpha: exploration-exploitation trade-off
            max_history: max decisions to retain for reward statistics
        """
        self.n_features = n_features
        self.alpha = alpha
        self.max_history = max_history
        self._A_global = np.eye(n_features)
        self._b_global = np.zeros((n_features, 1))
        self._reward_history: deque = deque(maxlen=max_history)

    def _feature_vector(self, product_id: str, category: str = "",
                       hook_id: str = "", audience_id: str = "",
                       extra_features: dict = None) -> np.ndarray:
        """Construct normalized feature vector from product context."""
        features = np.zeros(self.n_features)

        # Hash categorical features into feature dimensions
        if product_id:
            prod_hash = hash(product_id) % (self.n_features - 3)
            features[prod_hash] += 0.5

        cat_hash = hash(category or "unknown") % (self.n_features - 3)
        features[(cat_hash + 1) % self.n_features] += 0.7

        hook_hash = hash(hook_id or "default") % (self.n_features - 3)
        features[(hook_hash + 2) % self.n_features] += 0.6

        aud_hash = hash(audience_id or "broad") % (self.n_features - 3)
        features[(aud_hash + 3) % self.n_features] += 0.5

        # Extra numeric features
        if extra_features:
            for i, val in enumerate(extra_features.values()):
                if i < 2:
                    features[self.n_features - 2 + i] += float(val) * 0.1

        # L2 normalize
        norm = np.linalg.norm(features)
        if norm > 0:
            features /= norm

        return features

    def score(self, product_id: str, category: str = "", hook_id: str = "",
              audience_id: str = "", extra_features: dict = None) -> float:
        """Compute UCB score for a product: θᵀx + α√(xᵀA⁻¹x)."""
        x = self._feature_vector(product_id, category, hook_id, audience_id,
                                 extra_features)
        x_col = x.reshape(-1, 1)

        try:
            A_inv = np.linalg.inv(self._A_global)
            theta = A_inv @ self._b_global
            mean_score = float((theta.T @ x_col).item())
            exploration = self.alpha * float(np.sqrt((x_col.T @ A_inv @ x_col).item()))
        except np.linalg.LinAlgError:
            if self._reward_history:
                rewards = [r for _, r in self._reward_history]
                mean_score = float(np.mean(rewards))
                exploration = 0.1 * float(np.std(rewards) or 0.1)
            else:
                mean_score = 0.0
                exploration = 0.1

        return mean_score + exploration

    def update(self, product_id: str, reward: float, category: str = "",
               hook_id: str = "", audience_id: str = "",
               extra_features: dict = None):
        """Update bandit with observed reward."""
        x = self._feature_vector(product_id, category, hook_id, audience_id,
                                 extra_features)
        x_col = x.reshape(-1, 1)
        self._A_global += x_col @ x_col.T
        self._b_global += reward * x_col
        self._reward_history.append((x, reward))

    def reward_stats(self) -> dict:
        """Return mean, std, count of observed rewards."""
        if not self._reward_history:
            return {"mean": 0.0, "std": 1.0, "count": 0}
        rewards = [r for _, r in self._reward_history]
        return {
            "mean": float(np.mean(rewards)),
            "std": float(np.std(rewards) or 1.0),
            "count": len(rewards),
        }


# Singleton instance for per-product scoring
product_bandit = ProductContextualBandit(n_features=10, alpha=1.0)
