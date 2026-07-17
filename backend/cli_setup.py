#!/usr/bin/env python3
"""backend.cli_setup — interactive credential setup and configuration CLI.

Run this to set up API credentials for sandboxed testing or production.

Usage:
  python -m backend.cli_setup
"""
import sys
from pathlib import Path
from typing import Optional

# Add repo to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import (
    set_credential,
    get_credential,
    validate_credentials,
    list_configured_services,
)


def print_header(text: str) -> None:
    """Print a formatted header."""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def input_credential(key: str, description: str = "") -> Optional[str]:
    """Prompt user for a credential value."""
    if description:
        print(f"\n{description}")
    prompt = f"  {key}: "
    value = input(prompt).strip()
    return value if value else None


def setup_meta() -> bool:
    """Interactive Meta Ads setup."""
    print_header("Meta Ads Configuration")

    print("""
To set up Meta Ads API access:

1. Go to https://developers.facebook.com/apps/
2. Create or select an app
3. In Settings > Basic, copy your App ID and App Secret
4. Go to Tools > Access Token Generator (Ads Manager section)
5. Generate a token with 'ads_management' permission
6. Copy your Ad Account ID from Ads Manager (act_XXXXXXXXX)
    """)

    token = input_credential("META_ACCESS_TOKEN", "Meta Access Token:")
    if not token:
        print("✗ Skipped Meta setup")
        return False

    account = input_credential("META_AD_ACCOUNT_ID", "Meta Ad Account ID:")
    if not account:
        print("✗ Skipped Meta setup")
        return False

    set_credential("META_ACCESS_TOKEN", token)
    set_credential("META_AD_ACCOUNT_ID", account)

    # Verify
    is_valid, msg = validate_credentials("meta")
    if is_valid:
        print(f"✓ Meta configured successfully")
        return True
    else:
        print(f"✗ Meta configuration incomplete: {msg}")
        return False


def setup_tiktok() -> bool:
    """Interactive TikTok Ads setup."""
    print_header("TikTok Ads Configuration")

    print("""
To set up TikTok Ads API access:

1. Go to https://business.tiktok.com/
2. Navigate to Settings > Account > API Access
3. Request API access and create an application
4. Copy your Access Token
5. Copy your Advertiser ID from your account settings
    """)

    token = input_credential("TIKTOK_ACCESS_TOKEN", "TikTok Access Token:")
    if not token:
        print("✗ Skipped TikTok setup")
        return False

    advertiser = input_credential("TIKTOK_ADVERTISER_ID", "TikTok Advertiser ID:")
    if not advertiser:
        print("✗ Skipped TikTok setup")
        return False

    set_credential("TIKTOK_ACCESS_TOKEN", token)
    set_credential("TIKTOK_ADVERTISER_ID", advertiser)

    # Verify
    is_valid, msg = validate_credentials("tiktok")
    if is_valid:
        print(f"✓ TikTok configured successfully")
        return True
    else:
        print(f"✗ TikTok configuration incomplete: {msg}")
        return False


def setup_shopify() -> bool:
    """Interactive Shopify setup."""
    print_header("Shopify Configuration")

    print("""
To set up Shopify API access:

1. Go to https://www.shopify.com/
2. Create a development store or use your existing store
3. Go to Settings > Apps and channels
4. Create a custom app for product/order management
5. Copy your API key and password
6. Your store URL is in the format: your-store-name.myshopify.com
    """)

    store_url = input_credential("SHOPIFY_STORE_URL", "Shopify Store URL (e.g., mystore.myshopify.com):")
    if not store_url:
        print("✗ Skipped Shopify setup")
        return False

    api_key = input_credential("SHOPIFY_API_KEY", "Shopify API Key:")
    if not api_key:
        print("✗ Skipped Shopify setup")
        return False

    api_password = input_credential("SHOPIFY_API_PASSWORD", "Shopify API Password:")
    if not api_password:
        print("✗ Skipped Shopify setup")
        return False

    set_credential("SHOPIFY_STORE_URL", store_url)
    set_credential("SHOPIFY_API_KEY", api_key)
    set_credential("SHOPIFY_API_PASSWORD", api_password)

    # Verify
    is_valid, msg = validate_credentials("shopify")
    if is_valid:
        print(f"✓ Shopify configured successfully")
        return True
    else:
        print(f"✗ Shopify configuration incomplete: {msg}")
        return False


def setup_supabase() -> bool:
    """Interactive Supabase setup (optional)."""
    print_header("Supabase Configuration (Optional)")

    print("""
Supabase is used for metrics and analytics persistence.
This is optional; the system will work without it but you won't
be able to persist historical data.

To set up:

1. Go to https://supabase.com/
2. Create a project
3. Copy the Project URL and Anon Key from Settings > API
    """)

    print("Skipping Supabase for now (optional)")
    return True


def status() -> None:
    """Show current configuration status."""
    print_header("Configuration Status")

    services = list_configured_services()

    for service, is_ready in sorted(services.items()):
        status_icon = "✓" if is_ready else "✗"
        status_text = "Ready" if is_ready else "Not configured"
        print(f"{status_icon} {service.upper()}: {status_text}")

    ready_count = sum(1 for ready in services.values() if ready)
    total_count = len(services)

    print(f"\n{ready_count}/{total_count} services ready for production")


def main() -> None:
    """Main CLI flow."""
    print_header("MarketOS Dropship Platform Setup")

    print("""
This wizard will help you set up credentials for API integrations.

You can run the system in DRY-RUN mode (no real spend) without any
credentials, or set up sandboxed API access for testing.

For production, you'll need:
  - Meta Ads (for Facebook/Instagram campaigns)
  - TikTok Ads (for TikTok campaigns)
  - Shopify (for product listings)

All credentials are stored locally in ~/.marketos/credentials.json
    """)

    choice = input("Continue with setup? (yes/no/skip/status) [yes]: ").strip().lower() or "yes"

    if choice in ("status", "st"):
        status()
        return

    if choice in ("skip", "n", "no"):
        print("Setup skipped")
        return

    if choice not in ("yes", "y", ""):
        print("Invalid choice")
        return

    # Run setup workflows
    services_to_setup = [
        ("meta", setup_meta),
        ("tiktok", setup_tiktok),
        ("shopify", setup_shopify),
        ("supabase", setup_supabase),
    ]

    completed = 0
    for service_name, setup_fn in services_to_setup:
        try:
            if setup_fn():
                completed += 1
        except KeyboardInterrupt:
            print("\nSetup interrupted by user")
            break
        except Exception as exc:
            print(f"✗ Error setting up {service_name}: {exc}")

    print_header("Setup Complete")
    print(f"Successfully configured {completed} services")
    print("\nTo test your configuration:")
    print("  python -m backend.cli_setup status")
    print("\nTo start the system:")
    print("  python -m orchestrator.main")


if __name__ == "__main__":
    main()
