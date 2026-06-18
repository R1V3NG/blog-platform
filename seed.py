from db import create_db_and_tables, engine
from models import *
from auth import AuthHandler
from datetime import datetime, timedelta, timezone
from sqlmodel import Session, select


def seed():
    create_db_and_tables()
    auth = AuthHandler()

    with Session(engine) as session:
        existing = session.exec(select(User).where(
            User.username == "reader")).first()
        if existing:
            print("Данный пользователь уже создан")
            return

        now = datetime.now(timezone.utc)

        # Пользователи с разными датами регистрации
        reader = User(
            email="reader@example.com",
            username="reader",
            hashed_password=auth.get_password_hash("reader123"),
            role=UserRole.READER,
            is_verified=True,
            registered_at=now - timedelta(days=5)
        )
        author = User(
            email="author@example.com",
            username="author",
            hashed_password=auth.get_password_hash("author123"),
            role=UserRole.AUTHOR,
            is_verified=True,
            registered_at=now - timedelta(days=4)
        )
        moderator = User(
            email="moderator@example.com",
            username="moderator",
            hashed_password=auth.get_password_hash("mod123"),
            role=UserRole.MODERATOR,
            is_verified=True,
            registered_at=now - timedelta(days=3)
        )
        session.add_all([reader, author, moderator])
        session.commit()
        session.refresh(reader)
        session.refresh(author)
        session.refresh(moderator)

        # Категории
        tech = Category(name="tech")
        science = Category(name="science")
        lifestyle = Category(name="lifestyle")
        session.add_all([tech, science, lifestyle])
        session.commit()
        session.refresh(tech)
        session.refresh(science)
        session.refresh(lifestyle)

        # Статьи с разными датами публикации
        post1 = Post(
            title="Hello Tech",
            content="This is a tech post about FastAPI and SQLModel.",
            status="published",
            author_id=author.id,
            published_date=now - timedelta(days=2),
            views=0, likes_count=0, comments_count=0
        )
        post2 = Post(
            title="Draft Science",
            content="Science draft content about quantum physics.",
            status="draft",
            author_id=author.id,
            published_date=None,
            views=0, likes_count=0, comments_count=0
        )
        post3 = Post(
            title="Moderator Lifestyle Post",
            content="Lifestyle tips from the moderator.",
            status="published",
            author_id=moderator.id,
            published_date=now,
            views=0, likes_count=0, comments_count=0
        )

        session.add_all([post1, post2, post3])
        session.flush()
        session.add_all([
        PostCategoryLink(post_id=post1.id, category_id=tech.id),
        PostCategoryLink(post_id=post1.id, category_id=lifestyle.id),
        PostCategoryLink(post_id=post2.id, category_id=science.id),
        PostCategoryLink(post_id=post3.id, category_id=lifestyle.id),
])
        session.commit()
        session.refresh(post1)
        session.refresh(post2)
        session.refresh(post3)

        # Изображение к первой статье
        image = PostImage(
            post_id=post1.id,
            image_path="/media/posts/1/FastAPI.jpg"
        )
        session.add(image)

        # Комментарий от читателя
        comment = Comment(
            text="Great post! Very informative.",
            post_id=post1.id,
            author_id=reader.id,
            created_at=now - timedelta(hours=12),
            updated_at=None,
            likes_count=0
        )
        session.add(comment)
        session.commit()
        session.refresh(comment)

        # Лайк статьи (читатель)
        like_post = Like(
            user_id=reader.id,
            post_id=post1.id,
            created_at=now - timedelta(hours=10)
        )
        session.add(like_post)
        post1.likes_count += 1

        # Лайк комментария (читатель)
        comment_like = CommentLike(
            user_id=reader.id,
            comment_id=comment.id,
            created_at=now - timedelta(hours=8)
        )
        session.add(comment_like)
        comment.likes_count += 1

        # Просмотр статьи (читатель)
        view = PostView(
            user_id=reader.id,
            post_id=post1.id,
            viewed_at=now - timedelta(hours=6)
        )
        session.add(view)
        post1.views += 1

        # Обновление счётчиков
        post1.comments_count = 1
        session.add(post1)
        session.add(comment)
        session.commit()
        print("Посев базы данных завершён")


if __name__ == "__main__":
    seed()
