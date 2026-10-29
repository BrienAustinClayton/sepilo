"""Seed demo data: user usr_demo_priya and agent agt_demo_shopper."""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running as `python scripts/seed_demo.py` from the service root
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load service .env for DATABASE_URL if not already set
if "DATABASE_URL" not in os.environ:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

# Load agent .env for AGENT_PUBLIC_KEY if not already set
if "AGENT_PUBLIC_KEY" not in os.environ:
    try:
        from dotenv import load_dotenv  # noqa: F811
        _agent_env = Path(__file__).parent.parent.parent.parent / "apps" / "agent" / ".env"
        load_dotenv(_agent_env)
    except ImportError:
        pass

from app.db import get_engine  # noqa: E402
from app.models import User, Agent  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


def seed() -> None:
    factory = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    db = factory()
    try:
        # Idempotent: create user if not present
        if db.get(User, "usr_demo_priya") is None:
            user = User(
                id="usr_demo_priya",
                name="Priya",
                email="priya.demo@example.com",
                email_verified_at=datetime.now(timezone.utc),
                country="US",
                shipping_address={"name": "Priya Demo", "line1": "1 Market St", "city": "San Francisco",
                                  "region": "CA", "postal_code": "94105", "country": "US"},
            )
            db.add(user)
            db.flush()
            print("Created user usr_demo_priya")
        else:
            existing_user = db.get(User, "usr_demo_priya")
            if not existing_user.email_verified_at or not existing_user.shipping_address:
                existing_user.email = existing_user.email or "priya.demo@example.com"
                existing_user.email_verified_at = existing_user.email_verified_at or datetime.now(timezone.utc)
                existing_user.shipping_address = existing_user.shipping_address or {
                    "name": "Priya Demo", "line1": "1 Market St", "city": "San Francisco",
                    "region": "CA", "postal_code": "94105", "country": "US"}
                print("Gave user usr_demo_priya a verified email and shipping address")
            else:
                print("User usr_demo_priya already exists, skipping")

        public_key = os.environ.get("AGENT_PUBLIC_KEY", "")

        existing_agent = db.get(Agent, "agt_demo_shopper")
        if existing_agent is None:
            agent = Agent(
                id="agt_demo_shopper",
                user_id="usr_demo_priya",
                name="Demo Shopper",
                public_key=public_key,
                device_id="demo-device-0",
                verified=True,
            )
            db.add(agent)
            db.flush()
            print("Created agent agt_demo_shopper")
        else:
            # Update public_key if AGENT_PUBLIC_KEY is set and differs
            if public_key and existing_agent.public_key != public_key:
                existing_agent.public_key = public_key
                db.flush()
                print("Updated agent agt_demo_shopper public_key")
            else:
                print("Agent agt_demo_shopper already up to date, skipping")

        db.commit()
        print("Seed complete.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
