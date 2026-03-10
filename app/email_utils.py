import os
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from dotenv import load_dotenv

load_dotenv()

conf = ConnectionConfig(
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "noreply@example.com"),
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "password"),
    MAIL_FROM = os.getenv("MAIL_FROM", "noreply@example.com"),
    MAIL_PORT = int(os.getenv("MAIL_PORT", 465)),
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.example.com"),
    MAIL_STARTTLS = os.getenv("MAIL_STARTTLS", "False") == "True",
    MAIL_SSL_TLS = os.getenv("MAIL_SSL_TLS", "True") == "True",
    USE_CREDENTIALS = os.getenv("USE_CREDENTIALS", "True") == "True",
    VALIDATE_CERTS = os.getenv("VALIDATE_CERTS", "True") == "True"
)

def get_email_template(playername: str, title: str, description: str, code: str, warning: str) -> str:
    return f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #0f172a; color: #fff; padding: 30px; border-radius: 12px; max-width: 500px; margin: 0 auto; border: 1px solid #1e293b; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
        <div style="text-align: center; margin-bottom: 24px;">
            <h2 style="color: #06b6d4; margin: 0; font-size: 24px; letter-spacing: 1px;">BelugaEmpire</h2>
        </div>
        
        <h3 style="color: #f8fafc; font-size: 18px; margin-bottom: 16px;">{title}, {playername}!</h3>
        <p style="color: #cbd5e1; line-height: 1.6; margin-bottom: 24px; font-size: 15px;">
            {description}
        </p>
        
        <div style="background-color: #1e293b; border: 1px solid #334155; padding: 20px; border-radius: 8px; text-align: center; margin-bottom: 24px;">
            <span style="color: #fbbf24; letter-spacing: 8px; font-size: 36px; font-weight: bold; font-family: monospace;">{code}</span>
        </div>
        
        <p style="color: #64748b; font-size: 12px; line-height: 1.5; border-top: 1px solid #1e293b; padding-top: 16px; margin: 0;">
            {warning}
        </p>
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