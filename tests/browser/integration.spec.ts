import { test as base, expect, Page } from '@playwright/test';

const test = base.extend<{ uncaughtErrors: void }>({
  uncaughtErrors: [async ({ page }, use) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await use();
    expect(errors, 'Uncaught browser errors').toEqual([]);
  }, { auto: true }],
});

// Real React app in Chromium. Only the sidecar is mocked: no host operations run.
async function boot(page: Page) {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = {};
    if (path === '/api/conversations') data = route.request().method() === 'POST'
      ? { conversation: { id: 'new' } }
      : { conversations: [{ id: 'saved', title: 'Saved thread', status: 'active' }] };
    if (path === '/api/conversations/saved') data = { conversation: { id: 'saved' }, messages: [
      { id: 'm1', role: 'user', content: 'Previous question' },
      { id: 'm2', role: 'vortex', content: 'Previous observed answer' },
    ] };
    if (path === '/api/conversations/new') data = { conversation: { id: 'new' }, messages: [] };
    if (path === '/api/dependencies') data = { dependencies: { missing: [{ id: 'tool:test', title: 'Test tool', method: 'apt' }] } };
    if (path === '/api/dependencies/proposal') data = { install: { title: 'Test tool', method: 'apt', commands: ['apt install test'], plan_request: 'install test' } };
    if (path === '/api/dependencies/plan') data = { planned: true, plan: { id: 'p1', commands: [{ display: 'apt install test' }], approval_token: 'test-token' }, guardian: { decision: 'review', risk: 'high' } };
    await route.fulfill({ json: data });
  });
  await page.goto('/');
  await expect(page.getByTitle('Sidecar connected')).toBeVisible();
}
async function open(page: Page, label: string) {
  await page.getByTitle('Vortex Terminal start menu', { exact: true }).click();
  await page.getByRole('dialog', { name: 'VORTEX TERMINAL START MENU', exact: true })
    .getByRole('button', { name: new RegExp(`^${label} `) }).click();
}
const history = (page: Page) => page.getByRole('dialog', { name: 'CONVERSATIONS', exact: true });

test('resume and new keep visible transcript and next-turn context together', async ({ page }) => {
  await boot(page);
  await page.getByRole('button', { name: 'Tactical Map', exact: true }).click();
  await open(page, 'Conversations');
  await history(page).getByRole('button', { name: 'Resume', exact: true }).click();
  await expect(page.getByText('Previous observed answer', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('vortex.conversationId'))).toBe('saved');
  let context: unknown;
  await page.route('**/api/workspace/turn', async route => {
    context = route.request().postDataJSON().conversation_id;
    await route.fulfill({ json: { explanation: 'Context received', plan: {}, guardian: {} } });
  });
  await page.getByPlaceholder('Ask Vortex Terminal anything', { exact: false }).fill('check disk usage');
  await page.getByPlaceholder('Ask Vortex Terminal anything', { exact: false }).press('Enter');
  await expect.poll(() => context).toBe('saved');
  await expect(page.getByText(/Context received/)).toBeVisible();
  await open(page, 'Conversations');
  await history(page).getByRole('button', { name: 'New', exact: true }).click();
  await expect(history(page)).toHaveCount(0);
  await expect(page.getByText('Previous observed answer', { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem('vortex.conversationId'))).toBe('new');
});

test('failed resume preserves old context and displays the API error', async ({ page }) => {
  await boot(page);
  await page.evaluate(() => localStorage.setItem('vortex.conversationId', 'old'));
  await page.route('**/api/conversations/saved', route => route.fulfill({ status: 500, json: { error: { message: 'Cannot load thread' } } }));
  await open(page, 'Conversations');
  await history(page).getByRole('button', { name: 'Resume', exact: true }).click();
  await expect(history(page).getByText('Cannot load thread')).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('vortex.conversationId'))).toBe('old');
});

