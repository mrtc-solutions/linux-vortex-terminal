import { test, expect, Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { userInfo } from 'node:os';

// No route interception and no mocked API responses. Use disposable sidecar data.
test.beforeEach(async ({ page }) => {
  if (process.env.VORTEX_REAL_ACCEPTANCE !== '1' || !process.env.VORTEX_TEST_TOKEN_FILE) {
    throw new Error('Set VORTEX_REAL_ACCEPTANCE=1 and VORTEX_TEST_TOKEN_FILE for an isolated test sidecar.');
  }
  const token = readFileSync(process.env.VORTEX_TEST_TOKEN_FILE, 'utf8').trim();
  await page.goto(`/#vortex-token=${encodeURIComponent(token)}`);
  await expect(page.getByTitle('Sidecar connected')).toBeVisible({ timeout: 30000 });
  expect(new URL(page.url()).hash).toBe('');
});
test.afterEach(async ({ page }) => {
  // Test-owned backend only: don't let a failed browser assertion leak a PTY
  // into the next case. Page destruction doesn't run React unmount handlers.
  await page.request.post('/api/control/stop-all');
});
async function open(page: Page, name: string) {
  await page.getByTitle('Vortex Terminal start menu', { exact: true }).click();
  await page.getByRole('dialog', { name: 'VORTEX TERMINAL START MENU', exact: true })
    .getByRole('button', { name: new RegExp(`^${name} `) }).click();
}

test('real authenticated backend, model availability, and dependency inventory', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const model = await (await page.request.get('/api/models')).json();
  expect(model.model.providers).toBeTruthy();
  await open(page, 'Models');
  await expect(page.getByRole('dialog', { name: 'LOCAL AI / MODELS', exact: true }).getByText('GGUF files', { exact: true })).toBeVisible();
  await page.getByRole('dialog', { name: 'LOCAL AI / MODELS', exact: true }).getByLabel('Close window').click();
  const inventory = await (await page.request.get('/api/dependencies')).json();
  expect(Array.isArray(inventory.dependencies.missing)).toBe(true);
  await open(page, 'Dependencies');
  const deps = page.getByRole('dialog', { name: 'MISSING DEPENDENCIES', exact: true });
  if (inventory.dependencies.missing.length) {
    const item = inventory.dependencies.missing[0];
    await expect(deps.getByRole('button', { name: `Review ${item.title || item.id}`, exact: true })).toBeVisible();
    await deps.getByRole('button', { name: `Review ${item.title || item.id}`, exact: true }).click();
    await expect(deps.getByText('Source:', { exact: false })).toBeVisible({ timeout: 30000 });
  }
  expect(errors).toEqual([]);
});

test('real whoami operation and conversation resume roundtrip', async ({ page }) => {
  const input = page.getByPlaceholder('Ask Vortex Terminal anything', { exact: false });
  const turnResponse = page.waitForResponse(r => r.url().endsWith('/api/workspace/turn') && r.request().method() === 'POST');
  await input.fill('whoami'); await input.press('Enter');
  const response = await turnResponse;
  expect(response.ok()).toBe(true);
  const turn = await response.json();
  let operationId = turn.operation?.id;
  if (!operationId) {
    // The default safe profile requires explicit approval even for whoami.
    const executed = page.waitForResponse(r => r.url().endsWith('/api/execute') && r.request().method() === 'POST');
    await page.getByRole('dialog', { name: 'GUARDIAN PLAN REVIEW', exact: true }).getByRole('button', { name: /APPROVE/ }).click();
    const result = await (await executed).json();
    operationId = result.operation?.id;
  }
  expect(operationId).toBeTruthy();
  await expect.poll(async () => {
    const data = await (await page.request.get(`/api/operations/${operationId}`)).json();
    return data.operation.status;
  }, { timeout: 30000 }).toBe('succeeded');
  const observed = await (await page.request.get(`/api/operations/${operationId}`)).json();
  expect(observed.operation.commands[0].stdout.trim()).toBe(userInfo().username);
  await expect(page.locator('main')).toContainText(`[exit 0]\n${userInfo().username}`, { timeout: 30000 });
  const detail = await (await page.request.get(`/api/conversations/${turn.conversation.id}`)).json();
  expect(detail.messages.some((m: { content: string }) => m.content === 'whoami')).toBe(true);
  const uniqueTitle = `Acceptance ${turn.conversation.id}`;
  await page.request.post(`/api/conversations/${turn.conversation.id}/rename`, { data: { title: uniqueTitle } });
  await open(page, 'Conversations');
  const history = page.getByRole('dialog', { name: 'CONVERSATIONS', exact: true });
  const row = history.getByText(uniqueTitle, { exact: true }).locator('../..');
  await row.first().getByRole('button', { name: 'Resume', exact: true }).click();
  await expect(history).toHaveCount(0);
  await expect(page.locator('main').getByText('whoami', { exact: true }).first()).toBeVisible();
  await expect(page.locator('main')).toContainText(`[exit 0]\n${userInfo().username}`);
});

