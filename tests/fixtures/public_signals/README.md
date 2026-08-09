# Public Signal Fixtures

`rss_sample.xml` is a synthetic public RSS response with two usable records, one duplicate, and one partial record. It intentionally contains only `example.test` links and fixture publishers.

The expected files protect deterministic normalization, canonical event mapping, blocked-network behavior, stale-cache behavior, and the advisory replay audit. No fixture represents demand, revenue, conversion, profitability, or launch evidence.

Fixture ingestion does not make an HTTP request. Real RSS access is tested only through injected failing fetchers; CI never contacts the public endpoint.
