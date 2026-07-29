import logging
import os
import requests

_log = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    except Exception as exc:
        _log.warning("telegram_notify_failed error=%s", exc)


def send_slack(message):
    if not SLACK_WEBHOOK:
        return
    try:
        requests.post(SLACK_WEBHOOK, json={"text": message}, timeout=10)
    except Exception as exc:
        _log.warning("slack_notify_failed error=%s", exc)


def format_alert(summary):
    return (
        f"🚨 SYSTEM ALERT\n"
        f"ROAS: {summary['avg_roas']}\n"
        f"Error: {summary['prediction_error']}\n"
        f"Improvement: {summary['improvement_rate']}\n"
        f"Novelty: {summary['novelty_weight']}\n"
        f"Diversity: {summary['diversity']}\n"
    )


def check_alerts(summary):
    alerts = []

    if summary["improvement_rate"] < 0:
        alerts.append("Learning stalled")

    if summary["diversity"] < 0.1:
        alerts.append("Diversity collapse")

    if abs(summary["prediction_error"]) > 0.5:
        alerts.append("Prediction error spike")

    return alerts


def process_alerts(summary):
    alerts = check_alerts(summary)
    if not alerts:
        return

    message = format_alert(summary) + "\n" + "\n".join(alerts)

    send_telegram(message)
    send_slack(message)

    print(message)
