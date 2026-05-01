"""kpi_service package — backward-compatible re-exports of monolithic kpi_service.py (T6.3)."""
from .common import (
    resolve_period, get_previous_period, build_branch_filter, kpi_item, calc_trend, calc_trend_inverse, ratio_status, _gl_sum, _gl_balance, _gl_balance_by_classification, _count_table, _sum_column
)
from .executive import (
    get_executive_kpis
)
from .financial import (
    get_financial_kpis
)
from .sales import (
    get_sales_kpis
)
from .procurement import (
    get_procurement_kpis
)
from .warehouse import (
    get_warehouse_kpis
)
from .hr import (
    get_hr_kpis
)
from .manufacturing import (
    get_manufacturing_kpis
)
from .projects import (
    get_projects_kpis
)
from .pos import (
    get_pos_kpis
)
from .crm import (
    get_crm_kpis
)
from .charts import (
    _build_revenue_expense_chart, _build_sales_trend_chart, _build_ar_aging, _build_ap_aging, _build_executive_alerts, _build_financial_alerts
)

__all__ = ['resolve_period', 'get_previous_period', 'build_branch_filter', 'kpi_item', 'calc_trend', 'calc_trend_inverse', 'ratio_status', '_gl_sum', '_gl_balance', '_gl_balance_by_classification', '_count_table', '_sum_column', 'get_executive_kpis', 'get_financial_kpis', 'get_sales_kpis', 'get_procurement_kpis', 'get_warehouse_kpis', 'get_hr_kpis', 'get_manufacturing_kpis', 'get_projects_kpis', 'get_pos_kpis', 'get_crm_kpis', '_build_revenue_expense_chart', '_build_sales_trend_chart', '_build_ar_aging', '_build_ap_aging', '_build_executive_alerts', '_build_financial_alerts']
