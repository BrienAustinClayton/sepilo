"""drop web offers and retire the deal finder agents"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_drop_web_offers"
down_revision: Union[str, Sequence[str], None] = "0012_disputes_address_deals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("web_offers")
    op.execute("UPDATE agents SET revoked_at = now() WHERE kind = 'deals' AND revoked_at IS NULL")


def downgrade() -> None:
    op.create_table(
        "web_offers",
        sa.Column("product_id", sa.String(), primary_key=True),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("merchant", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("image", sa.String(), nullable=True),
        sa.Column("paypal_evidence", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
