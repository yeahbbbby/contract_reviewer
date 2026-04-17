import { chromium, type BrowserContext, type Page } from 'playwright';
import path from 'node:path';
import fs from 'node:fs/promises';

const STORAGE_DIR = path.resolve(process.cwd(), 'storage');
const USER_DATA_DIR = path.join(STORAGE_DIR, 'chromium-profile');

let contextPromise: Promise<BrowserContext> | null = null;
let currentPagePromise: Promise<Page> | null = null;

async function ensureStorageDir() {
  await fs.mkdir(USER_DATA_DIR, { recursive: true });
}

export async function getContext(): Promise<BrowserContext> {
  if (!contextPromise) {
    contextPromise = (async () => {
      await ensureStorageDir();
      return chromium.launchPersistentContext(USER_DATA_DIR, {
        headless: false,
        viewport: { width: 1440, height: 1200 },
      });
    })();
  }

  const context = await contextPromise.catch(async () => {
    contextPromise = null;
    await ensureStorageDir();
    return chromium.launchPersistentContext(USER_DATA_DIR, {
      headless: false,
      viewport: { width: 1440, height: 1200 },
    });
  });

  if (context.isClosed()) {
    contextPromise = null;
    return getContext();
  }

  return context;
}

export async function getPage(): Promise<Page> {
  const context = await getContext();

  if (!currentPagePromise) {
    currentPagePromise = (async () => {
      const page = context.pages()[0] ?? (await context.newPage());
      await page.bringToFront();
      return page;
    })();
  }

  const page = await currentPagePromise;
  if (page.isClosed()) {
    currentPagePromise = null;
    return getPage();
  }

  return page;
}

export async function resetPage(): Promise<Page> {
  const context = await getContext();
  const page = await context.newPage();
  await page.bringToFront();
  currentPagePromise = Promise.resolve(page);
  return page;
}

export async function closeBrowser() {
  if (contextPromise) {
    const context = await contextPromise;
    await context.close();
    contextPromise = null;
    currentPagePromise = null;
  }
}
