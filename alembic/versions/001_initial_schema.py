"""Initial schema for OLX phone data pipeline.

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enums (SQLite doesn't support enums natively, use CHECK constraints)
    # We'll use TEXT columns with CHECK constraints instead

    # Raw listings table
    op.create_table(
        'raw_listings',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('listing_id', sa.Text(), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('city', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('price', sa.Integer(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('condition', sa.Text(), nullable=True),
        sa.Column('seller_name', sa.Text(), nullable=True),
        sa.Column('seller_type', sa.Text(), nullable=True),
        sa.Column('seller_rating', sa.Float(), nullable=True),
        sa.Column('listing_date', sa.Text(), nullable=True),
        sa.Column('images', sa.Text(), nullable=True),  -- JSON array
        sa.Column('collected_at', sa.Text(), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('raw_html', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False, server_default='CURRENT_TIMESTAMP'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('listing_id'),
        sa.CheckConstraint("city IN ('delhi', 'mumbai', 'chennai', 'bengaluru', 'kolkata', 'hyderabad', 'pune', 'ahmedabad')"),
        sa.CheckConstraint("condition IN ('new', 'like_new', 'good', 'fair', 'poor', 'unknown')"),
        sa.CheckConstraint("source IN ('olx')"),
    )
    op.create_index('ix_raw_listings_city', 'raw_listings', ['city'])
    op.create_index('ix_raw_listings_price', 'raw_listings', ['price'])
    op.create_index('ix_raw_listings_listing_date', 'raw_listings', ['listing_date'])
    op.create_index('ix_raw_listings_collected_at', 'raw_listings', ['collected_at'])

    # Phone specifications table
    op.create_table(
        'phone_specs',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('brand', sa.Text(), nullable=False),
        sa.Column('model', sa.Text(), nullable=False),
        sa.Column('variant', sa.Text(), nullable=True),
        sa.Column('ram_gb', sa.Integer(), nullable=False),
        sa.Column('storage_gb', sa.Integer(), nullable=False),
        sa.Column('virtual_ram_gb', sa.Integer(), nullable=True),
        sa.Column('expandable_storage', sa.Integer(), nullable=False, default=0),
        sa.Column('launch_year', sa.Integer(), nullable=False),
        sa.Column('launch_date', sa.Text(), nullable=True),
        sa.Column('original_msrp_inr', sa.Integer(), nullable=True),
        sa.Column('original_msrp_usd', sa.Integer(), nullable=True),
        sa.Column('display_size_inches', sa.Float(), nullable=True),
        sa.Column('display_type', sa.Text(), nullable=True),
        sa.Column('processor', sa.Text(), nullable=True),
        sa.Column('battery_mah', sa.Integer(), nullable=True),
        sa.Column('rear_camera_mp', sa.Text(), nullable=True),
        sa.Column('front_camera_mp', sa.Text(), nullable=True),
        sa.Column('os_at_launch', sa.Text(), nullable=True),
        sa.Column('weight_grams', sa.Integer(), nullable=True),
        sa.Column('dimensions_mm', sa.Text(), nullable=True),
        sa.Column('colors', sa.Text(), nullable=True),  -- JSON array
        sa.Column('network_technologies', sa.Text(), nullable=True),  -- JSON array
        sa.Column('source_urls', sa.Text(), nullable=True),  -- JSON array
        sa.Column('created_at', sa.Text(), nullable=False, server_default='CURRENT_TIMESTAMP'),
        sa.Column('updated_at', sa.Text(), nullable=False, server_default='CURRENT_TIMESTAMP'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('brand', 'model', 'variant', name='uq_phone_spec'),
    )
    op.create_index('ix_phone_specs_brand', 'phone_specs', ['brand'])
    op.create_index('ix_phone_specs_model', 'phone_specs', ['model'])
    op.create_index('ix_phone_specs_launch_year', 'phone_specs', ['launch_year'])

    # Enriched listings table
    op.create_table(
        'enriched_listings',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('raw_listing_id', sa.Text(), nullable=False),
        sa.Column('phone_spec_id', sa.Text(), nullable=True),
        sa.Column('match_confidence', sa.Float(), nullable=False, default=0.0),
        sa.Column('match_method', sa.Text(), nullable=True),
        sa.Column('extracted_ram_gb', sa.Integer(), nullable=True),
        sa.Column('extracted_storage_gb', sa.Integer(), nullable=True),
        sa.Column('price_vs_msrp_pct', sa.Float(), nullable=True),
        sa.Column('depreciation_pct', sa.Float(), nullable=True),
        sa.Column('age_years', sa.Float(), nullable=True),
        sa.Column('enriched_at', sa.Text(), nullable=False, server_default='CURRENT_TIMESTAMP'),
        sa.ForeignKeyConstraint(['raw_listing_id'], ['raw_listings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['phone_spec_id'], ['phone_specs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('raw_listing_id'),
    )
    op.create_index('ix_enriched_listings_phone_spec', 'enriched_listings', ['phone_spec_id'])
    op.create_index('ix_enriched_listings_match_conf', 'enriched_listings', ['match_confidence'])

    # Fraud analyses table
    op.create_table(
        'fraud_analyses',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('listing_id', sa.Text(), nullable=False),
        sa.Column('flags', sa.Text(), nullable=True),  -- JSON array
        sa.Column('risk_score', sa.Float(), nullable=False, default=0.0),
        sa.Column('risk_level', sa.Text(), nullable=False, default='low'),
        sa.Column('evidence', sa.Text(), nullable=True),  -- JSON
        sa.Column('requires_manual_review', sa.Integer(), nullable=False, default=0),
        sa.Column('analyzed_at', sa.Text(), nullable=False, server_default='CURRENT_TIMESTAMP'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('listing_id'),
        sa.CheckConstraint("risk_level IN ('low', 'medium', 'high')"),
    )
    op.create_index('ix_fraud_analyses_risk_level', 'fraud_analyses', ['risk_level'])
    op.create_index('ix_fraud_analyses_risk_score', 'fraud_analyses', ['risk_score'])

    # Price stats table
    op.create_table(
        'price_stats',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('phone_spec_id', sa.Text(), nullable=False),
        sa.Column('city', sa.Text(), nullable=True),
        sa.Column('condition', sa.Text(), nullable=True),
        sa.Column('ram_gb', sa.Integer(), nullable=True),
        sa.Column('storage_gb', sa.Integer(), nullable=True),
        sa.Column('sample_size', sa.Integer(), nullable=False),
        sa.Column('min_price', sa.Integer(), nullable=False),
        sa.Column('max_price', sa.Integer(), nullable=False),
        sa.Column('mean_price', sa.Float(), nullable=False),
        sa.Column('median_price', sa.Float(), nullable=False),
        sa.Column('std_dev', sa.Float(), nullable=False),
        sa.Column('percentile_25', sa.Integer(), nullable=False),
        sa.Column('percentile_75', sa.Integer(), nullable=False),
        sa.Column('condition_breakdown', sa.Text(), nullable=True),  -- JSON
        sa.Column('depreciation_curve', sa.Text(), nullable=True),  -- JSON
        sa.Column('confidence', sa.Float(), nullable=False, default=0.0),
        sa.Column('calculated_at', sa.Text(), nullable=False, server_default='CURRENT_TIMESTAMP'),
        sa.ForeignKeyConstraint(['phone_spec_id'], ['phone_specs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_price_stats_phone_spec', 'price_stats', ['phone_spec_id'])
    op.create_index('ix_price_stats_city_condition', 'price_stats', ['city', 'condition'])

    # Collection runs table
    op.create_table(
        'collection_runs',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('started_at', sa.Text(), nullable=False, server_default='CURRENT_TIMESTAMP'),
        sa.Column('completed_at', sa.Text(), nullable=True),
        sa.Column('cities', sa.Text(), nullable=True),  -- JSON array
        sa.Column('listings_found', sa.Integer(), nullable=False, default=0),
        sa.Column('listings_new', sa.Integer(), nullable=False, default=0),
        sa.Column('listings_updated', sa.Integer(), nullable=False, default=0),
        sa.Column('errors', sa.Text(), nullable=True),  -- JSON
        sa.Column('status', sa.Text(), nullable=False, default='running'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_collection_runs_started_at', 'collection_runs', ['started_at'])


def downgrade() -> None:
    op.drop_table('collection_runs')
    op.drop_table('price_stats')
    op.drop_table('fraud_analyses')
    op.drop_table('enriched_listings')
    op.drop_table('phone_specs')
    op.drop_table('raw_listings')