import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./specs",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [["html", { open: "never" }], ["list"]],
  use: {
    baseURL: process.env.AMAN_API_URL || "http://localhost:8000",
    extraHTTPHeaders: {
      "Accept": "application/json",
      "Content-Type": "application/json",
    },
  },
  projects: [
    { name: "setup", testMatch: /seed\.spec\.ts/ },
    { name: "auth", testMatch: /auth\.spec\.ts/, dependencies: ["setup"] },
    { name: "branches", testMatch: /branches\.spec\.ts/, dependencies: ["setup"] },
    { name: "currencies", testMatch: /currencies\.spec\.ts/, dependencies: ["setup"] },
    { name: "permissions", testMatch: /permissions\.spec\.ts/, dependencies: ["setup"] },
    { name: "financial", testMatch: /financial\.spec\.ts/, dependencies: ["setup"] },
    { name: "inventory", testMatch: /inventory\.spec\.ts/, dependencies: ["setup"] },
    { name: "hr", testMatch: /hr\.spec\.ts/, dependencies: ["setup"] },
    { name: "isolation", testMatch: /isolation\.spec\.ts/, dependencies: ["setup"] },
  ],
});
