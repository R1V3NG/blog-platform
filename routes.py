import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlmodel import select, Session
from typing import List, Optional
from datetime import datetime, timedelta, timezone
import models
import db
from auth import AuthHandler, generate_verification_code, send_verification_email
from utils import save_image, delete_image

router = APIRouter()
auth_handler = AuthHandler()
logger = logging.getLogger("blog_api")
logging.basicConfig(level=logging.INFO)


# ---------- Зависимость: текущий пользователь ----------


def get_current_user(
    payload: dict = Depends(auth_handler.auth_wrapper),
    session: Session = Depends(db.get_session),
) -> models.User:
    user = session.get(models.User, payload["sub"])
    if not user:
        raise HTTPException(404, "User not found")
    return user


# ---------- Проверка прав доступа к статье ----------


def check_post_visibility(post: models.Post, user: Optional[models.User]) -> bool:
    """Возвращает True, если пользователь может видеть статью."""
    if user is None:
        return post.status
    if user.role == models.UserRole.READER:
        return post.status
    if user.role == models.UserRole.AUTHOR:
        return post.author_id == user.id or post.status
    return True


# ---------- Аутентификация ----------


@router.post("/auth/register", tags=["Auth"])
def register(
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(db.get_session),
):
    existing = session.exec(
        select(models.User).where(
            (models.User.email == email) | (models.User.username == username)
        )
    ).first()
    if existing:
        raise HTTPException(400, "Email or username already exists")
    hashed = auth_handler.get_password_hash(password)
    user = models.User(
        email=email,
        username=username,
        hashed_password=hashed,
        role=models.UserRole.READER,
        is_verified=False,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    code = generate_verification_code()
    expires = datetime.now(timezone.utc) + timedelta(minutes=5)
    verif = models.EmailVerification(email=email, code=code, expires_at=expires)
    session.add(verif)
    session.commit()
    send_verification_email(email, code)
    return {"message": "Verification code sent", "email": email}


@router.post("/auth/verify", tags=["Auth"])
def verify(
    email: str = Form(...),
    code: str = Form(...),
    session: Session = Depends(db.get_session),
):
    verif = session.exec(
        select(models.EmailVerification).where(
            models.EmailVerification.email == email,
            models.EmailVerification.code == code,
            models.EmailVerification.expires_at > datetime.now(timezone.utc),
        )
    ).first()
    if not verif:
        raise HTTPException(400, "Invalid or expired code")
    user = session.exec(select(models.User).where(models.User.email == email)).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_verified = True
    session.delete(verif)
    session.commit()
    token = auth_handler.encode_token(
        user.id, user.username, user.email, user.role.value
    )
    return {"access_token": token, "token_type": "bearer"}


@router.post("/auth/login", tags=["Auth"])
def login(
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(db.get_session),
):
    user = session.exec(select(models.User).where(models.User.email == email)).first()
    if not user or not auth_handler.verify_password(password, user.hashed_password):
        raise HTTPException(401, "Invalid email or password")
    if not user.is_verified:
        raise HTTPException(403, "Email not verified")
    access = auth_handler.encode_token(
        user.id, user.username, user.email, user.role.value
    )
    refresh = auth_handler.encode_refresh_token(user.id)
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}


@router.post("/auth/refresh", tags=["Auth"])
def refresh_token(
    refresh_token: str = Form(...), session: Session = Depends(db.get_session)
):
    try:
        user_id = auth_handler.decode_refresh_token(refresh_token)
    except HTTPException:
        raise
    user = session.get(models.User, user_id)
    if not user:
        raise HTTPException(401, "User not found")
    new_access = auth_handler.encode_token(
        user.id, user.username, user.email, user.role.value
    )
    new_refresh = auth_handler.encode_refresh_token(user.id)
    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
    }


# ---------- Пользователи ----------


