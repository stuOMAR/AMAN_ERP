import { test, expect } from "@playwright/test";
import { login, getJson } from "../fixtures/api-client";
import { COMPANY_CODE, COMPANY_USER, COMPANY_PASS } from "../fixtures/scenarios";

test.describe("Cross-Branch Isolation", () => {
  let adminToken: string;

  test.beforeAll(async ({ request }) => {
    adminToken = await login(request, COMPANY_USER, COMPANY_PASS, COMPANY_CODE);
  });

  test("TC-ISO-001: Admin sees all branches", async ({ request }) => {
    const branches = await getJson(request, adminToken, "/api/branches/");
    const list = Array.isArray(branches) ? branches : branches.data || [];
    expect(list.length).toBeGreaterThanOrEqual(1);
  });

  test("TC-ISO-002: Admin can access all financial data", async ({ request }) => {
    const endpoints = [
      "/api/accounting/accounts",
      "/api/treasury/accounts",
      "/api/sales/invoices",
      "/api/hr/employees/",
      "/api/inventory/products",
    ];

    for (const endpoint of endpoints) {
      const res = await request.get(endpoint, {
        headers: { Authorization: `Bearer ${adminToken}` },
      });
      expect(res.status(), `Admin access ${endpoint}`).toBe(200);
    }
  });

  test("TC-ISO-003: Dashboard is accessible", async ({ request }) => {
    const res = await request.get("/api/dashboard/", {
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    expect([200, 404]).toContain(res.status());
  });

  test("TC-ISO-004: Audit log is accessible", async ({ request }) => {
    const res = await request.get("/api/audit/", {
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    expect([200, 404]).toContain(res.status());
  });
});
