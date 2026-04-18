"""
威科先行MCP客户端(v1.6.2 — 关联每条 item 的命中摘要)
通过MCP协议调用威科先行法律检索服务
"""
import asyncio
import os
import threading
from typing import Dict, List, Optional
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class WekoMCPClient:
    """威科先行MCP客户端"""

    def __init__(self, mcp_dir: str = None):
        if mcp_dir is None:
            mcp_dir = Path(__file__).parent.parent.parent / "weko-playwright-mcp"

        self.mcp_dir = Path(mcp_dir)
        self.session = None
        self.exit_stack = None
        self.session_ready = False

        self.loop = None
        self.loop_thread = None

    def _start_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _run_async(self, coro):
        if self.loop is None:
            self.loop_thread = threading.Thread(target=self._start_loop, daemon=True)
            self.loop_thread.start()
            import time
            time.sleep(0.5)

        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()

    async def _start_session_async(self):
        if self.session is not None:
            return

        server_params = StdioServerParameters(
            command="node",
            args=["dist/index.js"],
            cwd=str(self.mcp_dir)
        )

        from contextlib import AsyncExitStack
        self.exit_stack = AsyncExitStack()
        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )

        self.session = await self.exit_stack.enter_async_context(
            ClientSession(stdio_transport[0], stdio_transport[1])
        )

        await self.session.initialize()

    def start_session(self):
        self._run_async(self._start_session_async())

    async def _stop_session_async(self):
        if self.exit_stack:
            await self.exit_stack.aclose()
            self.exit_stack = None
            self.session = None
            self.session_ready = False

    def stop_session(self):
        """
        停止 MCP 会话(容错关闭)
        """
        if self.loop:
            try:
                self._run_async(self._stop_session_async())
            except RuntimeError as e:
                if "cancel scope" in str(e):
                    print("  (MCP 清理遇到 cancel scope 警告,已忽略,不影响结果)")
                else:
                    raise
            except Exception as e:
                print(f"  (MCP 清理异常:{e},已忽略)")

            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except Exception:
                pass

    async def _call_tool_async(self, tool_name: str, args: Dict = None) -> Dict:
        if not self.session:
            await self._start_session_async()

        result = await self.session.call_tool(tool_name, arguments=args or {})

        if result.content:
            for item in result.content:
                if hasattr(item, 'text'):
                    return {'text': item.text}

        return {}

    def _call_tool(self, tool_name: str, args: Dict = None) -> Dict:
        return self._run_async(self._call_tool_async(tool_name, args))

    def open_home(self, url: Optional[str] = None) -> str:
        args = {"url": url} if url else {}
        result = self._call_tool("weko_open_home", args)
        return result.get('text', '')

    def export_redline_docx(self, file_path: str, title: str,
                            original_markdown: str, revised_markdown: str) -> str:
        result = self._call_tool("weko_export_redline_docx", {
            "filePath": file_path,
            "title": title,
            "originalBodyMarkdown": original_markdown,
            "revisedBodyMarkdown": revised_markdown,
        })
        return result.get('text', '')

    def wait_for_login(self, timeout_ms: int = 180000) -> str:
        result = self._call_tool("weko_wait_for_login", {
            "timeoutMs": timeout_ms
        })
        self.session_ready = True
        return result.get('text', '')

    # ================================================================
    # 检索 — 法规
    # ================================================================

    def search_regulations(self, query: str, region: str = "北京",
                          include_keywords: List[str] = None,
                          exclude_keywords: List[str] = None) -> Dict:
        """检索法律法规(v1.6:校园代理 + 解析 + 落盘)"""
        import time
        from urllib.parse import quote

        try:
            legislation_url = os.getenv('WEKO_LEGISLATION_URL')
            if legislation_url:
                sep = '&' if '?' in legislation_url else '?'
                target_url = f"{legislation_url}{sep}tip={quote(query)}"
                print(f"    [nav] {target_url}")
                self._call_tool("weko_navigate", {"url": target_url})
            else:
                self._call_tool("weko_open_common_tool", {
                    "toolName": "法律法规",
                    "query": query
                })

            time.sleep(3)

            try:
                rs = self._call_tool("weko_run_search", {"query": query})
                print(f"    [run_search] {rs.get('text', '')[:150]}")
                time.sleep(3)
            except Exception as e:
                print(f"    [run_search] ⚠ 失败:{e}")

            results = self._call_tool("weko_get_results", {"maxResults": 20})
            results_text = results.get('text', '')

            quality = self._assess_search_quality(results_text, query)
            print(f"    [quality] {quality['verdict']} - {quality['reason']} "
                  f"(文本 {len(results_text)} 字符)")

            parsed = self._parse_weko_results(results_text, kind="legislation")

            self._dump_debug(
                kind="legislation",
                query=query,
                raw_text=results_text,
                parsed=parsed,
                quality=quality,
            )

            items_with_snippet = sum(1 for it in parsed['items'] if it.get('snippet'))
            print(f"    [parsed] items={parsed['items_count']}, "
                  f"有摘要={items_with_snippet}, "
                  f"案号={len(parsed.get('case_numbers', []))}, "
                  f"条文={len(parsed.get('article_refs', []))}")

            if quality['verdict'] == 'empty':
                return {
                    "plan": "",
                    "results": "(检索未返回有效结果,LLM 不应引用任何具体法条或案例)",
                    "_quality": quality,
                    "_parsed": parsed,
                    "_raw": results_text,
                }

            return {
                "plan": "",
                "results": results_text,
                "_quality": quality,
                "_parsed": parsed,
                "_raw": results_text,
            }
        except Exception as e:
            print(f"    [error] 法规检索失败: {e}")
            return {"plan": "", "results": "(检索失败)"}

    # ================================================================
    # 检索 — 案例
    # ================================================================

    def search_cases(self, query: str, region: str = "北京",
                    time_range: str = "近三年",
                    dispute_focus: List[str] = None,
                    include_keywords: List[str] = None,
                    exclude_keywords: List[str] = None) -> Dict:
        """
        检索裁判文书(v1.6.2:主动 fill + 点搜索 + 失败重试)
        """
        import time
        from urllib.parse import quote

        try:
            judgment_url = os.getenv('WEKO_JUDGMENT_URL')
            if judgment_url:
                base_url = judgment_url.split('?')[0]
                print(f"    [nav] {base_url}")
                self._call_tool("weko_navigate", {"url": base_url})
            else:
                self._call_tool("weko_open_common_tool", {
                    "toolName": "裁判文书",
                    "query": query
                })

            # 给 SPA 充分加载时间
            time.sleep(7)

            # 触发搜索(第 1 次)
            rs_ok = False
            try:
                rs = self._call_tool("weko_run_search", {"query": query})
                print(f"    [run_search] {rs.get('text', '')[:150]}")
                rs_ok = True
                time.sleep(5)
            except Exception as e:
                print(f"    [run_search] ⚠ 第 1 次失败:{e}")

            # 失败重试一次
            if not rs_ok:
                print(f"    [retry] 重新 navigate 并再试一次...")
                try:
                    base_url = (os.getenv('WEKO_JUDGMENT_URL') or '').split('?')[0]
                    if base_url:
                        self._call_tool("weko_navigate", {"url": base_url})
                    time.sleep(8)
                    rs = self._call_tool("weko_run_search", {"query": query})
                    print(f"    [run_search retry] {rs.get('text', '')[:150]}")
                    time.sleep(5)
                except Exception as e:
                    print(f"    [run_search] ⚠ 重试也失败:{e}")

            results = self._call_tool("weko_get_results", {"maxResults": 20})
            results_text = results.get('text', '')

            quality = self._assess_search_quality(results_text, query)
            print(f"    [quality] {quality['verdict']} - {quality['reason']} "
                  f"(文本 {len(results_text)} 字符)")

            parsed = self._parse_weko_results(results_text, kind="cases")

            self._dump_debug(
                kind="cases",
                query=query,
                raw_text=results_text,
                parsed=parsed,
                quality=quality,
            )

            items_with_snippet = sum(1 for it in parsed['items'] if it.get('snippet'))
            print(f"    [parsed] items={parsed['items_count']}, "
                  f"有摘要={items_with_snippet}, "
                  f"案号={len(parsed.get('case_numbers', []))}")

            if quality['verdict'] == 'empty':
                return {
                    "plan": "",
                    "results": "(检索未返回有效结果,LLM 不应引用任何具体案号)",
                    "_quality": quality,
                    "_parsed": parsed,
                    "_raw": results_text,
                }

            return {
                "plan": "",
                "results": results_text,
                "_quality": quality,
                "_parsed": parsed,
                "_raw": results_text,
            }
        except Exception as e:
            print(f"    [error] 案例检索失败: {e}")
            return {"plan": "", "results": "(检索失败)"}

    # ================================================================
    # 辅助方法
    # ================================================================

    def _assess_search_quality(self, results_text: str, query: str) -> Dict:
        """判断威科返回的文本是不是真的搜到了东西"""
        t = (results_text or "").strip()

        if len(t) < 300:
            return {"verdict": "empty", "reason": f"返回过短({len(t)}字符)"}

        login_markers = [
            "需要登录", "抱歉,此功能需要登录", "请先登录",
            "登录后操作", "el-dialog__header",
        ]
        for marker in login_markers:
            if marker in t:
                return {"verdict": "empty", "reason": f"检测到未登录标志:{marker}"}

        empty_markers = [
            "搜索结果为空", "未找到相关", "没有找到",
            "暂无数据", "暂无结果", "no result",
        ]
        for marker in empty_markers:
            if marker in t:
                return {"verdict": "empty", "reason": f"检测到空结果标志:{marker}"}

        homepage_markers = ["3,466,648", "伦理安全指引"]
        homepage_hits = sum(1 for m in homepage_markers if m in t)
        if homepage_hits >= 1 and "检索条件" not in t:
            return {"verdict": "empty", "reason": "页面看起来是首页推荐,未执行搜索"}

        if "检索条件" in t and ("关键词" in t or query[:4] in t):
            return {"verdict": "ok", "reason": "检测到检索条件回显"}

        import re
        if re.search(r"第\s*\d+\s*条", t):
            return {"verdict": "ok", "reason": "文本含具体法条号"}

        if re.search(r"[((]\s*(19|20)\d{2}\s*[))]\s*[^\s]{1,10}?\s*[^\s]{1,4}[初终再]\s*\d+\s*号", t):
            return {"verdict": "ok", "reason": "文本含真实案号格式"}

        return {"verdict": "suspicious", "reason": "有内容但无法确认是否真的搜到"}

    def _parse_weko_results(self, raw_text: str, kind: str = "legislation") -> Dict:
        """
        v1.6.2: 从威科 get_results JSON 文本中提取结构化列表,
                并为每条 item 关联"命中摘要"(威科列表页已渲染的裁判观点片段)。

        威科列表项在 bodyText 里的格式:
            "<序号><标题>\n[判决书/裁定书]\n<法院>\n<案号>\n<日期> 裁判\n
            命中频次...\n命中片段\n共X处\n...\n查看详情→\n
            <真实摘要文本 — 通常 150-300 字>\n
            <下一个序号><下一个标题>..."

        关键分隔符:"查看详情→" 之后、下一个序号之前 = 本条 item 的命中摘要。
        """
        import json
        import re

        parsed = {
            "page_title": "",
            "page_url": "",
            "items_count": 0,
            "items": [],            # [{title, publisher, date, case_number, snippet, kind}]
            "law_articles": [],
            "case_numbers": [],
            "article_refs": [],     # 条款原文引用
            "body_snippet": "",
            "total_count": None,
        }

        if not raw_text or not raw_text.strip():
            return parsed

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            parsed["body_snippet"] = raw_text[:2000]
            return parsed

        parsed["page_title"] = data.get("title", "")
        parsed["page_url"] = data.get("url", "")
        body = data.get("bodyText", "") or ""
        parsed["body_snippet"] = body[:2000]

        # ---- 检索结果总数 ----
        m_total = re.search(
            r"(?:法律法规|裁判文书|行政监管|专业解读)\s*([\d,]+|99\+)", body
        )
        if m_total:
            parsed["total_count"] = m_total.group(1)

        # ---- 切分 bodyText 为条目块 ----
        # 策略:按"行首 1-2 位数字 + 非数字字符"作为条目起点
        lines = body.split("\n")
        item_start_pat = re.compile(r"^(\d{1,2})(?=\D)")

        blocks = []          # 每个 block 是 List[str],是属于一条 item 的所有行
        current_block = []

        def push_block():
            if current_block and len(current_block[0]) > 8:
                blocks.append(list(current_block))

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            m = item_start_pat.match(line_stripped)
            if m and len(line_stripped) > 6:
                # 新 item 开始
                push_block()
                title = line_stripped[len(m.group(1)):].strip()
                if len(title) > 5:
                    current_block = [title]
                else:
                    current_block = []
            else:
                if current_block:
                    current_block.append(line_stripped)
        push_block()

        # ---- 过滤:噪音条目(导航、筛选面板) ----
        noise_exact = {
            "法律法规", "裁判文书", "行政监管", "专业解读", "法规图谱",
            "查阅热度", "知道了", "不再提示", "EN", "中英对照", "法规对比",
            "返回顶部", "查看更多", "全选",
        }
        noise_contains = ["命中频次", "点击关键词", "法条要点"]

        # ---- 案号正则(给每条 item 尝试抽) ----
        case_num_pat = re.compile(
            r"[((]\s*(?:19|20)\d{2}\s*[))]\s*[^\s,。;]{1,15}?\s*[^\s,。;]{1,5}[初终再]\s*\d+\s*号"
        )

        for block in blocks[:40]:
            title = block[0]
            if title in noise_exact or any(n in title for n in noise_contains):
                continue
            if len(title) < 8:
                continue

            # 从 block 里收集元数据 + 摘要
            publisher = ""
            date = ""
            case_number = ""
            doc_type = ""  # 判决书 / 裁定书
            snippet = ""

            # 状态:是否已经越过 "查看详情→"(之后的行就是命中摘要)
            past_detail_marker = False
            snippet_lines = []

            for sub in block[1:]:
                if sub in noise_exact or any(n in sub for n in noise_contains):
                    continue

                # 识别"查看详情→" — 后面的行开始是真正的摘要
                if "查看详情" in sub:
                    past_detail_marker = True
                    continue

                if past_detail_marker:
                    # 摘要段落。注意避免把下一个 block 的起始数字误收
                    if len(sub) > 20:
                        snippet_lines.append(sub)
                        # 收 1-2 段就够了,再多可能是杂质
                        if len(" ".join(snippet_lines)) > 400:
                            break
                    continue

                # "查看详情→"之前的元数据区
                # 文书类型
                if sub in ("判决书", "裁定书", "调解书", "决定书", "执行裁定书"):
                    doc_type = sub
                    continue
                # 日期
                if re.match(r"^\d{4}\.\d{1,2}\.\d{1,2}", sub):
                    date = sub
                    continue
                # 案号(通常单独一行)
                m_cn = case_num_pat.search(sub)
                if m_cn and len(sub) < 60:
                    case_number = m_cn.group(0).strip()
                    continue
                # 法院 / 发文机关
                if any(kw in sub for kw in ["法院", "部", "局", "委员会", "政府", "协会"]) \
                        and len(sub) < 60:
                    publisher = sub
                    continue

            snippet = " ".join(snippet_lines)[:400]

            # 若摘要为空但 block 里有长行,退化方案:取最长的那行作为 snippet
            if not snippet:
                long_lines = [
                    s for s in block[1:]
                    if len(s) > 30
                    and s not in noise_exact
                    and not any(n in s for n in noise_contains)
                    and "命中" not in s
                    and s != doc_type
                ]
                if long_lines:
                    snippet = max(long_lines, key=len)[:400]

            item = {
                "title": title[:200],
                "publisher": publisher,
                "date": date,
                "case_number": case_number,
                "doc_type": doc_type,
                "snippet": snippet,
                "kind": kind,
            }
            parsed["items"].append(item)

        parsed["items_count"] = len(parsed["items"])

        # ---- 全局案号(从 bodyText)----
        case_numbers = list(dict.fromkeys(
            m.group(0).strip() for m in case_num_pat.finditer(body)
        ))
        parsed["case_numbers"] = case_numbers[:20]

        # ---- 法条号(数字格式)----
        law_pat = re.compile(r"《[^》]{2,30}》第\s*\d{1,4}\s*条")
        parsed["law_articles"] = list(dict.fromkeys(law_pat.findall(body)))[:30]

        # ---- 条款原文引用(中文数字或阿拉伯数字)----
        article_ref_pat = re.compile(
            r"第([一二三四五六七八九十百千]+|\d+)条\s+([^\n]{10,300})"
        )
        article_refs = []
        for m in article_ref_pat.finditer(body):
            article_refs.append({
                "article": f"第{m.group(1)}条",
                "text": m.group(2).strip()[:300],
            })
        parsed["article_refs"] = article_refs[:15]

        return parsed

    def _dump_debug(self, kind: str, query: str, raw_text: str,
                    parsed: Dict, quality: Dict) -> None:
        """
        把本次检索的原始返回、解析结果、质量判断全部落盘
        """
        import json
        import re

        output_dir = Path(os.getcwd()) / "output" / "weko_debug"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"    [dump] 创建目录失败:{e}")
            return

        safe_q = re.sub(r'[\\/:*?"<>|]', '_', query)[:50]
        prefix = f"{kind}_{safe_q}"

        try:
            (output_dir / f"{prefix}.txt").write_text(raw_text or "", encoding="utf-8")
        except Exception as e:
            print(f"    [dump] 写 raw 失败:{e}")

        try:
            report = {
                "query": query,
                "quality": quality,
                "parsed": parsed,
            }
            (output_dir / f"{prefix}.parsed.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"    [dump] 写 parsed 失败:{e}")

    # ================================================================
    # 既有方法(保留不变)
    # ================================================================

    def open_result(self, index: int) -> str:
        self._call_tool("weko_open_result", {"index": index})
        snapshot = self._call_tool("weko_snapshot")
        return snapshot.get('text', '')

    def search_rental_regulations(self, region: str = "北京") -> Dict:
        results = {"round1": None, "round2": None}

        print("  第一轮检索: 租赁合同")
        results["round1"] = self.search_regulations(
            query="租赁合同",
            region=region,
            include_keywords=["租赁", "合同"]
        )

        print("  第二轮检索: 转租")
        results["round2"] = self.search_regulations(
            query="转租",
            region=region,
            include_keywords=["转租"]
        )

        return results

    def search_sublease_cases(self, region: str = "北京") -> Dict:
        dispute_points = [
            "同意转租", "押金返还", "维修责任", "提前解约", "腾退占用费"
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
        self.start_session()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_session()