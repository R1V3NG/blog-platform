import os
import shutil
from datetime import datetime, timezone
from fastapi import UploadFile, HTTPException
import uuid

MEDIA_ROOT = os.getenv("MEDIA_ROOT", "media")
os.makedirs(MEDIA_ROOT, exist_ok=True)


def save_image(file: UploadFile, subfolder: str = "posts") -> str:
    # Проверка расширения
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
        raise HTTPException(400, "Only image files allowed")

    # Генерация уникального имени
    filename = f"{uuid.uuid4().hex}{ext}"
    folder = os.path.join(MEDIA_ROOT, subfolder)
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)

    # Сохранение и опционально ресайз
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Возвращаем относительный URL
    return f"/media/{subfolder}/{filename}"


def delete_image(path: str):
    """Удаляет файл изображения с диска"""
    if not path:
        return

    # Убираем префикс /media/ или \media\
    clean_path = path
    if clean_path.startswith("/media/"):
        clean_path = clean_path[7:]
    elif clean_path.startswith("\\media\\"):
        clean_path = clean_path[7:]
    elif clean_path.startswith("media/"):
        clean_path = clean_path[6:]
    elif clean_path.startswith("media\\"):
        clean_path = clean_path[6:]

    # Формируем полный путь
    full_path = os.path.join(MEDIA_ROOT, clean_path)
    full_path = os.path.normpath(full_path)

    if os.path.exists(full_path):
        try:
            os.remove(full_path)
            print(f"✅ Deleted: {full_path}")
        except Exception as e:
            print(f"❌ Error deleting {full_path}: {e}")
    else:
        print(f"⚠️ File not found: {full_path}")


def clear_media_folder():
    """Удаляет все файлы и папки внутри MEDIA_ROOT."""
    if os.path.exists(MEDIA_ROOT):
        for item in os.listdir(MEDIA_ROOT):
            item_path = os.path.join(MEDIA_ROOT, item)
            if os.path.isfile(item_path) or os.path.islink(item_path):
                os.unlink(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)


def format_time_ago(dt: datetime) -> str:
    # Если dt не имеет часового пояса, добавляем UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    diff = now - dt
    seconds = diff.total_seconds()

    if seconds < 60:
        return f"{int(seconds)} сек."
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)} мин."
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)} ч."
    days = hours / 24
    if days < 7:
        return f"{int(days)} дн."
    weeks = days / 7
    if weeks < 4:
        return f"{int(weeks)} нед."
    months = days / 30
    if months < 12:
        return f"{int(months)} мес."
    years = days / 365
    return f"{int(years)} г."
