"""
email_sender.py — Gmail SMTP 寄信工具
讀 .env 裡的 Gmail 帳號和應用程式密碼，寄 HTML email。
"""
import os
import smtplib
import ssl
from email import policy
from email.header import Header
from email.message import EmailMessage
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / "config" / ".env")

def send_html_email(
    subject: str,
    html_body: str,
    sender: str | None = None,
    receiver: str | None = None,
    password: str | None = None,
) -> bool:
    """
    透過 Gmail SMTP 寄 HTML email。

    參數都可以 None，會從環境變數讀：
        GMAIL_SENDER, GMAIL_RECEIVER, GMAIL_APP_PASSWORD
    """
    sender = sender or os.getenv("GMAIL_SENDER")
    receiver = receiver or os.getenv("GMAIL_RECEIVER")
    password = password or os.getenv("GMAIL_APP_PASSWORD")

    if not all([sender, receiver, password]):
        print("❌ Gmail 環境變數未設定完整")
        print("   需要：GMAIL_SENDER, GMAIL_RECEIVER, GMAIL_APP_PASSWORD")
        return False

    msg = EmailMessage(policy=policy.SMTPUTF8)
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = str(Header(subject, "utf-8"))
    msg.set_content("This email requires an HTML-capable client.", charset="utf-8")
    msg.add_alternative(html_body, subtype="html", charset="utf-8")

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg, mail_options=["SMTPUTF8"])
        print(f"✅ Email sent to {receiver}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ Gmail auth failed: {e}")
        print("   檢查 GMAIL_APP_PASSWORD 是否正確（不是 Gmail 登入密碼，是應用程式密碼）")
        return False

    except Exception as e:
        print(f"❌ Email send failed: {e}")
        return False


if __name__ == "__main__":
    # 測試用：寄一封 hello world
    html = f"""
    <html>
    <body style="font-family: sans-serif;">
        <h1>Oscar Market Analyst 測試郵件</h1>
        <p>如果你看到這封信，代表 Gmail SMTP 設定成功 ✅</p>
        <p>時間：{datetime.now().isoformat()}</p>
    </body>
    </html>
    """
    send_html_email(
        subject="📧 Oscar Market Analyst — 測試郵件",
        html_body=html,
    )