"""Tests for backend.patterns.safe_call."""
import logging

import pytest

from backend.patterns.safe_call import safe_call


class TestSafeCall:
    def test_success_passthrough(self):
        @safe_call(default="")
        def fn():
            return "value"

        assert fn() == "value"

    def test_exception_returns_default(self):
        @safe_call(default="")
        def fn():
            raise ValueError("boom")

        assert fn() == ""

    def test_default_false(self):
        @safe_call(default=False)
        def fn():
            raise RuntimeError("nope")

        assert fn() is False

    def test_default_factory_gives_fresh_instance(self):
        @safe_call(default=dict)
        def fn():
            raise RuntimeError("nope")

        d1 = fn()
        d2 = fn()
        assert d1 == {} and d2 == {}
        assert d1 is not d2  # fresh dict each call, not a shared mutable default

    def test_args_and_kwargs_passed_through(self):
        @safe_call(default=-1)
        def add(a, b, c=0):
            return a + b + c

        assert add(1, 2, c=3) == 6

    def test_logs_exception(self, caplog):
        @safe_call(default=None)
        def _will_fail():
            raise ValueError("kaboom")

        with caplog.at_level(logging.ERROR):
            _will_fail()
        assert any("_will_fail failed" in r.message for r in caplog.records)

    def test_custom_logger_used(self):
        custom = logging.getLogger("custom.test.logger")
        events = []
        custom.exception = lambda msg: events.append(msg)

        @safe_call(default=None, logger=custom)
        def fn():
            raise RuntimeError("x")

        fn()
        assert len(events) == 1
        assert "fn failed" in events[0]

    def test_preserves_function_name(self):
        @safe_call(default=None)
        def create_campaign():
            return "ok"

        assert create_campaign.__name__ == "create_campaign"