test('live PTY output, tab navigation, and cleanup on popup close', async ({ page }) => {
  await open(page, 'Host Shell');
  const shell = page.getByRole('dialog', { name: 'HOST SHELL (LIVE PTY)', exact: true });
  const input = shell.getByPlaceholder('Type into the live host shell…');
  await expect(input).toBeEnabled({ timeout: 15000 });
  await expect.poll(async () => {
    const sessions = await (await page.request.get('/api/sessions')).json();
    return sessions.sessions.filter((s: { status: string }) => s.status === 'running').length;
  }, { timeout: 10000 }).toBe(1);
  // Constructed marker avoids matching merely the echoed command.
  await input.fill("printf 'VORTEX_%s_OK\\n' PTY"); await input.press('Enter');
  await expect(shell.locator('pre')).toContainText('VORTEX_PTY_OK', { timeout: 15000 });
  await page.getByRole('button', { name: 'Tactical Map', exact: true }).click();
  await expect(shell.locator('pre')).toContainText('VORTEX_PTY_OK');
  await shell.getByLabel('Close window').click();
  await expect.poll(async () => {
    const data = await (await page.request.get('/api/sessions')).json();
    return data.sessions.filter((s: { status: string }) => s.status === 'running').length;
  }).toBe(0);
});

test('real conversation search, read, edit and branch preserve the original', async ({ page }) => {
  const created = await (await page.request.post('/api/workspace/turn', { data: { request: 'whoami' } })).json();
  const id = created.conversation.id;
  const unique = `Branch test ${id}`;
  await page.request.post(`/api/conversations/${id}/rename`, { data: { title: unique } });
  await open(page, 'Conversations');
  const history = page.getByRole('dialog', { name: 'CONVERSATIONS', exact: true });
  await history.getByLabel('Search conversations').fill(unique);
  await expect(history.getByRole('button', { name: 'Read messages', exact: true })).toHaveCount(1);
  await history.getByRole('button', { name: 'Read messages', exact: true }).click();
  await history.getByRole('button', { name: 'Edit & Branch', exact: true }).click();
  await history.getByLabel('Edit instruction').fill('check disk usage');
  const branch = page.waitForResponse(r => /\/messages\/[^/]+\/edit$/.test(r.url()));
  await history.getByRole('button', { name: 'Save & Branch', exact: true }).click();
  const result = await (await branch).json();
  expect(result.conversation.id).not.toBe(id);
  await expect(history).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem('vortex.conversationId'))).toBe(result.conversation.id);
  const original = await (await page.request.get(`/api/conversations/${id}`)).json();
  expect(original.messages.some((m: { content: string }) => m.content === 'whoami')).toBe(true);
});

test('two shell windows own independent PTYs and closing one preserves the other', async ({ page }) => {
  await open(page, 'Host Shell');
  const shells = page.getByRole('dialog', { name: 'HOST SHELL (LIVE PTY)', exact: true });
  await expect(shells.first().getByPlaceholder('Type into the live host shell…')).toBeEnabled();
  await shells.first().getByLabel('Minimize window').click();
  await open(page, 'Host Shell');
  await expect(shells.getByPlaceholder('Type into the live host shell…')).toBeEnabled();
  await shells.getByLabel('Close window').click();
  await expect.poll(async () => {
    const data = await (await page.request.get('/api/sessions')).json();
    return data.sessions.filter((s: { status: string }) => s.status === 'running').length;
  }).toBe(1);
  await page.getByTitle('Restore HOST SHELL (LIVE PTY)', { exact: true }).click();
  await shells.getByLabel('Close window').click();
  await expect.poll(async () => {
    const data = await (await page.request.get('/api/sessions')).json();
    return data.sessions.filter((s: { status: string }) => s.status === 'running').length;
  }).toBe(0);
});
