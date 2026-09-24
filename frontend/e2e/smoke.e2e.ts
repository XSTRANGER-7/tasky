/**
 * The demo script as a test: sign in, create a task, discuss it with an @mention,
 * resolve it, and check that the right people hear about it. Runs against the seeded
 * demo database (see playwright.config.ts).
 */
import { expect, test, type Page } from '@playwright/test'

async function signInAs(page: Page, account: 'Admin' | 'Member' | 'Viewer') {
  await page.goto('/login')
  // The login page's one-click demo buttons fill the seeded demo credentials.
  await page.getByRole('button', { name: account, exact: true }).click()
  await page.getByRole('button', { name: 'Sign in' }).click()
  // Sign-in returns to wherever the visitor was headed, so wait for the shell itself.
  await expect(page.getByRole('button', { name: 'Account menu' })).toBeVisible()
}

test.describe('smoke', () => {
  test('create, discuss and resolve a task', async ({ page, isMobile }) => {
    test.skip(isMobile, 'the full flow runs on desktop; the mobile project checks layout')
    const title = `E2E checkout latency ${Date.now()}`

    await signInAs(page, 'Admin')
    await page.goto('/')
    await expect(page.getByRole('img', { name: /Open backlog/ })).toBeVisible()

    // Report (keyboard shortcut opens the drawer). With AI on, the triage card appears
    // after a pause in typing; its suggestion is not applied unless accepted.
    await page.keyboard.press('c')
    const drawer = page.getByRole('dialog')
    await drawer.getByLabel('Title').fill(title)
    const card = drawer.getByRole('region', { name: 'AI triage suggestion' })
    const aiOn = await card
      .waitFor({ timeout: 4000 })
      .then(() => true)
      .catch(() => false) // LLM_PROVIDER=none: no card, and that is correct too
    if (aiOn) await expect(card).toContainText('Confidence')
    await drawer.getByRole('button', { name: 'Create task' }).click()
    await expect(page.getByRole('heading', { name: title })).toBeVisible()
    const key =
      (await page
        .locator('main')
        .getByText(/^(?:TASK|INC)-\d+$/)
        .first()
        .textContent()) ?? ''
    expect(key).toMatch(/^(?:TASK|INC)-\d+$/)

    // Attach a log file; it is listed with its size.
    await page.getByLabel('Choose files to attach').setInputFiles({
      name: 'gateway-errors.log',
      mimeType: 'text/plain',
      buffer: Buffer.from('2026-09-22T14:02Z ERROR upstream timed out\n'),
    })
    await expect(page.getByText('Attached gateway-errors.log')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Download gateway-errors.log' })).toBeAttached()

    // Watch it, then mention Mira in a comment via the autocomplete.
    await page.getByRole('button', { name: 'Watch', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Watching' })).toBeVisible()
    const box = page.getByRole('combobox', { name: 'Comment' })
    await box.fill('')
    await box.pressSequentially('@mir')
    await page.getByRole('option', { name: /Mira/ }).click()
    await box.pressSequentially('can you check the payment gateway latency?')
    await expect(box).toHaveValue('@mira can you check the payment gateway latency?')
    await page.getByRole('button', { name: 'Comment', exact: true }).click()
    await expect(page.getByText('can you check the payment gateway latency?')).toBeVisible()

    // Resolve with a note; the timeline records it.
    await page.getByRole('button', { name: /^Status: / }).click()
    await page.getByRole('menuitem', { name: /Resolve/ }).click()
    await page.getByRole('dialog').getByRole('textbox').fill('Rolled back the gateway config.')
    await page.getByRole('dialog').getByRole('button', { name: 'Resolve' }).click()
    await expect(page.getByRole('button', { name: /^Status: Resolved/ })).toBeVisible()
    await page.getByRole('tab', { name: 'Activity' }).click()
    await expect(page.getByText('Rolled back the gateway config.')).toBeVisible()

    // It shows up in the Watching view and in search.
    await page.goto('/tasks?view=watching')
    await expect(page.getByText(title)).toBeVisible()

    // Mira was notified of the mention.
    await page.getByRole('button', { name: 'Account menu' }).click()
    await page.getByRole('menuitem', { name: 'Sign out' }).click()
    await signInAs(page, 'Member')
    await page.goto('/notifications')
    await expect(page.getByText(new RegExp(key)).first()).toBeVisible()
  })

  test('admin pages and settings work', async ({ page, isMobile }) => {
    test.skip(isMobile, 'desktop navigation')
    await signInAs(page, 'Admin')

    await page.getByRole('link', { name: 'Users', exact: true }).click()
    await expect(page.getByRole('table', { name: 'Users' })).toBeVisible()
    await expect(page.getByText('mira@demo.io')).toBeVisible()

    await page.getByRole('link', { name: 'Configuration', exact: true }).click()
    await expect(page.getByRole('img', { name: /critical: first response/ })).toBeVisible()

    await page.getByRole('link', { name: 'Email outbox', exact: true }).click()
    await expect(page.getByText(/Worker: /)).toBeVisible()

    await page.goto('/settings')
    await page.getByRole('radio', { name: /Light/ }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    await page.getByRole('radio', { name: /Dark/ }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')

    await page.keyboard.press('Shift+?')
    await expect(page.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeVisible()
  })

  test('viewers cannot report or reach admin pages', async ({ page, isMobile }) => {
    test.skip(isMobile, 'desktop navigation')
    await signInAs(page, 'Viewer')
    await expect(page.getByRole('button', { name: 'New task' })).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Users', exact: true })).toHaveCount(0)
    await page.goto('/admin/users')
    await expect(page.getByRole('heading', { name: 'Admins only' })).toBeVisible()
  })

  test('cleanup: soft-delete the tasks this suite created', async ({ page, isMobile }) => {
    test.skip(isMobile, 'runs once, on desktop')
    await signInAs(page, 'Admin')
    // Soft delete only: they stay restorable from the recycle bin (?deleted=true).
    for (let i = 0; i < 20; i++) {
      await page.goto('/tasks?q=E2E%20checkout%20latency')
      await expect(page.locator('main h1').first()).toBeVisible()
      const row = page.locator('main a[href^="/tasks/"]', {
        hasText: 'E2E checkout latency',
      })
      await page.waitForTimeout(500) // let the search settle
      if ((await row.count()) === 0) break
      await row.first().click()
      await page.getByRole('button', { name: 'Delete task' }).click()
      await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click()
      await expect(page.getByText(/in the recycle bin|deleted/i).first()).toBeVisible()
    }
  })

  test('phone layout: bottom bar, More sheet, no horizontal scroll', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'mobile project only')
    await signInAs(page, 'Admin')

    const bar = page.getByRole('navigation', { name: 'Main (mobile)' })
    await expect(bar).toBeVisible()
    await bar.getByRole('link', { name: 'Tasks' }).click()
    await expect(page.getByRole('heading', { name: 'Tasks' })).toBeVisible()

    await bar.getByRole('button', { name: 'More' }).click()
    const sheet = page.getByRole('dialog', { name: 'More' })
    await sheet.getByRole('link', { name: 'Settings' }).click()
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()

    for (const path of ['/', '/tasks', '/notifications', '/admin/users', '/settings']) {
      await page.goto(path)
      await expect(page.locator('main h1').first()).toBeVisible() // SSE keeps the network busy
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
      expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(1)
    }
  })
})
