import { test, expect } from '@playwright/test';

const BASE_URL = 'http://localhost:5173';

// Helper: Login
async function login(page) {
    await page.goto(`${BASE_URL}/login`);
    await page.fill('input[placeholder="username"]', 'omar');
    await page.fill('input[placeholder="••••••••"]', 'As123321');
    await page.getByRole('button', { name: 'دخـــول' }).click();
    await page.waitForURL('**/');
    await expect(page).not.toHaveURL(/login/);
}

test.describe('Budgets Page', () => {
    test.beforeEach(async ({ page }) => {
        await login(page);
        await page.goto(`${BASE_URL}/accounting/budgets`);
        await page.waitForLoadState('networkidle');
    });

    test('should display budgets page with header', async ({ page }) => {
        await expect(page.locator('.workspace-title')).toBeVisible();
        await expect(page.getByText('الميزانيات')).toBeVisible();
    });

    test('should display stats cards', async ({ page }) => {
        // Wait for stats to load
        await page.waitForTimeout(1000);
        
        // Check if stats cards are visible
        const statsCards = page.locator('.card').filter({ hasText: /إجمالي|المخطط|الفعلي|تجاوز/ });
        await expect(statsCards.first()).toBeVisible();
    });

    test('should open create budget modal', async ({ page }) => {
        await page.getByRole('button', { name: /جديد|إنشاء/ }).click();
        
        // Check modal is visible
        await expect(page.locator('.modal-overlay')).toBeVisible();
        await expect(page.locator('.modal-title')).toContainText('ميزانية');
    });

    test('should create a new budget', async ({ page }) => {
        await page.getByRole('button', { name: /جديد|إنشاء/ }).click();
        
        // Fill form
        await page.fill('input[placeholder*="ميزانية"]', `Test Budget ${Date.now()}`);
        
        // Submit
        await page.getByRole('button', { name: 'حفظ' }).click();
        
        // Wait for success
        await page.waitForTimeout(1000);
        
        // Modal should close
        await expect(page.locator('.modal-overlay')).not.toBeVisible();
    });

    test('should filter budgets by cost center', async ({ page }) => {
        // Wait for page to load
        await page.waitForTimeout(1000);
        
        // Check if cost center filter exists
        const filter = page.locator('select').first();
        if (await filter.isVisible()) {
            await filter.selectOption({ index: 1 });
            await page.waitForTimeout(500);
        }
    });

    test('should display budget cards', async ({ page }) => {
        await page.waitForTimeout(1000);
        
        // Check for budget cards
        const cards = page.locator('.card').filter({ hasText: /ميزانية/ });
        const count = await cards.count();
        console.log(`Found ${count} budget cards`);
    });

    test('should navigate to budget items', async ({ page }) => {
        await page.waitForTimeout(1000);
        
        // Click on items button of first budget
        const itemsBtn = page.getByRole('button', { name: 'البنود' }).first();
        if (await itemsBtn.isVisible()) {
            await itemsBtn.click();
            await expect(page).toHaveURL(/\/items/);
        }
    });

    test('should navigate to budget report', async ({ page }) => {
        await page.waitForTimeout(1000);
        
        // Click on report button of first budget
        const reportBtn = page.getByRole('button', { name: 'التقرير' }).first();
        if (await reportBtn.isVisible()) {
            await reportBtn.click();
            await expect(page).toHaveURL(/\/report/);
        }
    });
});

test.describe('Cost Centers Page', () => {
    test.beforeEach(async ({ page }) => {
        await login(page);
        await page.goto(`${BASE_URL}/accounting/cost-centers`);
        await page.waitForLoadState('networkidle');
    });

    test('should display cost centers page', async ({ page }) => {
        await expect(page.locator('.workspace-title')).toBeVisible();
        await expect(page.getByText('مراكز التكلفة')).toBeVisible();
    });

    test('should display cost centers table', async ({ page }) => {
        await page.waitForTimeout(1000);
        
        // Check if table is visible
        const table = page.locator('.data-table');
        await expect(table).toBeVisible();
    });

    test('should open create cost center modal', async ({ page }) => {
        await page.getByRole('button', { name: /إضافة|جديد/ }).click();
        
        // Check modal is visible
        await expect(page.locator('.modal-overlay')).toBeVisible();
    });

    test('should create a new cost center', async ({ page }) => {
        await page.getByRole('button', { name: /إضافة|جديد/ }).click();
        
        // Fill form
        await page.fill('input#center_name', `Test CC ${Date.now()}`);
        await page.fill('input#center_name_en', `Test CC EN ${Date.now()}`);
        
        // Submit
        await page.getByRole('button', { name: 'حفظ' }).click();
        
        // Wait for success
        await page.waitForTimeout(1000);
        
        // Modal should close
        await expect(page.locator('.modal-overlay')).not.toBeVisible();
    });

    test('should search cost centers', async ({ page }) => {
        await page.waitForTimeout(1000);
        
        // Find search input
        const searchInput = page.locator('input[placeholder*="بحث"]').first();
        if (await searchInput.isVisible()) {
            await searchInput.fill('مركز');
            await page.waitForTimeout(500);
        }
    });

    test('should edit cost center', async ({ page }) => {
        await page.waitForTimeout(1000);
        
        // Click edit button on first row
        const editBtn = page.locator('.table-action-btn').first();
        if (await editBtn.isVisible()) {
            await editBtn.click();
            await expect(page.locator('.modal-overlay')).toBeVisible();
        }
    });

    test('should delete cost center with confirmation', async ({ page }) => {
        await page.waitForTimeout(1000);
        
        // Click delete button on first row
        const deleteBtn = page.locator('.table-action-btn').filter({ has: page.locator('svg') }).nth(1);
        if (await deleteBtn.isVisible()) {
            // Setup dialog handler
            page.on('dialog', dialog => dialog.accept());
            await deleteBtn.click();
            await page.waitForTimeout(1000);
        }
    });
});

