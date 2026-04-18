import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { z } from 'zod';
import { getPage, resetPage, closeBrowser } from './browser.js';
import { writeDocxFile, writeRedlineDocxFile } from './docx.js';
import { prepareSourceDocx } from './source.js';

const server = new Server(
  {
    name: 'weko-playwright-mcp',
    version: '0.1.0',
  },
  {
    capabilities: {
      tools: {},
    },
  },
);

function textResult(content: string) {
  return {
    content: [{ type: 'text' as const, text: content }],
  };
}

type WekoSearchPlanInput = {
  question: string;
  region?: string;
  timeRange?: string;
  caseCause?: string;
  includeKeywords?: string[];
  excludeKeywords?: string[];
  excludePartyKeywords?: string[];
  resultTypes?: string[];
};

type WekoRegulationSearchPlanInput = WekoSearchPlanInput & {
  lawKeywords?: string[];
  articleFocus?: string[];
};

type WekoCaseSearchPlanInput = WekoSearchPlanInput & {
  disputeFocus?: string[];
};

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'weko_open_home',
      description: 'Open the Weko Xianxing home page in the persistent Playwright browser session.',
      inputSchema: {
        type: 'object',
        properties: {
          url: { type: 'string', default: 'https://www.wkinfo.com.cn/' },
        },
      },
    },
    {
      name: 'weko_wait_for_login',
      description: 'Wait for the user to finish logging in and confirm the page is loaded.',
      inputSchema: {
        type: 'object',
        properties: {
          expectedUrlPart: { type: 'string' },
          timeoutMs: { type: 'number', default: 180000 },
        },
      },
    },
    {
      name: 'weko_navigate',
      description: 'Navigate to a Weko page in the current browser session.',
      inputSchema: {
        type: 'object',
        properties: {
          url: { type: 'string' },
        },
        required: ['url'],
      },
    },
    {
      name: 'weko_open_common_tool',
      description: 'Open the product menu and choose the Weko common tool for either laws/regulations or judgments.',
      inputSchema: {
        type: 'object',
        properties: {
          toolName: { type: 'string', enum: ['法律法规', '裁判文书'] },
          query: { type: 'string' },
        },
        required: ['toolName'],
      },
    },
    {
      name: 'weko_export_docx',
      description: 'Write the provided content into a formatted .docx file in the workspace.',
      inputSchema: {
        type: 'object',
        properties: {
          filePath: { type: 'string' },
          title: { type: 'string' },
          bodyMarkdown: { type: 'string' },
        },
        required: ['filePath', 'title', 'bodyMarkdown'],
      },
    },
    {
      name: 'weko_export_redline_docx',
      description: 'Write a revision-mode .docx file with tracked insertions and deletions based on the original and revised content.',
      inputSchema: {
        type: 'object',
        properties: {
          filePath: { type: 'string' },
          title: { type: 'string' },
          originalBodyMarkdown: { type: 'string' },
          revisedBodyMarkdown: { type: 'string' },
        },
        required: ['filePath', 'title', 'originalBodyMarkdown', 'revisedBodyMarkdown'],
      },
    },
    {
      name: 'weko_prepare_source_docx',
      description: 'Extract text from a PDF or image and write a normalized Word docx that can be used as the review baseline.',
      inputSchema: {
        type: 'object',
        properties: {
          sourcePath: { type: 'string' },
          sourceKind: { type: 'string', enum: ['auto', 'pdf', 'image', 'text'], default: 'auto' },
          title: { type: 'string' },
          normalizedDocxPath: { type: 'string' },
        },
        required: ['sourcePath', 'title', 'normalizedDocxPath'],
      },
    },
    {
      name: 'weko_run_search',
      description: 'Run the current Weko search plan on the active module page using a keyword box or search controls.',
      inputSchema: {
        type: 'object',
        properties: {
          query: { type: 'string' },
          searchInputSelector: { type: 'string' },
          submitSelector: { type: 'string' },
        },
        required: ['query'],
      },
    },
    {
      name: 'weko_get_results',
      description: 'Extract visible result titles, links, metadata and page text from the current Weko results page.',
      inputSchema: {
        type: 'object',
        properties: {
          resultSelector: { type: 'string', default: 'a' },
          maxResults: { type: 'number', default: 20 },
        },
      },
    },
    {
      name: 'weko_open_result',
      description: 'Open one Weko search result from the current page by index.',
      inputSchema: {
        type: 'object',
        properties: {
          index: { type: 'number' },
          selector: { type: 'string', default: 'a' },
        },
        required: ['index'],
      },
    },
    {
      name: 'weko_snapshot',
      description: 'Return the current Weko page title, URL, and extracted body text.',
      inputSchema: {
        type: 'object',
        properties: {},
      },
    },
    {
      name: 'weko_screenshot',
      description: 'Capture a screenshot of the current Weko page for debugging.',
      inputSchema: {
        type: 'object',
        properties: {
          fullPage: { type: 'boolean', default: true },
        },
      },
    },
    {
      name: 'browser_reset_page',
      description: 'Open a fresh browser tab while preserving the login session.',
      inputSchema: {
        type: 'object',
        properties: {},
      },
    },
    {
      name: 'browser_close',
      description: 'Close the persistent browser context.',
      inputSchema: {
        type: 'object',
        properties: {},
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args = {} } = request.params;
  const page = await getPage();

  if (name === 'weko_open_home') {
    const input = z.object({ url: z.string().url().optional() }).parse(args);
    const url = input.url ?? 'https://www.wkinfo.com.cn/';
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    return textResult(`Opened ${url}\nTitle: ${await page.title()}`);
  }

  if (name === 'weko_navigate') {
    const input = z.object({ url: z.string().url() }).parse(args);
    await page.goto(input.url, { waitUntil: 'domcontentloaded' });
    return textResult(`Opened ${input.url}\nTitle: ${await page.title()}`);
  }

  if (name === 'weko_wait_for_login' || name === 'browser_wait_for_login') {
    const input = z.object({ expectedUrlPart: z.string().optional(), timeoutMs: z.number().optional() }).parse(args);
    const timeout = input.timeoutMs ?? 180000;
    await page.waitForLoadState('networkidle', { timeout }).catch(() => undefined);
    if (input.expectedUrlPart) {
      const expectedUrlPart = input.expectedUrlPart;
      await page.waitForURL((url) => url.toString().includes(expectedUrlPart), { timeout }).catch(() => undefined);
    }
    return textResult(`Current URL: ${page.url()}\nTitle: ${await page.title()}`);
  }

  if (name === 'weko_open_common_tool') {
    const input = z.object({ toolName: z.enum(['法律法规', '裁判文书']), query: z.string().optional() }).parse(args);

    const queryPart = input.query ? `tip=${encodeURIComponent(input.query)}` : 'tip=';

    if (input.toolName === '法律法规') {
      const legislationUrl = `https://law.wkinfo.com.cn/legislation/list?${queryPart}`;
      await page.goto(legislationUrl, { waitUntil: 'domcontentloaded' });
      return textResult(`Opened common tool: ${input.toolName}\nURL: ${page.url()}\nTitle: ${await page.title()}`);
    }

    if (input.toolName === '裁判文书') {
      const judgmentUrl = `https://law.wkinfo.com.cn/judgment-documents/list?${queryPart}`;
      await page.goto(judgmentUrl, { waitUntil: 'domcontentloaded' });
      return textResult(`Opened common tool: ${input.toolName}\nURL: ${page.url()}\nTitle: ${await page.title()}`);
    }

    const productMenu = page.getByText('产品菜单', { exact: true }).first();
    await productMenu.scrollIntoViewIfNeeded().catch(() => undefined);
    await productMenu.hover().catch(() => undefined);
    await productMenu.click({ force: true }).catch(() => undefined);
    await page.waitForTimeout(600);

    const commonTool = page.getByText('通用工具', { exact: true }).first();
    await commonTool.scrollIntoViewIfNeeded().catch(() => undefined);
    await commonTool.hover().catch(() => undefined);
    await commonTool.click({ force: true }).catch(() => undefined);
    await page.waitForTimeout(600);

    const targetTool = page.getByText(input.toolName, { exact: true }).first();
    await targetTool.scrollIntoViewIfNeeded().catch(() => undefined);
    await targetTool.hover().catch(() => undefined);
    await targetTool.click({ force: true }).catch(async () => {
      await page.locator(`text=${input.toolName}`).first().click({ force: true });
    });
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);
    return textResult(`Opened common tool: ${input.toolName}\nURL: ${page.url()}\nTitle: ${await page.title()}`);
  }

  if (name === 'weko_export_docx') {
    const input = z.object({
      filePath: z.string(),
      title: z.string(),
      bodyMarkdown: z.string(),
    }).parse(args);

    await writeDocxFile(input);
    return textResult(`DOCX written: ${input.filePath}`);
  }

  if (name === 'weko_export_redline_docx') {
    const input = z.object({
      filePath: z.string(),
      title: z.string(),
      originalBodyMarkdown: z.string(),
      revisedBodyMarkdown: z.string(),
    }).parse(args);

    await writeRedlineDocxFile(input);
    return textResult(`Redline DOCX written: ${input.filePath}`);
  }

  if (name === 'weko_prepare_source_docx') {
    const input = z.object({
      sourcePath: z.string(),
      sourceKind: z.enum(['auto', 'pdf', 'image', 'text']).optional(),
      title: z.string(),
      normalizedDocxPath: z.string(),
    }).parse(args);

    const result = await prepareSourceDocx(input);
    return textResult(JSON.stringify(result, null, 2));
  }

  // if (name === 'weko_run_search') {
  //   const input = z.object({
  //     query: z.string(),
  //     searchInputSelector: z.string().optional(),
  //     submitSelector: z.string().optional(),
  //   }).parse(args);

  //   const selectors = [input.searchInputSelector ?? 'input[type="search"]', 'input[placeholder*="检索"]', 'input[placeholder*="搜索"]', 'textarea', 'input'];
  //   let locator = null;
  //   for (const selector of selectors) {
  //     const candidate = page.locator(selector).first();
  //     if (await candidate.count().catch(() => 0)) {
  //       locator = candidate;
  //       break;
  //     }
  //   }
  //   if (!locator) {
  //     throw new Error('No search input found on current page.');
  //   }

  //   await locator.fill(input.query);
  //   if (input.submitSelector) {
  //     await page.locator(input.submitSelector).first().click();
  //   } else {
  //     await locator.press('Enter');
  //   }
  //   await page.waitForLoadState('networkidle').catch(() => undefined);
  //   return textResult(`Search submitted: ${input.query}\nURL: ${page.url()}\nTitle: ${await page.title()}`);
  // }
  if (name === 'weko_run_search') {
    const input = z.object({
      query: z.string(),
      searchInputSelector: z.string().optional(),
      submitSelector: z.string().optional(),
    }).parse(args);

    // v1.5.2 修复:先等页面静默,避免在加载中的页面上找搜索框
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => undefined);
    await page.waitForTimeout(1500);  // 给 SPA 组件渲染一点时间

    // 候选选择器(按优先级排序)—— 排除 checkbox/switch 这种明显不是搜索框的
    const tryFill = async (sel: string): Promise<any | null> => {
      const candidates = page.locator(sel);
      const n = await candidates.count().catch(() => 0);
      for (let i = 0; i < n; i++) {
        const el = candidates.nth(i);
        // 过滤:不能是 checkbox/radio/hidden,必须可见可编辑
        const type = await el.getAttribute('type').catch(() => null);
        if (type && ['checkbox', 'radio', 'hidden', 'submit', 'button'].includes(type)) continue;
        const role = await el.getAttribute('role').catch(() => null);
        if (role === 'switch') continue;
        const visible = await el.isVisible().catch(() => false);
        if (!visible) continue;
        const editable = await el.isEditable().catch(() => false);
        if (!editable) continue;
        return el;
      }
      return null;
    };

    const selectors = [
      input.searchInputSelector,
      'input[placeholder*="检索"]',
      'input[placeholder*="搜索"]',
      'input[placeholder*="关键词"]',
      'input[placeholder*="请输入"]',
      'input[placeholder*="输入"]',
      'input[type="search"]',
      'input[type="text"]',
      'textarea',
      'input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]):not([type="submit"]):not([type="button"])',
    ].filter(Boolean) as string[];

    let locator: any = null;
    let usedSelector = '';
    for (const selector of selectors) {
      const found = await tryFill(selector);
      if (found) {
        locator = found;
        usedSelector = selector;
        break;
      }
    }
    if (!locator) {
      const allInputs = await page.locator('input, textarea').count().catch(() => 0);
      throw new Error(`No suitable search input found on ${page.url()}.\nPage had ${allInputs} input/textarea elements but none were visible + editable + non-checkbox.`);
    }

    await locator.fill(input.query);
    if (input.submitSelector) {
      await page.locator(input.submitSelector).first().click();
    } else {
      await locator.press('Enter');
    }
    await page.waitForLoadState('networkidle').catch(() => undefined);
    return textResult(`Search submitted: ${input.query}\nURL: ${page.url()}\nTitle: ${await page.title()}\nUsed selector: ${usedSelector}`);
  }

  if (name === 'weko_get_results') {
    const input = z.object({ resultSelector: z.string().optional(), maxResults: z.number().optional() }).parse(args);
    const resultSelector = input.resultSelector ?? 'a';
    const maxResults = input.maxResults ?? 20;
    const items = await page.locator(resultSelector).evaluateAll((elements, limit) => {
      return elements.slice(0, limit).map((element, index) => {
        const anchor = element as HTMLAnchorElement;
        const text = (anchor.innerText || anchor.textContent || '').trim();
        const href = anchor.href || anchor.getAttribute('href') || '';
        return { index, text, href };
      }).filter((item) => item.text || item.href);
    }, maxResults);

    const bodyText = await page.locator('body').innerText().catch(() => '');
    return textResult(JSON.stringify({ url: page.url(), title: await page.title(), items, bodyText }, null, 2));
  }

  if (name === 'weko_open_result') {
    const input = z.object({ index: z.number(), selector: z.string().optional() }).parse(args);
    const selector = input.selector ?? 'a';
    const links = page.locator(selector);
    const count = await links.count();
    if (input.index < 0 || input.index >= count) {
      throw new Error(`Index ${input.index} out of range. Found ${count} elements.`);
    }
    const target = links.nth(input.index);
    await target.click();
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);
    return textResult(`Opened result at index ${input.index}\nURL: ${page.url()}\nTitle: ${await page.title()}`);
  }

  if (name === 'weko_snapshot') {
    const bodyText = await page.locator('body').innerText().catch(() => '');
    return textResult(JSON.stringify({ url: page.url(), title: await page.title(), bodyText }, null, 2));
  }

  if (name === 'weko_screenshot') {
    const input = z.object({ fullPage: z.boolean().optional() }).parse(args);
    const buffer = await page.screenshot({ fullPage: input.fullPage ?? true, type: 'png' });
    return {
      content: [
        {
          type: 'image',
          data: buffer.toString('base64'),
          mimeType: 'image/png',
        },
      ],
    };
  }

  if (name === 'browser_reset_page') {
    const freshPage = await resetPage();
    return textResult(`Created a fresh tab. URL: ${freshPage.url()}`);
  }

  if (name === 'browser_close') {
    await closeBrowser();
    return textResult('Browser context closed.');
  }

  throw new Error(`Unknown tool: ${name}`);
});

const transport = new StdioServerTransport();
await server.connect(transport);

process.on('SIGINT', async () => {
  await closeBrowser();
  process.exit(0);
});