test('Escape cancels inline rename without closing its window', async ({ page }) => {
  await boot(page); await open(page, 'Conversations');
  await history(page).getByRole('button', { name: 'Rename', exact: true }).click();
  await history(page).getByLabel('Rename conversation').press('Escape');
  await expect(history(page)).toBeVisible();
  await expect(history(page).getByLabel('Rename conversation')).toHaveCount(0);
});

test('dependencies are reachable from Tools and plans require review', async ({ page }) => {
  const mutations: string[] = [];
  page.on('request', r => { if (r.method() === 'POST') mutations.push(new URL(r.url()).pathname); });
  await boot(page); await open(page, 'Tools');
  await page.getByRole('button', { name: 'Missing dependencies', exact: true }).click();
  await page.getByRole('button', { name: 'Review Test tool', exact: true }).click();
  await page.getByRole('button', { name: 'Create reviewed install plan', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'GUARDIAN PLAN REVIEW', exact: true })).toBeVisible();
  expect(mutations).toEqual(['/api/dependencies/plan']);
});

test('dependency errors are visible and refresh recovers', async ({ page }) => {
  await boot(page);
  await page.route('**/api/dependencies', route => route.fulfill({ status: 503, json: { error: { message: 'Inventory offline' } } }));
  await open(page, 'Dependencies');
  await expect(page.getByText('Inventory offline')).toBeVisible();
  await page.unroute('**/api/dependencies');
  await page.getByRole('button', { name: 'Refresh dependencies' }).click();
  await expect(page.getByRole('button', { name: 'Review Test tool' })).toBeVisible();
});

test('ninth popup does not evict the first; narrow windows remain on screen', async ({ page }) => {
  await boot(page);
  for (let i = 0; i < 9; i++) {
    await open(page, 'Tools');
    await page.getByRole('dialog', { name: 'TOOLS', exact: true }).last().getByLabel('Minimize window').click();
  }
  await expect(page.locator('[role="dialog"]')).toHaveCount(9);
  await page.setViewportSize({ width: 375, height: 667 });
  await page.getByTitle('Restore TOOLS', { exact: true }).last().click();
  const dialog = page.getByRole('dialog', { name: 'TOOLS', exact: true });
  const rect = await dialog.locator(':scope > div').boundingBox();
  expect(rect).not.toBeNull();
  expect(rect!.x).toBeGreaterThanOrEqual(0);
  expect(rect!.x + rect!.width).toBeLessThanOrEqual(375);
  expect(rect!.y + rect!.height).toBeLessThanOrEqual(667);
  await dialog.getByLabel('Maximize window').click();
  await expect(dialog.getByLabel('Restore window')).toBeVisible();
});

test('navigation preserves a delayed turn and resume cannot change its context', async ({ page }) => {
  await boot(page);
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let requested = false;
  await page.route('**/api/workspace/turn', async route => {
    requested = true; await gate;
    await route.fulfill({ json: { explanation: 'Delayed operation result', plan: {}, guardian: {} } });
  });
  const input = page.getByPlaceholder('Ask Vortex Terminal anything', { exact: false });
  await input.fill('check disk usage'); await input.press('Enter');
  await expect.poll(() => requested).toBe(true);
  await page.getByRole('button', { name: 'Tactical Map', exact: true }).click();
  await open(page, 'Conversations');
  await history(page).getByRole('button', { name: 'Resume', exact: true }).click();
  await expect(history(page).getByText('Wait for the active operation before switching conversations.')).toBeVisible();
  release();
  await history(page).getByLabel('Close window').click();
  await page.getByRole('button', { name: 'Terminal', exact: true }).click();
  await expect(page.getByText(/Delayed operation result/)).toBeVisible();
});

