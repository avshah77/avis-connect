"""Initial connect.* schema — projects, connectors, credentials, operations, push_log

Revision ID: 0001
Revises:
Create Date: 2026-05-18
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS connect")

    op.create_table(
        'projects',
        sa.Column('id',          sa.Integer(),     nullable=False),
        sa.Column('slug',        sa.String(80),    nullable=False),
        sa.Column('name',        sa.String(200),   nullable=False),
        sa.Column('description', sa.Text(),        nullable=True),
        sa.Column('active',      sa.Boolean(),     nullable=False, server_default='true'),
        sa.Column('created_at',  sa.DateTime(),    nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
        schema='connect',
    )

    op.create_table(
        'connectors',
        sa.Column('id',             sa.Integer(),    nullable=False),
        sa.Column('project_id',     sa.Integer(),    nullable=False),
        sa.Column('connector_type', sa.String(50),   nullable=False),
        sa.Column('base_url',       sa.String(500),  nullable=True),
        sa.Column('active',         sa.Boolean(),    nullable=False, server_default='true'),
        sa.Column('created_at',     sa.DateTime(),   nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['project_id'], ['connect.projects.id']),
        sa.PrimaryKeyConstraint('id'),
        schema='connect',
    )

    op.create_table(
        'credentials',
        sa.Column('id',              sa.Integer(),   nullable=False),
        sa.Column('project_id',      sa.Integer(),   nullable=False),
        sa.Column('connector_type',  sa.String(50),  nullable=False),
        sa.Column('key',             sa.String(100), nullable=False),
        sa.Column('value_encrypted', sa.Text(),      nullable=False),
        sa.Column('updated_at',      sa.DateTime(),  nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_by',      sa.String(100), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['connect.projects.id']),
        sa.PrimaryKeyConstraint('id'),
        schema='connect',
    )

    op.create_table(
        'operations',
        sa.Column('id',             sa.Integer(),    nullable=False),
        sa.Column('project_id',     sa.Integer(),    nullable=False),
        sa.Column('connector_id',   sa.Integer(),    nullable=False),
        sa.Column('connector_type', sa.String(50),   nullable=False),
        sa.Column('operation_name', sa.String(100),  nullable=False),
        sa.Column('endpoint',       sa.String(500),  nullable=False),
        sa.Column('method',         sa.String(10),   nullable=False, server_default='POST'),
        sa.Column('description',    sa.Text(),       nullable=True),
        sa.Column('active',         sa.Boolean(),    nullable=False, server_default='true'),
        sa.ForeignKeyConstraint(['project_id'],   ['connect.projects.id']),
        sa.ForeignKeyConstraint(['connector_id'], ['connect.connectors.id']),
        sa.PrimaryKeyConstraint('id'),
        schema='connect',
    )

    op.create_table(
        'push_log',
        sa.Column('id',              sa.BigInteger(), nullable=False),
        sa.Column('project_id',      sa.Integer(),    nullable=False),
        sa.Column('project_slug',    sa.String(80),   nullable=False),
        sa.Column('connector_type',  sa.String(50),   nullable=False),
        sa.Column('operation',       sa.String(100),  nullable=False),
        sa.Column('payload_json',    sa.Text(),       nullable=True),
        sa.Column('response_json',   sa.Text(),       nullable=True),
        sa.Column('status',          sa.String(20),   nullable=False, server_default='pending'),
        sa.Column('http_status',     sa.Integer(),    nullable=True),
        sa.Column('duration_ms',     sa.Float(),      nullable=True),
        sa.Column('error_msg',       sa.Text(),       nullable=True),
        sa.Column('retry_count',     sa.Integer(),    nullable=False, server_default='0'),
        sa.Column('original_log_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at',      sa.DateTime(),   nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['project_id'], ['connect.projects.id']),
        sa.PrimaryKeyConstraint('id'),
        schema='connect',
    )

    # Indexes for common query patterns
    op.create_index('ix_push_log_project_slug',    'push_log', ['project_slug'],    schema='connect')
    op.create_index('ix_push_log_status',          'push_log', ['status'],          schema='connect')
    op.create_index('ix_push_log_created_at',      'push_log', ['created_at'],      schema='connect')
    op.create_index('ix_push_log_connector_type',  'push_log', ['connector_type'],  schema='connect')


def downgrade() -> None:
    op.drop_index('ix_push_log_connector_type', 'push_log', schema='connect')
    op.drop_index('ix_push_log_created_at',     'push_log', schema='connect')
    op.drop_index('ix_push_log_status',         'push_log', schema='connect')
    op.drop_index('ix_push_log_project_slug',   'push_log', schema='connect')
    op.drop_table('push_log',    schema='connect')
    op.drop_table('operations',  schema='connect')
    op.drop_table('credentials', schema='connect')
    op.drop_table('connectors',  schema='connect')
    op.drop_table('projects',    schema='connect')
