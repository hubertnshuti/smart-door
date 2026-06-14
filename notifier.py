"""
Notifications: email (SMTP), Telegram, and SMS (Infobip).
Sending happens in background threads — never blocks door logic.
"""
import os
import smtplib
import threading
from email.message import EmailMessage

import requests
import config


def _send_email(subject, body, image_path=None):
    if not config.EMAIL_ENABLED:
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"]    = config.EMAIL_FROM
        msg["To"]      = config.EMAIL_TO
        msg.set_content(body)
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                msg.add_attachment(
                    f.read(), maintype="image", subtype="jpeg",
                    filename=os.path.basename(image_path),
                )
        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as s:
            s.starttls()
            s.login(config.EMAIL_FROM, config.EMAIL_PASSWORD)
            s.send_message(msg)
    except Exception as e:
        print(f"[notifier] email failed: {e}")


def _send_telegram(text, image_path=None):
    if not config.TELEGRAM_ENABLED:
        return
    try:
        base = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                requests.post(
                    f"{base}/sendPhoto",
                    data={"chat_id": config.TELEGRAM_CHAT_ID, "caption": text},
                    files={"photo": f},
                    timeout=15,
                )
        else:
            requests.post(
                f"{base}/sendMessage",
                data={"chat_id": config.TELEGRAM_CHAT_ID, "text": text},
                timeout=15,
            )
    except Exception as e:
        print(f"[notifier] telegram failed: {e}")


def _send_sms(text):
    if not config.SMS_ENABLED:
        return
    try:
        requests.post(
            f"https://{config.INFOBIP_BASE_URL}/sms/2/text/advanced",
            headers={
                "Authorization": f"App {config.INFOBIP_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"messages": [{
                "from": config.SMS_SENDER,
                "destinations": [{"to": config.SMS_TO}],
                "text": text,
            }]},
            timeout=15,
        )
    except Exception as e:
        print(f"[notifier] sms failed: {e}")


def notify_unknown(image_path=None):
    """Fire-and-forget alert: unrecognized person at the lab door."""
    subject = "Lab Access Control: Unknown person detected!"
    body    = ("An unrecognized person attempted to access the lab. "
               "See the attached snapshot for details.\n"
               f"Open the dashboard: {config.DASHBOARD_URL}")
              )
    threading.Thread(target=_send_email,    args=(subject, body, image_path), daemon=True).start()
    threading.Thread(target=_send_telegram, args=(body, image_path),          daemon=True).start()
    threading.Thread(target=_send_sms,      args=(body,),                     daemon=True).start()

def notify_unauthorized(name, reg=None):
    """Alert: a known student without an active grant tried to enter."""
    who = f"{name} ({reg})" if reg else name
    subject = "Lab Access: Unauthorized student attempt"
    body = (f"{who} tried to enter the lab but has no active access grant.\n\n"
            f"Open the dashboard: {config.DASHBOARD_URL}")
    threading.Thread(target=_send_email,    args=(subject, body, None), daemon=True).start()
    threading.Thread(target=_send_telegram, args=(body, None),          daemon=True).start()
    threading.Thread(target=_send_sms,      args=(body,),               daemon=True).start()
