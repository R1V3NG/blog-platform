from typing import Optional, List
from datetime import datetime, timezone
from sqlmodel import Field, SQLModel, Relationship
from enum import Enum


class UserRole(str, Enum):
    """Роли пользователя"""
    READER = "reader"
    AUTHOR = "author"
    MODERATOR = "moderator"


class User(SQLModel, table=True):
    """Пользователи"""
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    username: str = Field(unique=True, index=True)
    hashed_password: str
    role: UserRole = Field(default=UserRole.READER)
    is_verified: bool = Field(default=False)
    registered_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))

    post: List["Post"] = Relationship(
        back_populates="author", cascade_delete=True)
    comments: List["Comment"] = Relationship(
        back_populates="author", cascade_delete=True)
    likes: List["Like"] = Relationship(
        back_populates="user", cascade_delete=True)
    comment_likes: List["CommentLike"] = Relationship(
        back_populates="user", cascade_delete=True)


class EmailVerification(SQLModel, table=True):
    """Подтверждение почты пользователя"""
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True)
    code: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime


class PostCategoryLink(SQLModel, table=True):
    """Таблица для соединения категории со статьёй"""
    post_id: int = Field(foreign_key="post.id",
                         primary_key=True, ondelete="CASCADE")
    category_id: int = Field(foreign_key="category.id",
                             primary_key=True, ondelete="CASCADE")


class Category(SQLModel, table=True):
    """Категория статьи"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    posts: List["Post"] = Relationship(
        back_populates="categories",
        link_model=PostCategoryLink
    )

class PostStatus(str, Enum):
    """Статус статьи"""
    DRAFT = "draft"
    PUBLISHED = "published"


class Post(SQLModel, table=True):
    """Статьи"""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    content: str
    published_date: Optional[datetime] = Field(default=None)
    status: PostStatus = Field(default=PostStatus.DRAFT)
    author_id: int = Field(foreign_key="user.id", ondelete="CASCADE")
    views: int = Field(default=0)
    likes_count: int = Field(default=0)
    comments_count: int = Field(default=0)

    author: User = Relationship(back_populates="post")
    categories: List["Category"] = Relationship(
        back_populates="posts",
        link_model=PostCategoryLink)
    images: List["PostImage"] = Relationship(
        back_populates="post", cascade_delete=True)
    likes: List["Like"] = Relationship(
        back_populates="post", cascade_delete=True)
    comments: List["Comment"] = Relationship(
        back_populates="post", cascade_delete=True)


class PostImage(SQLModel, table=True):
    """Изображения к статьям"""
    id: Optional[int] = Field(default=None, primary_key=True)
    post_id: int = Field(foreign_key="post.id", ondelete="CASCADE")
    image_path: str
    post: Post = Relationship(back_populates="images")


class PostSort(str, Enum):
    """Сортировка статей"""
    RECENT = "recent"
    POPULAR = "popular"


class Comment(SQLModel, table=True):
    """Комментарии"""
    id: Optional[int] = Field(default=None, primary_key=True)
    text: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None
    post_id: int = Field(foreign_key="post.id", ondelete="CASCADE")
    author_id: int = Field(foreign_key="user.id", ondelete="CASCADE")
    likes_count: int = Field(default=0)

    post: Post = Relationship(back_populates="comments")
    author: User = Relationship(back_populates="comments")
    likes: List["CommentLike"] = Relationship(
        back_populates="comment", cascade_delete=True)


class CommentSort(str, Enum):
    """Сортировка комментариев"""
    NEWEST = "newest"
    OLDEST = "oldest"
    POPULAR = "popular"


class Like(SQLModel, table=True):
    """Лайки на статьи"""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", ondelete="CASCADE")
    post_id: int = Field(foreign_key="post.id", ondelete="CASCADE")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))

    user: User = Relationship(back_populates="likes")
    post: Post = Relationship(back_populates="likes")


class PostView(SQLModel, table=True):
    """Уникальные просмотры статьи (один пользователь - один просмотр)"""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", ondelete="CASCADE")
    post_id: int = Field(foreign_key="post.id", ondelete="CASCADE")
    viewed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))


class CommentLike(SQLModel, table=True):
    """Лайки на комментариях"""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", ondelete="CASCADE")
    comment_id: int = Field(foreign_key="comment.id", ondelete="CASCADE")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))

    user: User = Relationship(back_populates="comment_likes")
    comment: Comment = Relationship(back_populates="likes")
