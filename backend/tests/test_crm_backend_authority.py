from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_crm_create_endpoints_require_idempotency_key():
    router = _read("backend/routers/crm/opportunities.py")
    campaigns = _read("backend/routers/crm/campaigns.py")
    ddl = _read("backend/db_ddl/tenant_schema.py")
    migration = _read("backend/alembic/versions/031c_crm_opportunities_idempotency.py")
    service = _read("frontend/src/services/crm.js")

    assert 'require_idempotency_key(request, operation="CRM opportunity creation")' in router
    assert "WHERE idempotency_key = :idempotency_key" in router
    assert "idempotency_key, created_by" in router
    assert "uq_sales_opportunities_idempotency" in ddl
    assert 'require_idempotency_key(request, operation="CRM campaign creation")' in campaigns
    assert "uq_marketing_campaigns_idempotency" in ddl
    assert "uq_marketing_campaigns_idempotency" in migration
    assert "execution_idempotency_key VARCHAR(120)" in ddl
    assert "uq_marketing_campaigns_execution_idempotency" in migration
    assert "ALTER TABLE campaign_lead_attributions" in migration
    assert "ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120)" in migration
    assert "uq_campaign_lead_attr_campaign_lead" in ddl
    assert 'require_idempotency_key(request, operation="CRM campaign execution")' in campaigns
    assert 'require_idempotency_key(request, operation="CRM campaign lead attribution")' in campaigns
    assert "ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120)" in migration
    assert "createOpportunity: (data) => api.post('/crm/opportunities', data, idempotencyHeaders())" in service
    assert "createCampaign: (data) => api.post('/crm/campaigns', data, idempotencyHeaders())" in service
    assert "executeCampaign: (id) => api.post(`/crm/campaigns/${id}/execute`, null, idempotencyHeaders())" in service
    assert "attributeLead: (campaignId, leadId) => api.post(`/crm/campaigns/${campaignId}/attribute-lead`, null, {" in service


def test_crm_opportunity_conversion_to_quotation_is_idempotent():
    router = _read("backend/routers/crm/opportunities.py")
    service = _read("frontend/src/services/crm.js")

    assert 'require_idempotency_key(request, operation="CRM opportunity quotation conversion")' in router
    assert "WHERE idempotency_key = :idempotency_key" in router
    assert "idempotency_key" in router
    assert "convertToQuotation: (oppId) => api.post(`/crm/opportunities/${oppId}/convert-quotation`, null, idempotencyHeaders())" in service


def test_crm_forecasts_are_backend_decimal_serialized():
    analytics = _read("backend/routers/crm/analytics.py")
    opportunities = _read("backend/routers/crm/opportunities.py")
    cashflow_feed = _read("backend/services/crm/cashflow_feed.py")

    assert "money_str" in analytics
    assert "rate_str" in analytics
    assert "SUM(expected_value * probability / 100)" in analytics
    assert "100.0" not in analytics
    assert '"weighted_pipeline": _serialize_crm_row(weighted)' in analytics
    assert "COALESCE(SUM(expected_value * probability / 100), 0) as weighted_value" in opportunities
    assert '"pipeline": _serialize_opportunity_rows(rows' in opportunities
    assert "FROM sales_opportunities" in cashflow_feed
    assert "money_str(r.weighted_value)" in cashflow_feed
    assert "float(" not in cashflow_feed
    assert "100.0" not in cashflow_feed


def test_crm_frontend_keeps_money_as_strings_and_uses_backend_summaries():
    crm_home = _read("frontend/src/pages/CRM/CRMHome.jsx")
    opportunities = _read("frontend/src/pages/CRM/Opportunities.jsx")
    campaigns = _read("frontend/src/pages/CRM/MarketingCampaigns.jsx")
    campaign_list = _read("frontend/src/pages/Campaign/CampaignList.jsx")
    campaign_report = _read("frontend/src/pages/Campaign/CampaignReport.jsx")
    service = _read("frontend/src/services/crm.js")

    assert "expected_value: Number(" not in crm_home
    assert "expected_value: Number(" not in opportunities
    assert "budget: Number(" not in campaigns
    assert ".reduce((s, c) => s + (c.budget" not in campaigns
    assert ".reduce((s, c) => s + (c.total_" not in campaign_list
    assert "toFixed(" not in campaign_report
    assert "value / total" not in campaign_report
    assert "crmAPI.getCampaignSummary(params)" in campaigns
    assert "crmAPI.getCampaignSummary(params)" in campaign_list
    assert "{totalCampaigns}" in campaigns
    assert "{campaigns.length}" not in campaigns
    assert "getCampaignSummary: (params) => api.get('/crm/campaigns/summary', { params })" in service


def test_crm_cross_page_links_and_legacy_endpoints_are_integrated():
    campaigns = _read("backend/routers/crm/campaigns.py")
    opportunities = _read("backend/routers/crm/opportunities.py")
    service = _read("frontend/src/services/crm.js")
    velocity_router = _read("backend/routers/crm/velocity.py")
    funnel_router = _read("backend/routers/crm/funnel.py")
    cashflow_router = _read("backend/routers/crm/cashflow.py")
    velocity_service = _read("backend/services/crm/velocity.py")
    funnel_service = _read("backend/services/crm/funnel.py")
    kpi_service = _read("backend/services/kpi_service/crm.py")

    assert 'link=f"/crm/campaigns/{campaign_id}/report"' in campaigns
    assert 'link="/crm/opportunities"' in opportunities
    assert 'link=f"/crm/opportunities/{opp_id}"' not in opportunities
    assert "getVelocity: (params) => api.get('/crm/velocity', { params })" in service
    assert "getFunnel: (params) => api.get('/crm/funnel', { params })" in service
    assert "getCashflowForecast: (params) => api.get('/crm/cashflow-forecast', { params })" in service
    for router in (velocity_router, funnel_router, cashflow_router):
        assert "get_db_connection(current_user.company_id)" in router
        assert "current_user=Depends(get_current_user)" in router
        assert 'require_permission(["sales.view", "dashboard.crm"])' in router
    for source in (velocity_service, funnel_service):
        assert "sales_opportunities" in source
        assert "opportunity_stage_history" in source
        assert "INTERVAL ':days days'" not in source
        assert "FROM opportunities" not in source
    assert "float(" not in kpi_service
    assert "conversion_count" not in kpi_service
    assert "rate_str(win_rate)" in kpi_service
    assert "rate_str(campaign_roi)" in kpi_service


def test_crm_opportunity_stage_history_feeds_funnel_and_velocity():
    opportunities = _read("backend/routers/crm/opportunities.py")
    ddl = _read("backend/db_ddl/tenant_schema.py")

    assert "CREATE TABLE IF NOT EXISTS opportunity_stage_history" in ddl
    assert "def _record_opportunity_stage_change" in opportunities
    assert "INSERT INTO opportunity_stage_history" in opportunities
    assert "from_stage=None" in opportunities
    assert "from_stage=previous_stage" in opportunities
    assert "stage and stage != previous_stage" in opportunities


def test_crm_lead_scoring_stays_backend_driven():
    segments = _read("backend/routers/crm/segments.py")
    lead_scoring = _read("frontend/src/pages/CRM/LeadScoring.jsx")

    assert "SELECT * FROM crm_lead_scoring_rules WHERE is_active = TRUE" in segments
    assert "INSERT INTO crm_lead_scores" in segments
    assert "ON CONFLICT (opportunity_id) DO UPDATE" in segments
    assert "COALESCE(is_deleted, FALSE) = FALSE" in segments
    assert "crmAPI.calculateLeadScore()" in lead_scoring
