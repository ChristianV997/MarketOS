"""Tests for backend.patterns.errors — the MarketOS error taxonomy."""
import pytest

from backend.patterns.errors import (
    ConfigurationError,
    MarketOSError,
    RetryableError,
    SupplierQuoteError,
    ValidationError,
)


class TestErrorTaxonomy:
    def test_all_inherit_from_marketos_error(self):
        for cls in (RetryableError, ConfigurationError, SupplierQuoteError, ValidationError):
            assert issubclass(cls, MarketOSError)

    def test_retryable_error_flags(self):
        err = RetryableError("timeout")
        assert err.retryable is True
        assert err.severity == "warning"

    def test_configuration_error_flags(self):
        err = ConfigurationError("missing token")
        assert err.retryable is False
        assert err.severity == "fatal"

    def test_supplier_quote_error_is_retryable(self):
        err = SupplierQuoteError("spocket timeout")
        assert isinstance(err, RetryableError)
        assert err.retryable is True
        assert err.service == "supplier"

    def test_validation_error_not_retryable(self):
        err = ValidationError("negative price")
        assert err.retryable is False
        assert err.severity == "warning"

    def test_service_override(self):
        err = RetryableError("boom", service="meta")
        assert err.service == "meta"

    def test_message_preserved(self):
        err = ConfigurationError("META_ACCESS_TOKEN missing")
        assert "META_ACCESS_TOKEN missing" in str(err)

    def test_catch_all_via_base_class(self):
        caught = []
        for cls in (RetryableError, ConfigurationError, SupplierQuoteError, ValidationError):
            try:
                raise cls("x")
            except MarketOSError as e:
                caught.append(type(e))
        assert len(caught) == 4
