"""merge all heads

Revision ID: afa5d0a73bb9
Revises: 023e_zatca_outbox, 023f_opportunity_stage_history, 023g_pos_offline_batches, 023h_item_warehouse_settings, 023i_mrp_recommendations, 023j_bom_snapshots_and_mo_extensions, 023k_production_completions_and_scrap, 023l_workstation_overhead, 024s_je_source_extend
Create Date: 2026-05-02 23:12:08.457963
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = 'afa5d0a73bb9'
down_revision: Union[str, None] = ('023e_zatca_outbox', '023f_opportunity_stage_history', '023g_pos_offline_batches', '023h_item_warehouse_settings', '023i_mrp_recommendations', '023j_bom_snapshots_and_mo_extensions', '023k_production_completions_and_scrap', '023l_workstation_overhead', '024s_je_source_extend')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
