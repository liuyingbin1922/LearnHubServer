from datetime import datetime

from shared.db import get_session_factory
from shared.models import Collection, Problem, User


SessionLocal = get_session_factory()


def main():
    session = SessionLocal()
    user = User(nickname="seed-user")
    session.add(user)
    session.commit()
    collection = Collection(user_id=user.id, name="Seed Collection", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    session.add(collection)
    session.commit()
    problem = Problem(
        user_id=user.id,
        collection_id=collection.id,
        status="DRAFT",
        original_image_url="https://example.com/seed.png",
        order_index=0,
    )
    session.add(problem)
    session.commit()
    print(f"seeded user={user.id} collection={collection.id} problem={problem.id}")
    session.close()


if __name__ == "__main__":
    main()
