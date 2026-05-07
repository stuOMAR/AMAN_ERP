import { test, expect } from "@playwright/test";
import { login, getJson } from "../fixtures/api-client";
import { COMPANY_CODE, COMPANY_USER, COMPANY_PASS } from "../fixtures/scenarios";

test.describe("HR & Employees", () => {
  let token: string;

  test.beforeAll(async ({ request }) => {
    token = await login(request, COMPANY_USER, COMPANY_PASS, COMPANY_CODE);
  });

  test("TC-HR-001: Employees are listed", async ({ request }) => {
    const employees = await getJson(request, token, "/api/hr/employees/");
    const list = Array.isArray(employees) ? employees : employees.data || [];
    expect(list.length).toBeGreaterThanOrEqual(1);
  });

  test("TC-HR-002: Departments are listed", async ({ request }) => {
    const departments = await getJson(request, token, "/api/hr/departments");
    const list = Array.isArray(departments) ? departments : departments.data || [];
    expect(list.length).toBeGreaterThanOrEqual(1);
  });

  test("TC-HR-003: Positions are listed", async ({ request }) => {
    const positions = await getJson(request, token, "/api/hr/positions");
    const list = Array.isArray(positions) ? positions : positions.data || [];
    expect(list.length).toBeGreaterThanOrEqual(1);
  });

  test("TC-HR-004: Employee has correct fields", async ({ request }) => {
    const employees = await getJson(request, token, "/api/hr/employees/");
    const list = Array.isArray(employees) ? employees : employees.data || [];

    if (list.length > 0) {
      const emp = list[0];
      expect(emp.id).toBeTruthy();
      expect(emp.first_name).toBeTruthy();
      expect(emp.last_name).toBeTruthy();
    }
  });
});
