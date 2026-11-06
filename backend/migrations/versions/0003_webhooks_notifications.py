"""Webhook-triggered pipeline runs + notification channels.

Revision ID: 0003_webhooks_notifications
Revises: 0002_schedules
Create Date: 2026-10-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_webhooks_notifications"
down_revision = "0002_schedules"
branch_labels = None
depends_on = None

KEY = sa.Unicode(128)
TS = sa.Unicode(64)
TXT = sa.UnicodeText


def col(name, type_, default=None, nullable=False, foreign_key=None, **kw):
    if isinstance(default, (int, float)):
        default = sa.text(str(default))
    args = (foreign_key,) if foreign_key is not None else ()
    return sa.Column(name, type_, *args, nullable=nullable, server_default=default, **kw)


def upgrade() -> None:
    op.create_table(
        "webhooks",
        col("id", KEY, primary_key=True),
        col("tenant_id", KEY, "tenant_demo"),
        col("project_id", KEY, "proj_research"),
        col("owner_user_id", KEY, "user_admin"),    # webhook runs act as this user
        col("app_id", KEY),
        col("name", TXT),
        col("token_hash", KEY),                      # sha256 of the URL token; the token is shown once
        col("token_prefix", sa.Unicode(32)),         # first chars, so the UI can tell tokens apart
        col("secret", TXT, nullable=True),           # optional HMAC-SHA256 signing secret
        col("prompt_template", TXT),                 # {{body}}, {{body.path.to.field}}, {{query.x}}
        col("enabled", sa.Integer, 1),
        col("timeout_ms", sa.Integer, 120000),
        col("last_triggered_at", TS, nullable=True),
        col("last_status", KEY, nullable=True),
        col("last_error", TXT, nullable=True),
        col("created_at", TS),
        col("updated_at", TS),
        sa.Index("idx_webhooks_token", "token_hash", unique=True),
        sa.Index("idx_webhooks_scope_app", "tenant_id", "project_id", "app_id"),
    )
    op.create_table(
        "webhook_runs",
        col("id", KEY, primary_key=True),
        col("webhook_id", KEY, foreign_key=sa.ForeignKey("webhooks.id", ondelete="CASCADE")),
        col("tenant_id", KEY),
        col("project_id", KEY),
        col("app_id", KEY),
        col("app_version", sa.Integer, 0),
        col("trigger", KEY, "webhook"),            # webhook | manual
        col("status", KEY, "running"),             # running | completed | failed | paused | interrupted
        col("run_id", KEY, nullable=True),         # traces.run_id / agent_runs.run_id
        col("payload_preview", TXT, nullable=True),
        col("output_preview", TXT, nullable=True),
        col("error", TXT, nullable=True),
        col("latency_ms", sa.Integer, 0),
        col("cost_usd", sa.Float, 0.0),
        col("started_at", TS),
        col("finished_at", TS, nullable=True),
        sa.Index("idx_webhook_runs_webhook", "webhook_id", "started_at"),
    )
    op.create_table(
        "notification_channels",
        col("id", KEY, primary_key=True),
        col("tenant_id", KEY, "tenant_demo"),
        col("project_id", KEY, "proj_research"),
        col("app_id", KEY, nullable=True),         # NULL = every pipeline in the project
        col("name", TXT),
        col("kind", KEY, "webhook"),               # slack | webhook
        col("url", TXT),
        col("events", TXT, "[]"),                  # JSON list, e.g. ["run.failed", "run.paused"]
        col("enabled", sa.Integer, 1),
        col("last_sent_at", TS, nullable=True),
        col("last_error", TXT, nullable=True),
        col("created_at", TS),
        col("updated_at", TS),
        sa.Index("idx_notification_channels_scope", "tenant_id", "project_id"),
    )


def downgrade() -> None:
    op.drop_table("notification_channels")
    op.drop_table("webhook_runs")
    op.drop_table("webhooks")
