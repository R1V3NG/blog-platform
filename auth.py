import os
import random
import string
import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()


class AuthHandler:
    security = HTTPBearer()
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    secret = os.getenv("JWT_SECRET")
    expire_minutes = int(os.getenv("JWT_EXPIRE_MINUTES", 5))

    def get_password_hash(self, password: str) -> str:
        return self.pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return self.pwd_context.verify(plain_password, hashed_password)

    def encode_token(self, user_id: int, username: str, email: str, role: str) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "exp": now + timedelta(minutes=self.expire_minutes),
            "iat": now,
            "sub": str(user_id),
            "username": username,
            "email": email,
            "role": role,
        }
        return jwt.encode(payload, self.secret, algorithm="HS256")

    def decode_token(self, token: str):
        try:
            payload = jwt.decode(token, self.secret, algorithms=["HS256"])
            return {
                "sub": int(payload.get("sub")) if payload.get("sub") else None,
                "username": payload.get("username"),
                "email": payload.get("email"),
                "role": payload.get("role", "reader"),
            }
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Токен просрочен")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Неверный токен")

    # Секрет для refresh токена (лучше свой, но можно и общий)
    refresh_secret = os.getenv(
        "JWT_REFRESH_SECRET", os.getenv("JWT_SECRET") + "_refresh"
    )
    refresh_expire_days = int(os.getenv("JWT_REFRESH_EXPIRE_DAYS", 7))

    def encode_refresh_token(self, user_id: int) -> str:
        """Создаёт refresh token (долгоживущий)"""
        now = datetime.now(timezone.utc)
        payload = {
            "exp": now + timedelta(days=self.refresh_expire_days),
            "iat": now,
            "sub": str(user_id),
            "type": "refresh",
        }
        return jwt.encode(payload, self.refresh_secret, algorithm="HS256")

    def decode_refresh_token(self, token: str):
        """Декодирует refresh token, возвращает user_id"""
        try:
            payload = jwt.decode(token, self.refresh_secret, algorithms=["HS256"])
            if payload.get("type") != "refresh":
                raise HTTPException(401, "Недопустимый тип токена")
            return int(payload["sub"])
        except jwt.ExpiredSignatureError:
            raise HTTPException(401, "Срок действия токена обновления истек")
        except jwt.InvalidTokenError:
            raise HTTPException(401, "Недопустимый токен обновления")

    def auth_wrapper(self, auth: HTTPAuthorizationCredentials = Security(security)):
        return self.decode_token(auth.credentials)


# ---- Вспомогательные функции для регистрации (вне класса) ----
def generate_verification_code(length: int = 6) -> str:
    """Генерирует случайный цифровой код"""
    return "".join(random.choices(string.digits, k=length))


def send_verification_email(to_email: str, code: str):
    """Отправляет код подтверждения на email (в dev-режиме печатает в консоль)"""
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    username = os.getenv("MAIL_USERNAME")
    password = os.getenv("MAIL_PASSWORD")
    from_email = os.getenv("MAIL_FROM")

    if not all([smtp_server, username, password, from_email]):
        print(f"⚠️ Email не настроен. Код подтверждения для {to_email}: {code}")
        return

    subject = "Подтверждение регистрации"
    body = f"Ваш код подтверждения: {code}\nКод действителен 5 минут."
    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)
        print(f"✅ Письмо отправлено на {to_email}")
    except Exception as e:
        print(f"❌ Ошибка отправки email: {e}")
