"""disputes, shipping address, agent kind, web offers, preflight step, refunded status"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0012_disputes_address_deals"
down_revision: Union[str, Sequence[str], None] = "0011_channel3_usage"
branch_labels = None
depends_on = None

OLD_STEPS = "('verify_agent', 'check_mandate', 'authorize_payment', 'scan_injection', 'intent_diff', 'graph_risk', 'decide', 'capture_or_void', 'build_proof')"
NEW_STEPS = "('verify_agent', 'check_mandate', 'authorize_payment', 'scan_injection', 'intent_diff', 'graph_risk', 'decide', 'preflight', 'capture_or_void', 'build_proof')"
OLD_STATUS = "('received', 'awaiting_payment', 'rejected', 'authorized', 'checking', 'captured', 'voided', 'pending_approval', 'failed')"
NEW_STATUS = "('received', 'awaiting_payment', 'rejected', 'authorized', 'checking', 'captured', 'voided', 'pending_approval', 'failed', 'refunded')"


def upgrade() -> None:
    op.add_column("users", sa.Column("shipping_address", JSONB(), nullable=True))
    op.add_column("users", sa.Column("address_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agents", sa.Column("kind", sa.String(), nullable=False, server_default="custom"))
    op.execute("UPDATE agents SET kind = 'channel3' WHERE managed")

    op.drop_constraint("ck_checks_step", "checks", type_="check")
    op.create_check_constraint("ck_checks_step", "checks", f"step IN {NEW_STEPS}")
    op.drop_constraint("ck_orders_status", "orders", type_="check")
    op.create_check_constraint("ck_orders_status", "orders", f"status IN {NEW_STATUS}")

    op.create_table(
        "disputes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("order_id", sa.String(), sa.ForeignKey("orders.id"), nullable=False, index=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("priority_label", sa.String(), nullable=False, server_default="normal"),
        sa.Column("suggestion", sa.String(), nullable=True),
        sa.Column("ai_reasons", JSONB(), nullable=True),
        sa.Column("ai_source", sa.String(), nullable=True),
        sa.Column("decided_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("refund_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("reason IN ('not_received', 'not_as_described', 'unauthorized', 'duplicate', 'other')",
                           name="ck_disputes_reason"),
        sa.CheckConstraint("status IN ('open', 'refunded', 'rejected', 'failed')", name="ck_disputes_status"),
        sa.CheckConstraint("priority_label IN ('urgent', 'high', 'normal', 'low')", name="ck_disputes_priority_label"),
        sa.CheckConstraint("suggestion IS NULL OR suggestion IN ('refund', 'reject', 'investigate')",
                           name="ck_disputes_suggestion"),
    )
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


def downgrade() -> None:
    op.drop_table("web_offers")
    op.drop_table("disputes")
    op.drop_constraint("ck_orders_status", "orders", type_="check")
    op.create_check_constraint("ck_orders_status", "orders", f"status IN {OLD_STATUS}")
    op.drop_constraint("ck_checks_step", "checks", type_="check")
    op.create_check_constraint("ck_checks_step", "checks", f"step IN {OLD_STEPS}")
    op.drop_column("agents", "kind")
    op.drop_column("users", "address_updated_at")
    op.drop_column("users", "shipping_address")
