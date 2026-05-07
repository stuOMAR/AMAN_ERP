import { test, expect } from "@playwright/test";
import { login, getJson, expectStatus } from "../fixtures/api-client";
import { COMPANY_CODE, COMPANY_USER, COMPANY_PASS } from "../fixtures/scenarios";

test.describe("Auth & Security", () => {
  test("TC-AUTH-001: Successful login returns tokens", async ({ request }) => {
    const token = await login(request, COMPANY_USER, COMPANY_PASS, COMPANY_CODE);
    expect(token).toBeTruthy();
  });

  test("TC-AUTH-002: Wrong password returns 401", async ({ request }) => {
    const formData = new URLSearchParams();
    formData.append("username", COMPANY_USER);
    formData.append("password", "WrongPassword123!");
    formData.append("grant_type", "password");
    formData.append("company_code", COMPANY_CODE);

    const res = await request.post("/api/auth/login", {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      data: formData.toString(),
    });

    expect(res.status()).toBe(401);
  });

  test("TC-AUTH-003: Non-existent user returns 401", async ({ request }) => {
    const formData = new URLSearchParams();
    formData.append("username", "nonexistent.user.xyz");
    formData.append("password", "P@ssw0rd!2026");
    formData.append("grant_type", "password");
    formData.append("company_code", COMPANY_CODE);

    const res = await request.post("/api/auth/login", {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      data: formData.toString(),
    });

    expect([401, 422]).toContain(res.status());
  });

  test("TC-AUTH-004: Access without token returns 401", async ({ request }) => {
    const res = await request.get("/api/auth/me");
    expect(res.status()).toBe(401);
  });

  test("TC-AUTH-005: Access with invalid token returns 401", async ({ request }) => {
    const res = await request.get("/api/auth/me", {
      headers: { Authorization: "Bearer invalid.token.here" },
    });
    expect(res.status()).toBe(401);
  });

  test("TC-AUTH-006: /auth/me returns current user info", async ({ request }) => {
    const token = await login(request, COMPANY_USER, COMPANY_PASS, COMPANY_CODE);
    const me = await getJson(request, token, "/api/auth/me");
    expect(me.username || me.full_name).toBeTruthy();
    expect(me.role).toBeTruthy();
  });

  test("TC-AUTH-007: Rate limiting on failed logins", async ({ request }) => {
    const formData = new URLSearchParams();
    formData.append("username", COMPANY_USER);
    formData.append("password", "WrongPassword");
    formData.append("grant_type", "password");
    formData.append("company_code", COMPANY_CODE);

    let rateLimited = false;
    for (let i = 0; i < 15; i++) {
      const res = await request.post("/api/auth/login", {
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        data: formData.toString(),
      });
      if (res.status() === 429) {
        rateLimited = true;
        break;
      }
    }
    expect(rateLimited).toBe(true);
  });
});
