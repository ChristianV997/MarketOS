from backend.ecommerce.shopify_readonly.pii import hash_pii, redact_customer_payload, redact_name


def test_pii_hashes_are_deterministic_and_payload_removes_raw_values():
    assert hash_pii("Ada@Example.test") == hash_pii(" ada@example.test ")
    value = redact_customer_payload({"email": "ada@example.test", "phone": "555", "first_name": "Ada", "last_name": "Lovelace", "address": "secret"})
    assert "email" not in value and "phone" not in value and "address" not in value
    assert value["email_hash"] and value["name_redacted"] == "A*** L***"
    assert redact_name("") == "[redacted]"
