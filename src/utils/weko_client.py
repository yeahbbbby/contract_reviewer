"""
威科先行MCP客户端
通过MCP协议调用威科先行法律检索服务
"""
import asyncio
import threading
from typing import Dict, List, Optional
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class WekoMCPClient:
    """威科先行MCP客户端"""

    def __init__(self, mcp_dir: str = None):
        """
        初始化威科先行MCP客户端

        Args:
            mcp_dir: weko-playwright-mcp目录路径
        """
        if mcp_dir is None:
            # 默认使用 contract_reviewer 目录下的 weko-playwright-mcp
            mcp_dir = Path(__file__).parent.parent.parent / "weko-playwright-mcp"

        self.mcp_dir = Path(mcp_dir)
        self.session = None
        self.exit_stack = None
        self.session_ready = False

        # 创建专用的事件循环和线程
        self.loop = None
        self.loop_thread = None

    def _start_loop(self):
        """在新线程中启动事件循环"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _run_async(self, coro):
        """在事件循环中运行协程"""
        if self.loop is None:
            # 启动事件循环线程
            self.loop_thread = threading.Thread(target=self._start_loop, daemon=True)
            self.loop_thread.start()
            # 等待循环启动
            import time
            time.sleep(0.5)

        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()

    async def _start_session_async(self):
        """异步启动MCP会话"""
        if self.session is not None:
            return

        # 配置MCP服务器参数 - 直接调用 node 避免 npm 的输出干扰
        server_params = StdioServerParameters(
            command="node",
            args=["dist/index.js"],
            cwd=str(self.mcp_dir)
        )

        # 创建stdio客户端
        from contextlib import AsyncExitStack
        self.exit_stack = AsyncExitStack()
        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )

        # 创建会话
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(stdio_transport[0], stdio_transport[1])
        )

        # 初始化会话
        await self.session.initialize()

    def start_session(self):
        """启动MCP会话（同步接口）"""
        self._run_async(self._start_session_async())

    async def _stop_session_async(self):
        """异步停止MCP会话"""
        if self.exit_stack:
            await self.exit_stack.aclose()
            self.exit_stack = None
            self.session = None
            self.session_ready = False

    def stop_session(self):
        """停止MCP会话（同步接口）"""
        if self.loop:
            self._run_async(self._stop_session_async())
            self.loop.call_soon_threadsafe(self.loop.stop)

    async def _call_tool_async(self, tool_name: str, args: Dict = None) -> Dict:
        """
        异步调用MCP工具

        Args:
            tool_name: 工具名称
            args: 工具参数

        Returns:
            工具返回结果
        """
        if not self.session:
            await self._start_session_async()

        result = await self.session.call_tool(tool_name, arguments=args or {})

        # 提取文本内容
        if result.content:
            for item in result.content:
                if hasattr(item, 'text'):
                    return {'text': item.text}

        return {}

    def _call_tool(self, tool_name: str, args: Dict = None) -> Dict:
        """调用MCP工具（同步接口）"""
        return self._run_async(self._call_tool_async(tool_name, args))

    # def open_home(self) -> str:
    #     """打开威科先行首页"""
    #     result = self._call_tool("weko_open_home")
    #     return result.get('text', '')
    def open_home(self, url: Optional[str] = None) -> str:
        """
        打开威科先行首页。

        Args:
            url: 可选。若传入,则打开该 URL(用于校园代理等场景)。
                 若不传,MCP 内部默认打开 https://www.wkinfo.com.cn/
        """
        args = {"url": url} if url else {}
        result = self._call_tool("weko_open_home", args)
        return result.get('text', '')

    def export_redline_docx(self, file_path: str, title: str,
                            original_markdown: str, revised_markdown: str) -> str:
        """
        导出带修订痕迹(tracked changes)的 .docx。

        调用原版在 weko-playwright-mcp 里实现好的 weko_export_redline_docx。
        输入原合同文本 + 修改后合同文本,输出的 .docx 里会有真实的 Word 修订痕迹。
        """
        result = self._call_tool("weko_export_redline_docx", {
            "filePath": file_path,
            "title": title,
            "originalBodyMarkdown": original_markdown,
            "revisedBodyMarkdown": revised_markdown,
        })
        return result.get('text', '')

    def wait_for_login(self, timeout_ms: int = 180000) -> str:
        """
        等待用户登录

        Args:
            timeout_ms: 超时时间（毫秒）

        Returns:
            登录状态信息
        """
        result = self._call_tool("weko_wait_for_login", {
            "timeoutMs": timeout_ms
        })
        self.session_ready = True
        return result.get('text', '')

    def search_regulations(self, query: str, region: str = "北京",
                          include_keywords: List[str] = None,
                          exclude_keywords: List[str] = None) -> Dict:
        """检索法律法规(v1.5.4:校园代理 + 按回车触发搜索)"""
        import os
        import time
        from urllib.parse import quote

        try:
            legislation_url = os.getenv('WEKO_LEGISLATION_URL')
            if legislation_url:
                sep = '&' if '?' in legislation_url else '?'
                target_url = f"{legislation_url}{sep}tip={quote(query)}"
                print(f"    导航到:{target_url}")
                self._call_tool("weko_navigate", {"url": target_url})
            else:
                self._call_tool("weko_open_common_tool", {
                    "toolName": "法律法规",
                    "query": query
                })

            # 等页面加载(代理 + SPA 渲染)
            time.sleep(3)

            # v1.5.4:?tip= 只预填,要触发真正搜索需要按回车(或点搜索按钮)
            # weko_run_search 会找到搜索框 → fill → press Enter
            try:
                self._call_tool("weko_run_search", {"query": query})
                time.sleep(2)  # 等搜索结果返回
            except Exception as e:
                print(f"    run_search 失败(可能页面未就绪):{e}")

            plan_text = ""

            results = self._call_tool("weko_get_results", {"maxResults": 20})

            return {
                "plan": plan_text,
                "results": results.get('text', '')
            }
        except Exception as e:
            print(f"    法规检索失败: {e}")
            return {"plan": "", "results": ""}
            return {"plan": "", "results": ""}

    def search_cases(self, query: str, region: str = "北京",
                    time_range: str = "近三年",
                    dispute_focus: List[str] = None,
                    include_keywords: List[str] = None,
                    exclude_keywords: List[str] = None) -> Dict:
        """检索裁判文书(v1.5.4)"""
        import os
        import time
        from urllib.parse import quote

        try:
            judgment_url = os.getenv('WEKO_JUDGMENT_URL')
            if judgment_url:
                sep = '&' if '?' in judgment_url else '?'
                target_url = f"{judgment_url}{sep}tip={quote(query)}"
                print(f"    导航到:{target_url}")
                self._call_tool("weko_navigate", {"url": target_url})
            else:
                self._call_tool("weko_open_common_tool", {
                    "toolName": "裁判文书",
                    "query": query
                })

            time.sleep(3)

            try:
                self._call_tool("weko_run_search", {"query": query})
                time.sleep(2)
            except Exception as e:
                print(f"    run_search 失败(可能页面未就绪):{e}")

            plan_text = ""

            results = self._call_tool("weko_get_results", {"maxResults": 20})

            return {
                "plan": plan_text,
                "results": results.get('text', '')
            }
        except Exception as e:
            print(f"    案例检索失败: {e}")
            return {"plan": "", "results": ""}
        
    def _trigger_search_button(self):
        """
        v1.5.4:威科的 ?tip= 只预填搜索框不触发搜索,
        需要额外点"搜索"按钮。尝试几种常见的 selector,哪个命中就用哪个。
        """
        # 从截图看,"搜索"按钮上既有放大镜图标也有"搜索"两个字,
        # 所以按文本匹配最稳定
        selectors = [
            'button:has-text("搜索")',          # 带"搜索"字样的 button
            'span.el-button:has-text("搜索")',  # Element UI 风格
            '[class*="search"] button',          # class 含 search
            'button[type="submit"]',             # 提交按钮
        ]
        for sel in selectors:
            try:
                self._call_tool("weko_click", {"selector": sel})
                print(f"    已点击搜索按钮(selector={sel})")
                return
            except Exception:
                continue
        print("    ⚠ 没找到搜索按钮,可能页面结构变了")

    def open_result(self, index: int) -> str:
        """
        打开指定索引的检索结果

        Args:
            index: 结果索引

        Returns:
            结果详情
        """
        self._call_tool("weko_open_result", {"index": index})

        # 获取页面快照
        snapshot = self._call_tool("weko_snapshot")
        return snapshot.get('text', '')

    def search_rental_regulations(self, region: str = "北京") -> Dict:
        """
        检索租赁相关法规（固定两轮检索）

        Args:
            region: 地区

        Returns:
            检索结果汇总
        """
        results = {
            "round1": None,
            "round2": None
        }

        # 第一轮：租赁合同
        print("  第一轮检索: 租赁合同")
        results["round1"] = self.search_regulations(
            query="租赁合同",
            region=region,
            include_keywords=["租赁", "合同"]
        )

        # 第二轮：转租
        print("  第二轮检索: 转租")
        results["round2"] = self.search_regulations(
            query="转租",
            region=region,
            include_keywords=["转租"]
        )

        return results

    def search_sublease_cases(self, region: str = "北京") -> Dict:
        """
        检索转租相关案例（按争议点分组）

        Args:
            region: 地区

        Returns:
            按争议点分组的案例
        """
        dispute_points = [
            "同意转租",
            "押金返还",
            "维修责任",
            "提前解约",
            "腾退占用费"
        ]

        results = {}
        for dispute in dispute_points:
            print(f"  检索争议点: {dispute}")
            results[dispute] = self.search_cases(
                query=f"房屋转租 {dispute}",
                region=region,
                dispute_focus=[dispute],
                include_keywords=["转租", dispute],
                exclude_keywords=["公司", "企业", "商业"]
            )

        return results

    def __enter__(self):
        """上下文管理器入口"""
        self.start_session()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.stop_session()
