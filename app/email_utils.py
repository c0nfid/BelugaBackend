import os
from pathlib import Path

from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from dotenv import load_dotenv

load_dotenv()

conf = ConnectionConfig(
    MAIL_USERNAME=os.getenv("MAIL_USERNAME", "noreply@example.com"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD", "password"),
    MAIL_FROM=os.getenv("MAIL_FROM", "noreply@example.com"),
    MAIL_PORT=int(os.getenv("MAIL_PORT", 465)),
    MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.example.com"),
    MAIL_STARTTLS=os.getenv("MAIL_STARTTLS", "False") == "True",
    MAIL_SSL_TLS=os.getenv("MAIL_SSL_TLS", "True") == "True",
    USE_CREDENTIALS=os.getenv("USE_CREDENTIALS", "True") == "True",
    VALIDATE_CERTS=os.getenv("VALIDATE_CERTS", "True") == "True"
)

def get_email_template(
    playername: str,
    title: str,
    description: str,
    code: str,
    warning: str,
) -> str:
    return f"""
<div style="margin:0; padding:40px 16px; background:#020817;">
  <div style="
    max-width:560px;
    margin:0 auto;
    font-family:'Segoe UI', Arial, sans-serif;
    color:#e2f3ff;
    text-align:center;
    border:1px solid rgba(148,163,184,0.12);
    border-radius:24px;
    padding:32px 24px;
    box-sizing:border-box;
    overflow:hidden;
    background:
      radial-gradient(circle at 20% 0%, rgba(118,212,242,0.16) 0%, rgba(118,212,242,0.05) 18%, rgba(118,212,242,0) 42%),
      radial-gradient(circle at 80% 20%, rgba(251,191,36,0.08) 0%, rgba(251,191,36,0.03) 16%, rgba(251,191,36,0) 36%),
      linear-gradient(180deg, #020817 0%, #07111a 38%, #0a1622 62%, #020817 100%);
    box-shadow:
      inset 0 1px 0 rgba(255,255,255,0.03),
      0 0 0 1px rgba(255,255,255,0.015),
      0 12px 36px rgba(0,0,0,0.32);
  ">
    
    <div style="margin-bottom:30px; font-size:26px; font-weight:900; letter-spacing:1.8px; text-transform:uppercase;">
      <span style="color:#76d4f2;">Beluga</span>
      <span style="color:#80DAEB;"> Empire</span>
    </div>

    <h3 style="
      margin:0 0 14px;
      color:#f4fbff;
      font-size:18px;
      font-weight:900;
      line-height:1.3;
      text-shadow:0 0 10px rgba(118,212,242,0.10);
    ">
      {title}, {playername}!
    </h3>

    <p style="margin:0 0 28px; color:#8ba3b8; line-height:1.7; font-size:15px; max-width:480px; margin-left:auto; margin-right:auto;">
      {description}
    </p>

    <div style="
      margin:0 auto 28px;
      padding:28px 20px;
      max-width:420px;
      border-radius:20px;
      border:1px solid rgba(148,163,184,0.12);
      background:
        linear-gradient(180deg, rgba(9,20,30,0.78) 0%, rgba(4,11,18,0.84) 100%);
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.025),
        inset 0 0 16px rgba(118,212,242,0.04),
        0 0 18px rgba(118,212,242,0.08),
        0 0 34px rgba(0,0,0,0.24);
      box-sizing:border-box;
    ">
      <div style="
        color:#8ba3b8;
        font-size:12px;
        letter-spacing:1.8px;
        text-transform:uppercase;
        margin-bottom:12px;
      ">
        Код подтверждения
      </div>
      <span style="
        display:inline-block;
        color:#FFD35F;
        line-height:1;
        letter-spacing:8px;
        padding-left:8px;
        font-size:35px;
        font-weight:900;
        font-family:'Segoe UI', Arial, sans-serif;
        text-shadow:
          0 0 8px rgba(251,191,36,0.40),
          0 0 16px rgba(251,191,36,0.22);
      ">
        {code}
      </span>
    </div>

    <p style="margin:0; color:#6f879a; font-size:12px; line-height:1.6; max-width:480px; margin-left:auto; margin-right:auto;">
      {warning}
    </p>
  </div>
</div>
    """


async def send_email(email_to: str, subject: str, html_content: str):

    message = MessageSchema(
        subject=subject,
        recipients=[email_to],
        body=html_content,
        subtype=MessageType.html
    )

    fm = FastMail(conf)
    await fm.send_message(message)