import { test, expect } from "@playwright/test";
import { login, getJson } from "../fixtures/api-client";
import { COMPANY_CODE, COMPANY_USER, COMPANY_PASS } from "../fixtures/scenarios";

test.describe("Currencies & Exchange Rates", () => {
  let token: string;

  test.beforeAll(async ({ request }) => {
    token = await login(request, COMPANY_USER, COMPANY_PASS, COMPANY_CODE);
  });

  test("TC-CUR-001: Only one base currency", async ({ request }) => {
    const currencies = await getJson(request, token, "/api/currencies/");
    const list = Array.isArray(currencies) ? currencies : currencies.data || [];

    const baseCurrencies = list.filter((c: any) => c.is_base === true);
    expect(baseCurrencies.length).toBe(1);
  });

  test("TC-CUR-002: All required currencies exist", async ({ request }) => {
    const currencies = await getJson(request, token, "/api/currencies/");
    const list = Array.isArray(currencies) ? currencies : currencies.data || [];

    const codes = list.map((c: any) => c.code);
    expect(codes).toContain("SAR");
    expect(codes).toContain("EGP");
    expect(codes).toContain("AED");
    expect(codes).toContain("USD");
  });

  test("TC-CUR-003: Exchange rates are correct", async ({ request }) => {
    const currencies = await getJson(request, token, "/api/currencies/");
    const list = Array.isArray(currencies) ? currencies : currencies.data || [];

    const expectedRates: Record<string, number> = {
      SAR: 1, EGP: 0.076, AED: 1.021, USD: 3.75,
    };

    for (const cur of list) {
      const expected = expectedRates[cur.code];
      if (expected !== undefined) {
        expect(cur.current_rate).toBeCloseTo(expected, 3);
      }
    }
  });

  test("TC-CUR-004: Currency conversion AED to SAR", async ({ request }) => {
    const currencies = await getJson(request, token, "/api/currencies/");
    const list = Array.isArray(currencies) ? currencies : currencies.data || [];

    const aed = list.find((c: any) => c.code === "AED");
    const sar = list.find((c: any) => c.code === "SAR");

    if (aed && sar) {
      const amountAED = 1000;
      const amountSAR = amountAED * (aed.current_rate / sar.current_rate);
      expect(amountSAR).toBeCloseTo(1021, 0);
    }
  });
});
