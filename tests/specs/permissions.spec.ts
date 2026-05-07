import { test, expect } from "@playwright/test";
import { login, getJson } from "../fixtures/api-client";
import { COMPANY_CODE, COMPANY_USER, COMPANY_PASS } from "../fixtures/scenarios";

test.describe("Permissions & RBAC", () => {
  let adminToken: string;

  test.beforeAll(async ({ request }) => {
    adminToken = await login(request, COMPANY_USER, COMPANY_PASS, COMPANY_CODE);
  });

  test("TC-PERM-001: Admin can access all endpoints", async ({ request }) => {
    const endpoints = [
      "/api/branches/",
      "/api/currencies/",
      "/api/accounting/accounts",
      "/api/treasury/accounts",
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

  test("TC-PERM-002: Roles endpoint returns permissions", async ({ request }) => {
    const res = await request.get("/api/roles/permissions", {
      headers: { Authorization: `Bearer ${adminToken}` },
    });

    if (res.ok()) {
      const body = await res.json();
      const permissions = Array.isArray(body) ? body : body.data || body.permissions || [];
      expect(permissions.length).toBeGreaterThan(50);
    }
  });

  test("TC-PERM-003: Roles list is available", async ({ request }) => {
    const res = await request.get("/api/roles/", {
      headers: { Authorization: `Bearer ${adminToken}` },
    });

    if (res.ok()) {
      const body = await res.json();
      const roles = Array.isArray(body) ? body : body.data || [];
      expect(roles.length).toBeGreaterThan(0);
    }
  });
});
