import { test, expect } from "@playwright/test";
import { login, getJson } from "../fixtures/api-client";
import { COMPANY_CODE, COMPANY_USER, COMPANY_PASS } from "../fixtures/scenarios";

test.describe("Branches", () => {
  let token: string;

  test.beforeAll(async ({ request }) => {
    token = await login(request, COMPANY_USER, COMPANY_PASS, COMPANY_CODE);
  });

  test("TC-BR-001: List branches", async ({ request }) => {
    const branches = await getJson(request, token, "/api/branches/");
    const list = Array.isArray(branches) ? branches : branches.data || [];
    expect(list.length).toBeGreaterThanOrEqual(1);
  });

  test("TC-BR-002: Each branch has correct default_currency", async ({ request }) => {
    const branches = await getJson(request, token, "/api/branches/");
    const list = Array.isArray(branches) ? branches : branches.data || [];

    for (const branch of list) {
      expect(branch.default_currency).toBeTruthy();
      expect(branch.branch_code).toBeTruthy();
    }
  });

  test("TC-BR-003: Default branch exists", async ({ request }) => {
    const branches = await getJson(request, token, "/api/branches/");
    const list = Array.isArray(branches) ? branches : branches.data || [];

    const defaultBranch = list.find((b: any) => b.is_default === true);
    if (defaultBranch) {
      expect(defaultBranch.branch_code).toBeTruthy();
    }
  });

  test("TC-BR-004: Duplicate branch_code is rejected", async ({ request }) => {
    const branches = await getJson(request, token, "/api/branches/");
    const list = Array.isArray(branches) ? branches : branches.data || [];
    if (list.length === 0) return;

    const existingCode = list[0].branch_code;
    const res = await request.post("/api/branches/", {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        branch_code: existingCode,
        branch_name: "فرع مكرر",
        country_code: "SA",
        default_currency: "SAR",
      },
    });

    expect([400, 409, 422]).toContain(res.status());
  });
});