@router.get("/users/me", tags=["Users"])
def get_me(user: models.User = Depends(get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role.value,
        "is_verified": user.is_verified,
        "registered_at": user.registered_at.isoformat(),
    }


@router.put("/users/me/password", tags=["Users"])
def change_password(
    old_password: str = Form(...),
    new_password: str = Form(...),
    user: models.User = Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    if not auth_handler.verify_password(old_password, user.hashed_password):
        raise HTTPException(400, "Wrong password")
    user.hashed_password = auth_handler.get_password_hash(new_password)
    session.add(user)
    session.commit()
    logger.info(f"User {user.username} changed password")
    return {"message": "Password updated"}


@router.get("/users/me/posts", tags=["Users"])
def get_my_posts(
    skip: int = 0,
    limit: int = 20,
    user: models.User = Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    posts = session.exec(
        select(models.Post)
        .where(models.Post.author_id == user.id)
        .order_by(models.Post.published_date.desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return [
        {
            "id": post.id,
            "title": post.title,
            "status": post.status.value,
            "published_date": post.published_date.isoformat() if post.published_date else None,
            "views": post.views,
            "likes_count": post.likes_count,
            "comments_count": post.comments_count,
            "images": [img.image_path for img in post.images],
        }
        for post in posts
    ]


# ---------- Категории ----------


@router.get("/api/categories", tags=["Categories"])
def get_categories(session: Session = Depends(db.get_session)):
    return session.exec(select(models.Category)).all()


@router.get("/api/categories/{category_id}", tags=["Categories"])
def get_category(category_id: int, session: Session = Depends(db.get_session)):
    category = session.get(models.Category, category_id)
    if not category:
        raise HTTPException(404, "Category not found")
    return {
        "id": category.id,
        "name": category.name,
        "posts": [{"id": p.id, "title": p.title} for p in category.posts],
    }


@router.post("/api/categories", tags=["Categories"])
def create_category(
    name: str = Form(...),
    user: models.User = Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    if user.role != models.UserRole.MODERATOR:
        raise HTTPException(403, "Only moderators can create categories")

    # Нормализация
    name = name.strip().lower()
    if not name:
        raise HTTPException(400, "Category name cannot be empty")

    # Проверка на дубликат
    existing = session.exec(
        select(models.Category).where(models.Category.name == name)
    ).first()
    if existing:
        raise HTTPException(400, "Category already exists")
    category = models.Category(name=name)
    session.add(category)
    session.commit()
    session.refresh(category)
    logger.info(f"Category created: {category.name} by {user.username}")
    return category


@router.put("/api/categories/{category_id}", tags=["Categories"])
def update_category(
    category_id: int,
    name: str = Form(...),
    user: models.User = Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    if user.role != models.UserRole.MODERATOR:
        raise HTTPException(403, "Only moderators can update categories")
    category = session.get(models.Category, category_id)
    if not category:
        raise HTTPException(404, "Category not found")

    # Нормализация
    name = name.strip().lower()
    if not name:
        raise HTTPException(400, "Category name cannot be empty")

    # Проверяем, что имя не занято другой категорией
    existing = session.exec(
        select(models.Category).where(
            models.Category.name == name, models.Category.id != category_id
        )
    ).first()
    if existing:
        raise HTTPException(400, "Category name already in use")
    category.name = name
    session.add(category)
    session.commit()
    session.refresh(category)
    logger.info(f"Category updated: {category.name} by {user.username}")
    return category


@router.delete("/api/categories/{category_id}", tags=["Categories"])
def delete_category(
    category_id: int,
    user: models.User = Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    if user.role != models.UserRole.MODERATOR:
        raise HTTPException(403, "Only moderators can delete categories")
    category = session.get(models.Category, category_id)
    if not category:
        raise HTTPException(404, "Category not found")
    session.delete(category)
    session.commit()
    logger.info(f"Category deleted: {category.name} by {user.username}")
    return {"ok": True}


# ---------- Статьи (эндпоинты /api/posts) ----------


@router.get("/api/posts", tags=["Posts"])
def get_posts(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    category_ids: Optional[List[int]] = Query(
        None, description="Напишите нужные ID категорий"
    ),
    status: Optional[models.PostStatus] = Query(
        None, description="Статусы: Черновик(draft) или Публикация(published)"
    ),
    sort: models.PostSort = Query(
        models.PostSort.RECENT,
        description="Сортировка: recent (по дате), popular (по лайкам)",
    ),
    session: Session = Depends(db.get_session),
    user: Optional[models.User] = Depends(get_current_user),
):
    query = select(models.Post)

    # Фильтрация по видимости согласно роли
    if user is None:
        query = query.where(models.Post.status == models.PostStatus.PUBLISHED)
    elif user.role == models.UserRole.READER:
        query = query.where(models.Post.status == models.PostStatus.PUBLISHED)
    elif user.role == models.UserRole.AUTHOR:
        query = query.where(
            (models.Post.author_id == user.id)
            | (models.Post.status == models.PostStatus.PUBLISHED)
        )

    # Фильтр по категории
    if category_ids:
        query = query.join(models.PostCategoryLink).where(
            models.PostCategoryLink.category_id.in_(category_ids)
        )
        query = query.distinct()

    # Фильтр по статусу
    if status is not None:
        query = query.where(models.Post.status == status)

    # Сортировка
    if sort == models.PostSort.POPULAR:
        query = query.order_by(
            models.Post.likes_count.desc(), models.Post.published_date.desc()
        )
    else:
        query = query.order_by(models.Post.published_date.desc())

    total = len(session.exec(query).all())
    posts = session.exec(query.offset((page - 1) * limit).limit(limit)).all()

    result = []
    for post in posts:
        user_liked = False
        if user:
            user_liked = (
                session.exec(
                    select(models.Like).where(
                        models.Like.user_id == user.id, models.Like.post_id == post.id
                    )
                ).first()
                is not None
            )
        result.append(
            {
                "id": post.id,
                "title": post.title,
                "content": post.content,
                "status": post.status.value,
                "published_date": post.published_date.isoformat() if post.published_date else None,
                "author_id": post.author_id,
                "categories": [{"id": c.id, "name": c.name} for c in post.categories],
                "views": post.views,
                "likes_count": post.likes_count,
                "user_liked": user_liked,
                "comments_count": post.comments_count,
                "images": [img.image_path for img in post.images],
            }
        )

    return {"page": page, "limit": limit, "total": total, "data": result}


@router.get("/api/posts/{post_id}", tags=["Posts"])
def get_post(
    post_id: int,
    session: Session = Depends(db.get_session),
    user: Optional[models.User] = Depends(get_current_user),
):
    post = session.get(models.Post, post_id)
    if not post or not check_post_visibility(post, user):
        raise HTTPException(404, "Post not found")

    # Проверка, лайкнул ли текущий пользователь
    user_liked = False
    if user:
        user_liked = (
            session.exec(
                select(models.Like).where(
                    models.Like.user_id == user.id, models.Like.post_id == post_id
                )
            ).first()
            is not None
        )
    # Учёт просмотра (только если не автор и ещё не смотрел)
    if user and user.id != post.author_id:
        existing_view = session.exec(
            select(models.PostView).where(
                models.PostView.user_id == user.id, models.PostView.post_id == post_id
            )
        ).first()
        if not existing_view:
            view = models.PostView(user_id=user.id, post_id=post_id)
            session.add(view)
            post.views += 1
            session.add(post)
            session.commit()

    images = [img.image_path for img in post.images]
    return {
        "id": post.id,
        "title": post.title,
        "content": post.content,
        "status": post.status.value,
        "published_date": post.published_date.isoformat() if post.published_date else None,
        "author_id": post.author_id,
        "categories": [{"id": c.id, "name": c.name} for c in post.categories],
        "views": post.views,
        "likes_count": post.likes_count,
        "user_liked": user_liked,
        "comments_count": post.comments_count,
        "images": images,
    }


@router.post("/api/posts", tags=["Posts"])
def create_post(
    title: str = Form(...),
    content: str = Form(...),
    status: Optional[models.PostStatus] = Query(
        models.PostStatus.DRAFT, description="Статусы: Черновик(draft) или Публикация(published)"
    ),
    category_ids: Optional[str] = Form(
        None, description="Напишите нужные ID категорий через запятую"
    ),
    user: models.User = Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    if user.role not in (models.UserRole.AUTHOR, models.UserRole.MODERATOR):
        raise HTTPException(403, "Only authors and moderators can create posts")

    post = models.Post(
        title=title,
        content=content,
        status=status,
        author_id=user.id,
        published_date=(
            datetime.now(timezone.utc)
            if status == models.PostStatus.PUBLISHED
            else None
        ),
    )
    session.add(post)
    session.flush()

    # Преобразуем строку в список целых
    category_list = []
    if category_ids:
        try:
            category_list = [
                int(x.strip()) for x in category_ids.split(",") if x.strip()
            ]
        except ValueError:
            raise HTTPException(400, "category_ids must be comma-separated integers")

    if category_list:
        categories = session.exec(
            select(models.Category).where(models.Category.id.in_(category_list))
        ).all()
        if len(categories) != len(category_list):
            raise HTTPException(404, "One or more categories not found")
        for category in categories:
            session.add(
                models.PostCategoryLink(post_id=post.id, category_id=category.id)
            )

    session.commit()
    session.refresh(post)
    logger.info(f"Post created: post.id: {post.id} by {user.username}")
    return {
        "id": post.id,
        "title": post.title,
        "status": post.status.value,
        "published_date": post.published_date.isoformat() if post.published_date else None,
        "categories": [{"id": c.id, "name": c.name} for c in post.categories],
    }


@router.put("/api/posts/{post_id}", tags=["Posts"])
def update_post(
    post_id: int,
    title: str = Form(...),
    content: str = Form(...),
    status: Optional[models.PostStatus] = Query(
        models.PostStatus.DRAFT, description="Статусы: Черновик(draft) или Публикация(published)"
    ),
    category_ids: Optional[str] = Form(
        None, description="Напишите нужные ID категорий через запятую"
    ),
    user: models.User = Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    post = session.get(models.Post, post_id)
    if not post:
        raise HTTPException(404, "Post not found")

    # Проверка прав
    if user.role == models.UserRole.READER:
        raise HTTPException(403, "Not allowed")
    if user.role == models.UserRole.AUTHOR and post.author_id != user.id:
        raise HTTPException(403, "You can only edit your own posts")

    post.title = title
    post.content = content
    post.status = status

    # Если выбран статус published и текущий статус статьи не published, то устанавливаем  текущую дату, иначе обнуляем
    if status == models.PostStatus.PUBLISHED and (post.status != models.PostStatus.PUBLISHED or post.published_date is None):
        post.published_date = datetime.now(timezone.utc)
    elif status == models.PostStatus.DRAFT:
        post.published_date = None

    session.add(post)
    session.flush()

    # Обновление категорий: удаляем все текущие связи и создаём новые
    old_links = session.exec(
        select(models.PostCategoryLink).where(
            models.PostCategoryLink.post_id == post_id
        )
    ).all()

    for link in old_links:
        session.delete(link)
        session.flush()
    category_list = []
    if category_ids:
        try:
            category_list = [
                int(x.strip()) for x in category_ids.split(",") if x.strip()
            ]
        except ValueError:
            raise HTTPException(400, "category_ids must be comma-separated integers")

    if category_list:
        categories = session.exec(
            select(models.Category).where(models.Category.id.in_(category_list))
        ).all()
        if len(categories) != len(category_list):
            raise HTTPException(404, "One or more categories not found")
        for category in categories:
            session.add(
                models.PostCategoryLink(post_id=post_id, category_id=category.id)
            )
    session.commit()
    session.refresh(post)
    logger.info(f"Post updated: post.id: {post.id} by {user.username}")
    return {
        "message": "Post updated",
        "categories": [{"id": c.id, "name": c.name} for c in post.categories],
    }


@router.delete("/api/posts/{post_id}", tags=["Posts"])
def delete_post(
    post_id: int,
    user: models.User = Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    post = session.get(models.Post, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    if user.role == models.UserRole.READER:
        raise HTTPException(403, "Not allowed")
    if user.role == models.UserRole.AUTHOR and post.author_id != user.id:
        raise HTTPException(403, "You can only delete your own posts")

    # Удаление изображений с диска
    for img in post.images:
        delete_image(img.image_path)
    session.delete(post)
    session.commit()
    logger.info(f"Post deleted: post.id: {post.id} by {user.username}")
    return {"ok": True}


# ---------- Изображения статей ----------


@router.post("/api/posts/{post_id}/image", tags=["Posts"])
def add_post_image(
    post_id: int,
    file: UploadFile = File(...),
    user: models.User = Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    post = session.get(models.Post, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    if user.role not in (models.UserRole.AUTHOR, models.UserRole.MODERATOR):
        raise HTTPException(403, "Only authors and moderators can upload images")
    if user.role == models.UserRole.AUTHOR and post.author_id != user.id:
        raise HTTPException(403, "Not your post")

    # Сохраняем один файл
    path = save_image(file, subfolder=f"posts/{post_id}")
    img = models.PostImage(post_id=post_id, image_path=path)
    session.add(img)
    session.commit()
    session.refresh(img)
    logger.info(f"Image added to post {post_id}: {img.image_path} by {user.username}")
    return {"id": img.id, "image_path": img.image_path}


@router.post("/api/posts/{post_id}/images", tags=["Posts"])
def add_post_images(
    post_id: int,
    files: List[UploadFile] = File(...),
    user: models.User = Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    post = session.get(models.Post, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    if user.role not in (models.UserRole.AUTHOR, models.UserRole.MODERATOR):
        raise HTTPException(403, "Only authors and moderators can upload images")
    if user.role == models.UserRole.AUTHOR and post.author_id != user.id:
        raise HTTPException(403, "Not your post")

    added = []
    for file in files:
        path = save_image(file, subfolder=f"posts/{post_id}")
        img = models.PostImage(post_id=post_id, image_path=path)
        session.add(img)
        session.flush()
        added.append({"id": img.id, "image_path": img.image_path})

    session.commit()
    logger.info(
        f"Images added to post {post_id}: {[a['image_path'] for a in added]} by {user.username}"
    )
    return {"images_added": added}


@router.delete("/api/posts/{post_id}/images/{image_id}", tags=["Posts"])
def delete_post_images(
    post_id: int,
    image_id: int,
    user: models.User = Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    post = session.get(models.Post, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    if user.role == models.UserRole.READER:
        raise HTTPException(403, "Not allowed")
    if user.role == models.UserRole.AUTHOR and post.author_id != user.id:
        raise HTTPException(403, "Not your post")

    image = session.get(models.PostImage, image_id)
    if not image or image.post_id != post_id:
        raise HTTPException(404, "Image not found")
    delete_image(image.image_path)
    session.delete(image)
    session.commit()
    logger.info(
        f"Image deleted from post {post_id}: {image.image_path} by {user.username}"
    )
    return {"ok": True}


# ---------- Комментарии ----------


@router.get("/api/posts/{post_id}/comments", tags=["Comments"])
def get_comments(
    post_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    sort: models.CommentSort = Query(
        models.CommentSort.NEWEST, description="Сортировка: newest, oldest, popular"
    ),
    session: Session = Depends(db.get_session),
    user: Optional[models.User] = Depends(get_current_user),
):
    post = session.get(models.Post, post_id)
    if not post or not check_post_visibility(post, user):
        raise HTTPException(404, "Post not found")

    query = select(models.Comment).where(models.Comment.post_id == post_id)
    if sort == models.CommentSort.NEWEST:
        query = query.order_by(models.Comment.created_at.desc())
    elif sort == models.CommentSort.OLDEST:
        query = query.order_by(models.Comment.created_at.asc())
    elif sort == models.CommentSort.POPULAR:
        query = query.order_by(
            models.Comment.likes_count.desc(), models.Comment.created_at.desc()
        )

    total = len(session.exec(query).all())
    comments = session.exec(query.offset((page - 1) * limit).limit(limit)).all()

    result = []
    for c in comments:
        user_liked = False
        if user:
            user_liked = (
                session.exec(
                    select(models.CommentLike).where(
                        models.CommentLike.user_id == user.id,
                        models.CommentLike.comment_id == c.id,
                    )
                ).first()
                is not None
            )
        result.append(
            {
                "id": c.id,
                "text": c.text,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                "likes_count": c.likes_count,
                "user_liked": user_liked,
                "author": {"id": c.author.id, "username": c.author.username},
            }
        )
    return {
        "post_id": post_id,
        "page": page,
        "limit": limit,
        "total": total,
        "comments": result,
    }


@router.get("/api/comments/{comment_id}", tags=["Comments"])
def get_comment(
    comment_id: int,
    session: Session = Depends(db.get_session),
    user: Optional[models.User] = Depends(get_current_user),
):
    comment = session.get(models.Comment, comment_id)
    if not comment:
        raise HTTPException(404, "Comment not found")

    # Проверим, видна ли связанная статья
    post = session.get(models.Post, comment.post_id)
    if not post or not check_post_visibility(post, user):
        raise HTTPException(404, "Comment not found")

    # Проверка, лайкнул ли текущий пользователь
    user_liked = False
    if user:
        user_liked = (
            session.exec(
                select(models.CommentLike).where(
                    models.CommentLike.user_id == user.id,
                    models.CommentLike.comment_id == comment.id,
                )
            ).first()
            is not None
        )

    return {
        "id": comment.id,
        "text": comment.text,
        "post_id": comment.post_id,
        "author": {"id": comment.author.id, "username": comment.author.username},
        "likes_count": comment.likes_count,
        "user_liked": user_liked,
        "created_at": comment.created_at.isoformat(),
        "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
    }


@router.post("/api/posts/{post_id}/comments", tags=["Comments"])
def create_comment(
    post_id: int,
    text: str = Form(...),
    user: models.User = Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    post = session.get(models.Post, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    if (
        post.status != models.PostStatus.PUBLISHED
        and user.id != post.author_id
        and user.role != models.UserRole.MODERATOR
    ):
        raise HTTPException(400, "Cannot comment on draft posts")

    comment = models.Comment(text=text, post_id=post_id, author_id=user.id)
    session.add(comment)
    post.comments_count += 1
    session.add(post)
    session.commit()
    session.refresh(comment)
    logger.info(f"Comment created by {user.username} on post {post_id}")
    return {
        "id": comment.id,
        "text": comment.text,
        "created_at": comment.created_at.isoformat(),
        "author": {"id": user.id, "username": user.username},
    }


@router.put("/api/comments/{comment_id}", tags=["Comments"])
def update_comment(
    comment_id: int,
    text: str = Form(...),
    user: models.User = Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    comment = session.get(models.Comment, comment_id)
    if not comment:
        raise HTTPException(404, "Comment not found")
    if comment.author_id != user.id:
        raise HTTPException(403, "You can only edit your own comments")
    comment.text = text
    comment.updated_at = datetime.now(timezone.utc)
    session.add(comment)
    session.commit()
    logger.info(f"Comment updated: {comment.id} by {user.username}")
    return {"message": "Comment updated"}


@router.delete("/api/comments/{comment_id}", tags=["Comments"])
def delete_comment(
    comment_id: int,
    user: models.User = Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    comment = session.get(models.Comment, comment_id)
    if not comment:
        raise HTTPException(404, "Comment not found")
    if comment.author_id != user.id and user.role != models.UserRole.MODERATOR:
        raise HTTPException(403, "You can only delete your own comments")
    post = session.get(models.Post, comment.post_id)
    if post:
        post.comments_count = max(0, post.comments_count - 1)
        session.add(post)
    session.delete(comment)
    session.commit()
    logger.info(f"Comment deleted: {comment_id} by {user.username}")
    return {"ok": True}


# ---------- Лайки ----------


@router.post("/api/posts/{post_id}/like", tags=["Likes"])
def toggle_post_like(
    post_id: int,
    user: models.User = Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    post = session.get(models.Post, post_id)
    if not post or not check_post_visibility(post, user):
        raise HTTPException(404, "Post not found")

    existing = session.exec(
        select(models.Like).where(
            models.Like.user_id == user.id, models.Like.post_id == post_id
        )
    ).first()

    if existing:
        session.delete(existing)
        post.likes_count = max(0, post.likes_count - 1)
        session.add(post)
        session.commit()

        action = "liked" if not existing else "unliked"
        logger.info(f"Post {post_id} {action} by {user.username}")

        return {"liked": False, "likes_count": post.likes_count}
    else:
        like = models.Like(user_id=user.id, post_id=post_id)
        session.add(like)
        post.likes_count += 1
        session.add(post)
        session.commit()

        action = "liked" if not existing else "unliked"
        logger.info(f"Post {post_id} {action} by {user.username}")

        return {"liked": True, "likes_count": post.likes_count}


@router.post("/api/comments/{comment_id}/like", tags=["Likes"])
def toggle_comment_like(
    comment_id: int,
    user: models.User = Depends(get_current_user),
    session: Session = Depends(db.get_session),
):
    comment = session.get(models.Comment, comment_id)
    if not comment:
        raise HTTPException(404, "Comment not found")
    # Проверим, что статья видна
    post = session.get(models.Post, comment.post_id)
    if not post or not check_post_visibility(post, user):
        raise HTTPException(404, "Comment not found")

    existing = session.exec(
        select(models.CommentLike).where(
            models.CommentLike.user_id == user.id,
            models.CommentLike.comment_id == comment_id,
        )
    ).first()

    if existing:
        session.delete(existing)
        comment.likes_count = max(0, comment.likes_count - 1)
        session.add(comment)
        session.commit()

        action = "liked" if not existing else "unliked"
        logger.info(f"Comment {comment_id} {action} by {user.username}")

        return {"liked": False, "likes_count": comment.likes_count}
    else:
        like = models.CommentLike(user_id=user.id, comment_id=comment_id)
        session.add(like)
        comment.likes_count += 1
        session.add(comment)
        session.commit()

        action = "liked" if not existing else "unliked"
        logger.info(f"Comment {comment_id} {action} by {user.username}")

        return {"liked": True, "likes_count": comment.likes_count}
