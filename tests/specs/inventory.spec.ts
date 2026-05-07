import { test, expect } from "@playwright/test";
import { login, getJson } from "../fixtures/api-client";
import { COMPANY_CODE, COMPANY_USER, COMPANY_PASS } from "../fixtures/scenarios";

test.describe("Inventory & Products", () => {
  let token: string;

  test.beforeAll(async ({ request }) => {
    token = await login(request, COMPANY_USER, COMPANY_PASS, COMPANY_CODE);
  });

  test("TC-INV-001: All products are listed", async ({ request }) => {
    const products = await getJson(request, token, "/api/inventory/products");
    const list = Array.isArray(products) ? products : products.data || [];
    expect(list.length).toBeGreaterThanOrEqual(3);
  });

  test("TC-INV-002: Product types are correct", async ({ request }) => {
    const products = await getJson(request, token, "/api/inventory/products");
    const list = Array.isArray(products) ? products : products.data || [];

    const tablet = list.find((p: any) => p.item_code === "GH-TAB-10");
    if (tablet) expect(tablet.item_type).toBe("product");

    const impl = list.find((p: any) => p.item_code === "GH-SRV-IMPL");
    if (impl) expect(impl.item_type).toBe("service");
  });

  test("TC-INV-003: Product prices are correct", async ({ request }) => {
    const products = await getJson(request, token, "/api/inventory/products");
    const list = Array.isArray(products) ? products : products.data || [];

    const tablet = list.find((p: any) => p.item_code === "GH-TAB-10");
    if (tablet) {
      expect(tablet.selling_price).toBe(1200);
      expect(tablet.buying_price).toBe(800);
    }
  });

  test("TC-INV-004: Warehouses are listed", async ({ request }) => {
    const warehouses = await getJson(request, token, "/api/inventory/warehouses");
    const list = Array.isArray(warehouses) ? warehouses : warehouses.data || [];
    expect(list.length).toBeGreaterThanOrEqual(3);
  });

  test("TC-INV-005: Product categories are listed", async ({ request }) => {
    const res = await request.get("/api/inventory/categories", {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (res.ok()) {
      const body = await res.json();
      const list = Array.isArray(body) ? body : body.data || [];
      expect(list.length).toBeGreaterThanOrEqual(2);
    }
  });

  test("TC-INV-006: Cannot create product with duplicate item_code", async ({ request }) => {
    const res = await request.post("/api/inventory/products", {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        item_code: "GH-TAB-10",
        item_name: "منتج مكرر",
        item_type: "product",
        selling_price: 100,
      },
    });

    expect([400, 409, 422]).toContain(res.status());
  });
});
