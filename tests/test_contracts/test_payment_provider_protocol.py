from backend.contracts.adapters import AdapterHealth, PaymentProvider, SidecarContext
from backend.integrations.mercado_pago_mx import MercadoPagoMxPaymentAdapter
from backend.integrations.stripe_mx import StripeMxPaymentAdapter


def test_stripe_mx_adapter_satisfies_payment_provider_protocol():
    adapter: PaymentProvider = StripeMxPaymentAdapter()
    assert isinstance(adapter.health(), AdapterHealth)
    assert isinstance(adapter.estimate_fee(100.0), dict)
    assert isinstance(adapter.list_payments(), list)
    assert isinstance(adapter.list_refunds("pi_1"), list)
    assert isinstance(adapter.handle_webhook({}, context=SidecarContext()), dict)


def test_mercado_pago_mx_adapter_satisfies_payment_provider_protocol():
    adapter: PaymentProvider = MercadoPagoMxPaymentAdapter()
    assert isinstance(adapter.health(), AdapterHealth)
    assert isinstance(adapter.estimate_fee(100.0), dict)
    assert isinstance(adapter.list_payments(), list)
    assert isinstance(adapter.list_refunds("pay_1"), list)
    assert isinstance(adapter.handle_webhook({}, context=SidecarContext()), dict)
