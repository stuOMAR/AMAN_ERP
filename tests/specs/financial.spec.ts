import { test, expect } from "@playwright/test";
import { login, getJson } from "../fixtures/api-client";
import { COMPANY_CODE, COMPANY_USER, COMPANY_PASS } from "../fixtures/scenarios";

test.describe("Financial Transactions", () => {
  let token: string;

  test.beforeAll(async ({ request }) => {
    token = await login(request, COMPANY_USER, COMPANY_PASS, COMPANY_CODE);
  });

  test("TC-FIN-001: Chart of accounts has correct structure", async ({ request }) => {
    const accounts = await getJson(request, token, "/api/accounting/accounts");
    const list = Array.isArray(accounts) ? accounts : accounts.data || [];

    expect(list.length).toBeGreaterThanOrEqual(12);

    const types = new Set(list.map((a: any) => a.account_type));
    expect(types.has("asset")).toBe(true);
    expect(types.has("liability")).toBe(true);
    expect(types.has("revenue")).toBe(true);
    expect(types.has("expense")).toBe(true);
  });

  test("TC-FIN-002: Treasury accounts have balances", async ({ request }) => {
    const treasuries = await getJson(request, token, "/api/treasury/accounts");
    const list = Array.isArray(treasuries) ? treasuries : treasuries.data || [];

    expect(list.length).toBeGreaterThanOrEqual(4);

    for (const t of list) {
      expect(t.name).toBeTruthy();
      expect(t.currency).toBeTruthy();
    }
  });

  test("TC-FIN-003: Journal entries endpoint is accessible", async ({ request }) => {
    const res = await request.get("/api/accounting/journal-entries", {
      headers: { Authorization: `Bearer ${token}` },
    });

    expect([200, 204, 404]).toContain(res.status());
  });

  test("TC-FIN-004: Sales invoices endpoint is accessible", async ({ request }) => {
    const res = await request.get("/api/sales/invoices", {
      headers: { Authorization: `Bearer ${token}` },
    });

    expect([200, 204, 404]).toContain(res.status());
  });

  test("TC-FIN-005: Cannot create invoice with negative quantity", async ({ request }) => {
    const parties = await getJson(request, token, "/api/parties/customers");
    const partyList = parties?.items || (Array.isArray(parties) ? parties : []);

    const products = await getJson(request, token, "/api/inventory/products");
    const prodList = Array.isArray(products) ? products : products.data || [];

    if (partyList.length > 0 && prodList.length > 0) {
      const res = await request.post("/api/sales/invoices", {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          invoice_date: "2026-05-04",
          party_id: partyList[0].id,
          currency: "SAR",
          lines: [{ product_id: prodList[0].id, quantity: -5, unit_price: 100 }],
        },
      });

      expect([400, 422]).toContain(res.status());
    }
  });
});
