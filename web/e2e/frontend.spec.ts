import { test, expect } from '@playwright/test';

// ── 1. Dashboard ────────────────────────────────────────────────────────────
test.describe('Dashboard', () => {
  test('loads and shows key sections', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/dashboard/i);
    // Header nav
    await expect(page.getByRole('link', { name: /analyze/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /skills/i })).toBeVisible();
    // Page should not show an error boundary
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).not.toContainText('Internal Server Error');
  });
});

// ── 2. Analyze page ─────────────────────────────────────────────────────────
test.describe('Analyze page', () => {
  test('renders form with disabled submit button when empty', async ({ page }) => {
    await page.goto('/analyze');
    await expect(page.locator('input[type="text"], input[placeholder]').first()).toBeVisible();
    // Submit button text is "Start Analysis"
    const btn = page.getByRole('button', { name: /start analysis/i });
    await expect(btn).toBeVisible();
    // Button is disabled when repo input is empty
    await expect(btn).toBeDisabled();
  });

  test('accepts repo input and enables submit', async ({ page }) => {
    await page.goto('/analyze');
    const input = page.locator('input[type="text"], input[placeholder]').first();
    await input.fill('anthropics/anthropic-sdk-python');
    await expect(input).toHaveValue('anthropics/anthropic-sdk-python');
    // Button should become enabled after input (skills are pre-selected by default)
    const btn = page.getByRole('button', { name: /start analysis/i });
    await expect(btn).toBeEnabled();
  });
});

// ── 3. Reports list ─────────────────────────────────────────────────────────
test.describe('Reports page', () => {
  test('loads without error', async ({ page }) => {
    await page.goto('/reports');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).not.toContainText('Internal Server Error');
    const body = await page.locator('body').innerText();
    expect(body.length).toBeGreaterThan(10);
  });
});

// ── 4. Skills page ──────────────────────────────────────────────────────────
test.describe('Skills page', () => {
  test('shows 4 built-in skills', async ({ page }) => {
    await page.goto('/skills');
    await page.waitForLoadState('networkidle');
    for (const skill of ['efficiency', 'security', 'cost', 'error']) {
      await expect(page.locator('body')).toContainText(new RegExp(skill, 'i'));
    }
  });

  test('Install Skill button opens modal', async ({ page }) => {
    await page.goto('/skills');
    const installBtn = page.getByRole('button', { name: /install/i });
    await expect(installBtn).toBeVisible();
    await installBtn.click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).not.toBeVisible();
  });

  test('skill card click opens detail drawer', async ({ page }) => {
    await page.goto('/skills');
    await page.waitForLoadState('networkidle');
    // Skill cards are <button> elements inside the skills list
    const firstCard = page.getByRole('button').filter({ hasText: /analyst/i }).first();
    await expect(firstCard).toBeVisible();
    await firstCard.click();
    // Drawer should show skill details
    await expect(page.locator('body')).toContainText(/dimension|requires|description/i);
  });
});

// ── 5. Trend charts ─────────────────────────────────────────────────────────
test.describe('Trend Analysis', () => {
  test('trend section renders with date range selector', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    // Should have 7d/30d/90d buttons
    await expect(page.getByRole('button', { name: '7d' })).toBeVisible();
    await expect(page.getByRole('button', { name: '30d' })).toBeVisible();
    await expect(page.getByRole('button', { name: '90d' })).toBeVisible();
  });

  test('trend section shows insights or empty state', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    // Wait for trends to load — either insight text or empty state
    const body = page.locator('body');
    await expect(
      body.getByText(/Insights|No trend data|分析洞察|暂无趋势/).first()
    ).toBeVisible({ timeout: 10000 });
  });

  test('clicking date range buttons fetches new data', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    // Click 7d
    await page.getByRole('button', { name: '7d' }).click();
    // Should still show trend section without error
    await expect(page.locator('body')).not.toContainText('Internal Server Error');
    // Click 90d
    await page.getByRole('button', { name: '90d' }).click();
    await expect(page.locator('body')).not.toContainText('Internal Server Error');
  });
});

