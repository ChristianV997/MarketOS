# Commerce operations release packet

This directory is the **operator-facing information architecture** for the
existing MarketOS commerce-operations cycle. It does not add a second packet
schema, packet builder, scorer, identity registry, fingerprint field,
`source_family`, or alias-collapse authority.

The packet **is** the cycle report:

```text
evaluation.commerce.commerce_operations_cycle.build_commerce_operations_cycle(...).to_dict()
```

The client-safe file is a **projection of that dict**, not a second packet.

Windows operators and humans should read
[`OPERATOR_RELEASE_PACKET.md`](OPERATOR_RELEASE_PACKET.md). The cycle CLI
(`scripts/run_commerce_operations_cycle.py`) is the only producer. The
commerce MVP cockpit / Windows runner consume `scripts/run_commerce_mvp_slice.py`
instead; they do not consume this cycle.

This output is planning evidence. It is never launch, ads, order, payment,
publish, or provider authority.
