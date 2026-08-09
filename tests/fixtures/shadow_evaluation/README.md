# Shadow Feature Evaluation Fixtures

Each JSONL file contains a canonical, synthetic and dry-run `shadow_feature_observation` event. The payload is a compact evidence snapshot: `observed_event_types` represents the canonical event evidence that a future writer migration must provide. These fixtures are evaluation inputs only; they never toggle a feature flag.

Expected files intentionally assert the classification and the principal blocker, where applicable. The aggregate report snapshots protect deterministic report serialization.
