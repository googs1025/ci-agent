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

// ── 5. API proxy (frontend → backend) ───────────────────────────────────────
test.describe('API proxy', () => {
  test('backend /health returns ok directly', async ({ page }) => {
    const res = await page.request.get('http://localhost:8000/health');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.status).toBe('ok');
  });

  test('/api/skills returns 4 skills via Next.js proxy', async ({ page }) => {
    const res = await page.request.get('http://localhost:3000/api/skills');
    expect(res.status()).toBe(200);
    const skills = await res.json();
    expect(Array.isArray(skills)).toBeTruthy();
    expect(skills.length).toBe(4);
    const names = skills.map((s: { name: string }) => s.name);
    expect(names).toContain('security-analyst');
    expect(names).toContain('efficiency-analyst');
  });

  test('/api/dashboard returns stats via proxy', async ({ page }) => {
    const res = await page.request.get('http://localhost:3000/api/dashboard');
    expect(res.status()).toBe(200);
    const data = await res.json();
    expect(data).toHaveProperty('repo_count');
    expect(data).toHaveProperty('analysis_count');
  });
});