test('titlebar dragging moves a window and clamps at screen edges', async ({ page }) => {
  await boot(page); await open(page, 'Tools');
  const dialog = page.getByRole('dialog', { name: 'TOOLS', exact: true });
  const title = dialog.getByText('TOOLS', { exact: true });
  const before = await dialog.locator(':scope > div').boundingBox();
  const box = await title.boundingBox();
  await page.mouse.move(box!.x + 10, box!.y + 5);
  await page.mouse.down(); await page.mouse.move(5, 5); await page.mouse.up();
  const after = await dialog.locator(':scope > div').boundingBox();
  expect(after!.x).toBeLessThan(before!.x);
  expect(after!.x).toBeGreaterThanOrEqual(16);
  expect(after!.y).toBeGreaterThanOrEqual(16);
});

test('an executing approval still blocks resume after its window is closed', async ({ page }) => {
  await boot(page);
  await open(page, 'Dependencies');
  await page.getByRole('button', { name: 'Review Test tool', exact: true }).click();
  await page.getByRole('button', { name: 'Create reviewed install plan', exact: true }).click();
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let requested = false;
  await page.route('**/api/execute', async route => {
    requested = true; await gate;
    await route.fulfill({ status: 500, json: { error: { message: 'Test execution stopped' } } });
  });
  const approval = page.getByRole('dialog', { name: 'GUARDIAN PLAN REVIEW', exact: true });
  await approval.getByRole('button', { name: /APPROVE/ }).click();
  await expect.poll(() => requested).toBe(true);
  await approval.getByLabel('Close window').click();
  await open(page, 'Conversations');
  await history(page).getByRole('button', { name: 'Resume', exact: true }).click();
  await expect(history(page).getByText(/Close or finish the pending approval/)).toBeVisible();
  release();
});

test('model management sends reviewed API shapes and confirms downloads', async ({ page }) => {
  await boot(page);
  await page.route('**/api/models/gguf', route => route.fulfill({ json: { gguf: { files: [{ name: 'example.gguf' }] } } }));
  await page.route('**/api/ollama', route => route.fulfill({ json: { ollama: { installed: true, api_state: 'healthy' }, models: { items: [{ name: 'example:1b', installed: true }] } } }));
  const changes: { path: string; body: unknown }[] = [];
  await page.route('**/api/models/gguf/activate', async route => { changes.push({ path: new URL(route.request().url()).pathname, body: route.request().postDataJSON() }); await route.fulfill({ json: {} }); });
  await page.route('**/api/ollama/models/pull', async route => { changes.push({ path: new URL(route.request().url()).pathname, body: route.request().postDataJSON() }); await route.fulfill({ json: {} }); });
  await open(page, 'Models');
  const models = page.getByRole('dialog', { name: 'LOCAL AI / MODELS', exact: true });
  await models.getByRole('button', { name: 'Use example.gguf for primary', exact: true }).click();
  await expect.poll(() => changes.length).toBe(1);
  expect(changes[0].body).toEqual({ file: 'example.gguf', role: 'primary' });
  await models.getByLabel('Ollama model name').fill('example:1b');
  await models.getByRole('button', { name: 'Download named model' }).click();
  expect(changes).toHaveLength(1);
  await models.getByRole('button', { name: 'Confirm model change', exact: true }).click();
  await expect.poll(() => changes.length).toBe(2);
  expect(changes[1].body).toEqual({ name: 'example:1b', role: 'primary' });
});

test('native application controls use the preload bridge', async ({ page }) => {
  await page.addInitScript(() => {
    const w = window as unknown as { vortexWindow: unknown; nativeActions: string[] };
    w.nativeActions = [];
    w.vortexWindow = {
      getState: async () => ({ maximized: false }), onStateChange: () => () => {},
      minimize: () => w.nativeActions.push('minimize'),
      toggleMaximize: () => w.nativeActions.push('maximize'), close: () => w.nativeActions.push('close'),
    };
  });
  await boot(page);
  await page.getByLabel('Minimize application').click();
  await page.getByLabel('Maximize application').click();
  await page.getByLabel('Close application').click();
  expect(await page.evaluate(() => (window as unknown as { nativeActions: string[] }).nativeActions)).toEqual(['minimize', 'maximize', 'close']);
});