// ── 6. Language switching ───────────────────────────────────────────────────
test.describe('Language switching (i18n)', () => {
  test('language toggle button is visible in navbar', async ({ page }) => {
    await page.goto('/');
    const langBtn = page.getByRole('button', { name: /switch language/i });
    await expect(langBtn).toBeVisible();
  });

  test('switch to Chinese and verify UI text', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    // Click to switch to Chinese (button shows "中文")
    const langBtn = page.getByRole('button', { name: /switch language/i });
    const btnText = await langBtn.textContent();
    // If currently EN, button shows "中文"; click to switch
    if (btnText?.includes('中文')) {
      await langBtn.click();
    }
    // Verify Chinese text appears
    await expect(page.locator('body')).toContainText('仪表盘');
    await expect(page.locator('body')).toContainText('分析');
    await expect(page.locator('body')).toContainText('报告');
    await expect(page.locator('body')).toContainText('技能');
  });

  test('switch back to English and verify UI text', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    const langBtn = page.getByRole('button', { name: /switch language/i });
    // Click twice to ensure we end up on English
    await langBtn.click();
    await langBtn.click();
    // Verify English text
    await expect(page.getByRole('link', { name: /dashboard/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /analyze/i })).toBeVisible();
  });

  test('language preference persists after reload', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    // Switch to Chinese
    const langBtn = page.getByRole('button', { name: /switch language/i });
    const btnText = await langBtn.textContent();
    if (btnText?.includes('中文')) {
      await langBtn.click();
    }
    await expect(page.locator('body')).toContainText('仪表盘');
    // Reload
    await page.reload();
    await page.waitForLoadState('networkidle');
    // Should still be Chinese
    await expect(page.locator('body')).toContainText('仪表盘');
  });
});

// ── 7. Dashboard trends API ─────────────────────────────────────────────────
test.describe('Trends API', () => {
  test('/api/dashboard/trends returns valid structure', async ({ page }) => {
    const res = await page.request.get(`${BASE}/api/dashboard/trends?days=30`);
    expect(res.status()).toBe(200);
    const data = await res.json();
    expect(data).toHaveProperty('daily_scores');
    expect(data).toHaveProperty('dimension_trends');
    expect(data).toHaveProperty('repo_comparison');
    expect(Array.isArray(data.daily_scores)).toBeTruthy();
    expect(Array.isArray(data.dimension_trends)).toBeTruthy();
    expect(Array.isArray(data.repo_comparison)).toBeTruthy();
  });
});

// ── 8. API proxy (frontend → backend) ───────────────────────────────────────
const BASE = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:3000';
const BACKEND = process.env.PLAYWRIGHT_BACKEND_URL || 'http://localhost:8000';

test.describe('API proxy', () => {
  test('backend /health returns ok directly', async ({ page }) => {
    const res = await page.request.get(`${BACKEND}/health`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.status).toBe('ok');
  });

  test('/api/skills returns 4 skills via Next.js proxy', async ({ page }) => {
    const res = await page.request.get(`${BASE}/api/skills`);
    expect(res.status()).toBe(200);
    const skills = await res.json();
    expect(Array.isArray(skills)).toBeTruthy();
    expect(skills.length).toBe(4);
    const names = skills.map((s: { name: string }) => s.name);
    expect(names).toContain('security-analyst');
    expect(names).toContain('efficiency-analyst');
  });

  test('/api/dashboard returns stats via proxy', async ({ page }) => {
    const res = await page.request.get(`${BASE}/api/dashboard`);
    expect(res.status()).toBe(200);
    const data = await res.json();
    expect(data).toHaveProperty('repo_count');
    expect(data).toHaveProperty('analysis_count');
  });
});