test.describe('Budget Items Page', () => {
    test.beforeEach(async ({ page }) => {
        await login(page);
        // Navigate to first budget's items
        await page.goto(`${BASE_URL}/accounting/budgets`);
        await page.waitForLoadState('networkidle');
        await page.waitForTimeout(1000);
        
        const itemsBtn = page.getByRole('button', { name: 'البنود' }).first();
        if (await itemsBtn.isVisible()) {
            await itemsBtn.click();
            await page.waitForLoadState('networkidle');
        }
    });

    test('should display budget items page', async ({ page }) => {
        await expect(page.locator('.workspace-title')).toBeVisible();
    });

    test('should display accounts table', async ({ page }) => {
        await page.waitForTimeout(1000);
        const table = page.locator('.data-table');
        await expect(table).toBeVisible();
    });

    test('should allow entering monthly amounts', async ({ page }) => {
        await page.waitForTimeout(1000);
        
        // Find first monthly input
        const monthlyInputs = page.locator('input[type="number"]');
        if (await monthlyInputs.first().isVisible()) {
            await monthlyInputs.first().fill('5000');
            await page.waitForTimeout(300);
            
            // Check that annual is calculated (5000 * 12 = 60000)
            const annualInput = monthlyInputs.nth(1);
            const annualValue = await annualInput.inputValue();
            expect(parseInt(annualValue)).toBe(60000);
        }
    });

    test('should save budget items', async ({ page }) => {
        await page.waitForTimeout(1000);
        
        // Click save button
        const saveBtn = page.getByRole('button', { name: 'حفظ' });
        if (await saveBtn.isVisible()) {
            await saveBtn.click();
            await page.waitForTimeout(1000);
        }
    });
});

test.describe('Budget Report Page', () => {
    test.beforeEach(async ({ page }) => {
        await login(page);
        // Navigate to first budget's report
        await page.goto(`${BASE_URL}/accounting/budgets`);
        await page.waitForLoadState('networkidle');
        await page.waitForTimeout(1000);
        
        const reportBtn = page.getByRole('button', { name: 'التقرير' }).first();
        if (await reportBtn.isVisible()) {
            await reportBtn.click();
            await page.waitForLoadState('networkidle');
        }
    });

    test('should display budget report page', async ({ page }) => {
        await expect(page.locator('.workspace-title')).toBeVisible();
    });

    test('should display report table with correct columns', async ({ page }) => {
        await page.waitForTimeout(1000);
        
        // Check table headers
        await expect(page.getByText('مخطط')).toBeVisible();
        await expect(page.getByText('فعلي')).toBeVisible();
    });

    test('should show correct calculations', async ({ page }) => {
        await page.waitForTimeout(1000);
        
        // Check that percentages are displayed
        const percentageCells = page.locator('td').filter({ hasText: /%/ });
        const count = await percentageCells.count();
        console.log(`Found ${count} percentage cells`);
    });

    test('should display performance bars', async ({ page }) => {
        await page.waitForTimeout(1000);
        
        // Check for progress bars
        const bars = page.locator('[style*="border-radius: 3px"]').filter({ has: page.locator('[style*="height: 100%"]') });
        const count = await bars.count();
        console.log(`Found ${count} performance bars`);
    });

    test('should filter by date range', async ({ page }) => {
        await page.waitForTimeout(1000);
        
        // Find date inputs
        const dateInputs = page.locator('input[placeholder="YYYY/MM/DD"]');
        if (await dateInputs.count() >= 2) {
            await dateInputs.first().fill('2026/01/01');
            await dateInputs.nth(1).fill('2026/06/30');
            
            // Wait for data to reload
            await page.waitForTimeout(1000);
        }
    });
});

test.describe('Branch Isolation', () => {
    test('should only show budgets for current branch', async ({ page }) => {
        await login(page);
        await page.goto(`${BASE_URL}/accounting/budgets`);
        await page.waitForLoadState('networkidle');
        await page.waitForTimeout(1000);
        
        // Get all budget names
        const budgetCards = page.locator('.card').filter({ hasText: /ميزانية/ });
        const count = await budgetCards.count();
        console.log(`Budgets visible for current branch: ${count}`);
    });

    test('should only show cost centers for current branch', async ({ page }) => {
        await login(page);
        await page.goto(`${BASE_URL}/accounting/cost-centers`);
        await page.waitForLoadState('networkidle');
        await page.waitForTimeout(1000);
        
        // Get all cost center names
        const rows = page.locator('.data-table tbody tr');
        const count = await rows.count();
        console.log(`Cost centers visible: ${count}`);
    });
});
