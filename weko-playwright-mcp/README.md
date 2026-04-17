# Weko Playwright MCP

A Weko Xianxing specific MCP server for legal research workflows with Playwright.

## What it provides

- Persistent Chromium session for manual login
- Open the Weko home page
- Open the Weko common tool from the product menu
- Build separate Weko search plans for laws/regulations and judgments
- Run searches from the current page
- Read result lists and page text
- Open a result and extract page text
- Capture screenshots for debugging

## Recommended workflow

1. Call `weko_open_home`.
2. Manually log in when prompted.
3. Call `weko_wait_for_login` if you want the server to wait for session completion.
4. Call `weko_open_common_tool` and choose `法律法规` or `裁判文书` from `产品菜单` -> `通用工具`.
5. Optionally pass a `query` to `weko_open_common_tool` so it opens the target page with `tip=` already filled.
6. Call `weko_build_regulation_search_plan` for law/regulation research or `weko_build_case_search_plan` for case research.
7. Copy the returned `copyableQuery` or `narrowQuery` into `weko_run_search` if you want to refine within the page.
8. Use `weko_get_results` to inspect the hit list.
9. Use `weko_open_result` on the most relevant item and iterate.

## Setup

```bash
npm install
npm run build
```

The first install will download Chromium through Playwright.

## Run in dev mode

```bash
npm run dev
```

## MCP client config example

```json
{
	"mcpServers": {
		"weko-playwright-mcp": {
			"command": "npm",
			"args": ["run", "dev"],
			"cwd": "d:/Desktop/code/weko-playwright-mcp"
		}
	}
}
```

Use your MCP client to point at this server, then open Weko, log in once, and reuse the same persistent Chromium session.

## Example MCP tools

- `weko_open_home`
- `weko_wait_for_login`
- `weko_navigate`
- `weko_open_common_tool`
- `weko_build_regulation_search_plan`
- `weko_build_case_search_plan`
- `weko_run_search`
- `weko_get_results`
- `weko_open_result`
- `weko_snapshot`
- `weko_screenshot`

## Notes

- The first login should be done manually.
- Session state is stored under `storage/`.
- Verify Weko's terms of use and your organization's compliance rules before automating access.
