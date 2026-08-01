from backend.integrations.tiktok_ads import create_campaign


def launch_ads_for_product(product_name, budget=20.0):
    campaign_id = create_campaign(name=f"{product_name} Campaign", budget=budget)
    return {"campaign_id": campaign_id, "status": "created" if campaign_id else "error"}
