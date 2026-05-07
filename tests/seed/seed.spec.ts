import { test, expect } from "@playwright/test";
import { login, postJson, getJson, materializeRefs, RefMap } from "../fixtures/api-client";
import { gulfHoldingScenario, COMPANY_CODE, COMPANY_USER, COMPANY_PASS } from "../fixtures/scenarios";

const COMPANY_USER_TOKEN = process.env.AMAN_TOKEN || "";

let token: string;
const refs: RefMap = {};

test.describe.serial("Seed: Gulf Holding Master Data", () => {
  test.beforeAll(async ({ request }) => {
    token = await login(request, COMPANY_USER, COMPANY_PASS, COMPANY_CODE);
  });

  test("TC-SEED-002: Create currencies", async ({ request }) => {
    for (const cur of gulfHoldingScenario.currencies) {
      const body: Record<string, any> = { ...cur };
      delete body.ref;
      try {
        const created = await postJson(request, token, "/api/currencies/", body);
        refs[cur.ref] = created.id as number;
      } catch {
        const currencies = await getJson(request, token, "/api/currencies/");
        const list = Array.isArray(currencies) ? currencies : currencies.data || [];
        const existing = list.find((c: any) => c.code === cur.code);
        if (existing) refs[cur.ref] = existing.id;
      }
    }
    expect(refs["currency:SAR"]).toBeTruthy();
    expect(refs["currency:EGP"]).toBeTruthy();
    expect(refs["currency:AED"]).toBeTruthy();
    expect(refs["currency:USD"]).toBeTruthy();
  });

  test("TC-SEED-003: Create branches", async ({ request }) => {
    for (const branch of gulfHoldingScenario.branches) {
      const body = materializeRefs(branch, refs);
      try {
        const created = await postJson(request, token, "/api/branches/", body);
        refs[branch.ref] = created.id as number;
      } catch {
        const branches = await getJson(request, token, "/api/branches/");
        const list = Array.isArray(branches) ? branches : branches.data || [];
        const existing = list.find((b: any) => b.branch_code === branch.branch_code);
        if (existing) refs[branch.ref] = existing.id;
      }
    }
    expect(refs["branch:riyadh"]).toBeTruthy();
    expect(refs["branch:cairo"]).toBeTruthy();
    expect(refs["branch:dubai"]).toBeTruthy();
  });

  test("TC-SEED-004: Create accounts and treasury", async ({ request }) => {
    for (const acc of gulfHoldingScenario.accounts) {
      const body = materializeRefs(acc, refs);
      try {
        const created = await postJson(request, token, "/api/accounting/accounts", body);
        refs[acc.ref] = created.id as number;
      } catch {
        const accounts = await getJson(request, token, "/api/accounting/accounts");
        const list = Array.isArray(accounts) ? accounts : accounts.data || [];
        const existing = list.find((a: any) => a.account_number === acc.account_number);
        if (existing) refs[acc.ref] = existing.id;
      }
    }

    for (const treasury of gulfHoldingScenario.treasuryAccounts) {
      const body = materializeRefs(treasury, refs);
      try {
        const created = await postJson(request, token, "/api/treasury/accounts", body);
        refs[treasury.ref] = created.id as number;
      } catch {
        const treasuries = await getJson(request, token, "/api/treasury/accounts");
        const list = Array.isArray(treasuries) ? treasuries : treasuries.data || [];
        const existing = list.find((t: any) => t.name === treasury.name);
        if (existing) refs[treasury.ref] = existing.id;
      }
    }

    expect(refs["account:assets"]).toBeTruthy();
    expect(refs["treasury:riyadh_bank"]).toBeTruthy();
  });

  test("TC-SEED-005: Create departments, positions, warehouses", async ({ request }) => {
    for (const dept of gulfHoldingScenario.departments) {
      const body = materializeRefs(dept, refs);
      try {
        const created = await postJson(request, token, "/api/hr/departments", body);
        refs[dept.ref] = created.id as number;
      } catch {
        const departments = await getJson(request, token, "/api/hr/departments");
        const list = Array.isArray(departments) ? departments : departments.data || [];
        const existing = list.find((d: any) => d.department_name === dept.department_name);
        if (existing) refs[dept.ref] = existing.id;
      }
    }

    for (const pos of gulfHoldingScenario.positions) {
      const body = materializeRefs(pos, refs);
      try {
        const created = await postJson(request, token, "/api/hr/positions", body);
        refs[pos.ref] = created.id as number;
      } catch {
        const positions = await getJson(request, token, "/api/hr/positions");
        const list = Array.isArray(positions) ? positions : positions.data || [];
        const existing = list.find((p: any) => p.position_name === pos.position_name);
        if (existing) refs[pos.ref] = existing.id;
      }
    }

    for (const wh of gulfHoldingScenario.warehouses) {
      const body = materializeRefs(wh, refs);
      try {
        const created = await postJson(request, token, "/api/inventory/warehouses", body);
        refs[wh.ref] = created.id as number;
      } catch {
        const warehouses = await getJson(request, token, "/api/inventory/warehouses");
        const list = Array.isArray(warehouses) ? warehouses : warehouses.data || [];
        const existing = list.find((w: any) => w.code === wh.code);
        if (existing) refs[wh.ref] = existing.id;
      }
    }

    expect(refs["dept:executive"]).toBeTruthy();
    expect(refs["wh:riyadh"]).toBeTruthy();
  });

  test("TC-SEED-006: Create products and categories", async ({ request }) => {
    for (const cat of gulfHoldingScenario.productCategories) {
      const body = materializeRefs(cat, refs);
      try {
        const created = await postJson(request, token, "/api/inventory/categories", body);
        refs[cat.ref] = created.id as number;
      } catch {
        const categories = await getJson(request, token, "/api/inventory/categories");
        const list = Array.isArray(categories) ? categories : categories.data || [];
        const existing = list.find((c: any) => c.code === cat.category_code || c.name === cat.category_name);
        if (existing) refs[cat.ref] = existing.id;
      }
    }

    for (const prod of gulfHoldingScenario.products) {
      const body = materializeRefs(prod, refs);
      try {
        const created = await postJson(request, token, "/api/inventory/products", body);
        refs[prod.ref] = created.id as number;
      } catch {
        const products = await getJson(request, token, "/api/inventory/products");
        const list = Array.isArray(products) ? products : products.data || [];
        const existing = list.find((p: any) => p.item_code === prod.item_code);
        if (existing) refs[prod.ref] = existing.id;
      }
    }

    expect(refs["cat:electronics"]).toBeTruthy();
    expect(refs["prod:tablet"]).toBeTruthy();
  });

  test("TC-SEED-007: Create customers and suppliers", async ({ request }) => {
    for (const party of gulfHoldingScenario.parties) {
      const body = materializeRefs(party, refs);
      try {
        const endpoint = party.is_customer ? "/api/sales/customers" : "/api/purchases/suppliers";
        const created = await postJson(request, token, endpoint, body);
        refs[party.ref] = created.id as number;
      } catch {
        const parties = await getJson(request, token, "/api/parties/customers");
        const list = parties?.items || (Array.isArray(parties) ? parties : []);
        const existing = list.find((p: any) => p.name === party.name);
        if (existing) refs[party.ref] = existing.id;
      }
    }

    expect(refs["party:riyadh_customer"]).toBeTruthy();
    expect(refs["party:cairo_customer"]).toBeTruthy();
    expect(refs["party:dubai_customer"]).toBeTruthy();
  });

  test("TC-SEED-008: Verify completeness", async ({ request }) => {
    const branches = await getJson(request, token, "/api/branches/");
    const branchList = Array.isArray(branches) ? branches : branches.data || [];
    expect(branchList.length).toBeGreaterThanOrEqual(3);

    const currencies = await getJson(request, token, "/api/currencies/");
    const curList = Array.isArray(currencies) ? currencies : currencies.data || [];
    expect(curList.length).toBeGreaterThanOrEqual(4);

    const products = await getJson(request, token, "/api/inventory/products");
    const prodList = Array.isArray(products) ? products : products.data || [];
    expect(prodList.length).toBeGreaterThanOrEqual(3);
  });
});

export { refs, token };
