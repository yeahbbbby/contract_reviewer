"""
Agent② 合规审查 v1.7
基于本地规范库(含核心法条预打包) + 威科先行进行合规性审查

v1.7 改动:
1. 新增"核心法条"主动预加载 —— 调 regulation_loader.get_core_articles_for_sublease()
2. _build_prompt 去掉 200 字截断,法条完整原文呈现
3. system_prompt 加"硬性事实性约束" —— 钉死管辖=民诉法34条、LPR 不写数字、规章号不得凭记忆、押金分两维
4. _collect_regulations 加"管辖"主题检索(修复之前 0 命中的问题)
"""
from typing import Dict, List
from ..utils.llm_client import get_llm_client, LLMClient


class Agent02Compliance:
    """合规审查Agent"""

    def __init__(self, llm_client: LLMClient = None):
        self.llm_client = llm_client or get_llm_client()

    def review(self, clauses: Dict, regulation_loader, weko_client) -> Dict:
        """
        进行合规审查

        Args:
            clauses: 提取的条款
            regulation_loader: 本地规范库加载器(v1.7 要求支持 get_core_articles_for_sublease)
            weko_client: 威科先行MCP客户端

        Returns:
            审查报告
        """
        # 收集相关法规
        regulations = self._collect_regulations(clauses, regulation_loader, weko_client)

        # 构建审查提示词
        prompt = self._build_prompt(clauses, regulations)

        # 调用LLM
        review_text = self.llm_client.analyze(
            prompt=prompt,
            system_prompt=self._get_system_prompt(),
            max_tokens=8192
        )

        return {
            'agent': 'Agent02_Compliance',
            'review': review_text,
            'regulations_used': regulations,
            'issues': self._extract_issues(review_text),
            'compliance_score': self._calculate_score(review_text)
        }

    # ========================================================
    # system_prompt —— v1.7 加硬性事实性约束
    # ========================================================
    def _get_system_prompt(self) -> str:
        return """你是一位专业的房屋租赁合同合规审查专家,专门为二房东(转租方)提供合规性审查。

你的审查框架采用"三观四步法":

【三观】
1. 宏观:交易可行性、主体资格、标的合法性
2. 中观:合同形式、格式条款、示范文本符合度
3. 微观:具体条款的合规性

【四步法】
1. 识别条款类型和性质
2. 匹配适用法律规范
3. 判断合规性和效力
4. 提出修改建议

重点审查内容:
- 转租合法性(是否有原房东书面同意)
- 租期合规性(不得超过原租期)
- 租金条款(支付方式、调整机制)
- 押金条款(金额限制、退还条件、传递机制)
- 违约责任(是否对等、是否过高)
- 解除条件(是否合理、是否单方)
- 格式条款(是否存在不公平条款)
- 争议解决(管辖约定是否符合专属管辖规定)

请以二房东的立场,识别:
- 效力风险(可能导致合同无效的条款)
- 履约风险(可能导致违约的条款)
- 清退风险(影响清退次承租人的条款)
- 证据风险(举证责任不利的条款)

================================================================
【硬性事实性约束 —— 以下错误必须避免】
================================================================

① 管辖条款的法条引用(错误率最高,重点强调)
   - 房屋租赁合同纠纷属【不动产纠纷专属管辖】
   - 法律依据:《民事诉讼法》第34条(不动产专属管辖) + 最高法司法解释第28条(房租按不动产确定管辖)
   - ❌ 禁止:引用《民事诉讼法》第24条作为管辖依据 —— 第24条不是管辖条款
   - ❌ 禁止:将"约定房屋所在地法院管辖"描述为"协议管辖" —— 因为不动产专属管辖不允许协议变更,
        即使约定与法定一致,法律路径也是"法定专属管辖",不是"有效的协议选择"
   - ✅ 正确表述模板:
     "合同约定争议由房屋所在地法院管辖,与《民事诉讼法》第34条 +《最高人民法院关于适用
      〈中华人民共和国民事诉讼法〉的解释》第28条规定的'房屋租赁合同纠纷按不动产纠纷确定管辖'
      相一致,属专属管辖情形,条款有效。"

② LPR 利率数字
   - ❌ 禁止:写出具体的年化百分比(如"LPR 四倍约 14.8%""年化 18.25%")
   - 原因:LPR 每月浮动,写死必过时;且 LPR 四倍并非严格的违约金上限,只是司法参考
   - ✅ 正确表述:
     - 只提"LPR 四倍"本身,不换算具体数字
     - 如需说明畸高,可写:"日 3% 滞纳金年化超千倍,显著超过司法实践中违约金调整的通行参考上限"
     - 调减建议使用定性语言:"应调整为司法实践通行参考水平",而非给出具体百分比

③ 规章号 / 示范文本号 / 案号引用
   - ❌ 禁止:凭记忆写出具体发文号(如"京建发〔2021〕37号")
   - ✅ 只能引用【本提示词中出现的】规章号
   - 如需提及"北京市住房租赁示范合同",只说名称本身,不添加具体发文号

④ 押金条款的评价维度
   - 必须分两维,不得混为一谈:
     (A) 金额合规性:押金金额是否 ≤ 法定上限
         - 住房租赁企业:一般不超过 1 个月租金(《北京市住房租赁条例》)
         - 自然人出租:一般不超过 3 个月租金
         - 本案 8000 元 = 1 月租金,金额合规 ✅
     (B) 传递机制:二房东对原房东的押金是否形成"乙方押金→二房东→原房东"的闭环
         - 本案未约定传递机制 → 敞口风险 🟠
   - ❌ 禁止:同一押金条款既标"合规"又标"高危" —— 两维必须分别标注

⑤ 所有案号与案例引用
   - ❌ 禁止:引用未在【威科检索结果】中出现的具体案号
   - 如需引用裁判规则,说"司法实践中……"的概括性表述即可

================================================================
【输出格式】
================================================================
【宏观审查】
【中观审查】
【微观审查】
【合规问题清单】
【法条依据】(必须只引用本提示词【核心法条】和【威科检索】中的内容,禁止凭记忆扩充)
【修改建议】
"""

    # ========================================================
    # 法规收集:本地主题检索 + ⭐ 核心法条预打包 + 威科
    # ========================================================
    def _collect_regulations(self, clauses: Dict, regulation_loader, weko_client) -> Dict:
        """收集相关法规(v1.7 加核心法条预打包)"""
        regulations = {
            'local_topics': [],      # 按主题检索的本地法条(面广)
            'core_articles': {},     # ⭐ 按争议点预打包的核心法条(精准)
            'weko_regulations': {},
            'weko_cases': {},
        }

        # 1) 本地按主题检索 —— v1.7 加"管辖"主题(修复之前 0 命中)
        print("  本地规范库主题检索...")
        topics = ['转租', '租金', '押金', '违约', '解除', '管辖', '维修']
        for topic in topics:
            try:
                results = regulation_loader.search_by_topic(topic)
                regulations['local_topics'].extend(results[:3])  # 每主题前 3
            except Exception as e:
                print(f"    主题 {topic} 检索失败: {e}")

        # 2) ⭐ 本地核心法条预打包(v1.7 核心新增)
        #    这一步把转租合同必然涉及的法条提前查出来,喂给 LLM 完整原文
        #    LLM 就不必凭记忆重构,避免法条引用错误
        try:
            print("  本地核心法条预打包...")
            core = regulation_loader.get_core_articles_for_sublease()
            regulations['core_articles'] = core
            total = sum(len(v) for v in core.values())
            print(f"    已打包 {len(core)} 个主题,共 {total} 条核心法条")
        except Exception as e:
            print(f"    核心法条打包失败: {e}(可能是 regulation_loader 版本过旧)")

        # 3) 从威科先行检索法规(固定两轮)
        try:
            print("  威科先行法规检索...")
            weko_regs = weko_client.search_rental_regulations(region="北京")
            regulations['weko_regulations'] = weko_regs
        except Exception as e:
            print(f"  威科先行法规检索失败: {e}")
            print("  继续使用本地规范库...")

        # 4) 从威科先行检索案例(按争议点)
        try:
            print("  威科先行案例检索...")
            weko_cases = weko_client.search_sublease_cases(region="北京")
            regulations['weko_cases'] = weko_cases
        except Exception as e:
            print(f"  威科先行案例检索失败: {e}")
            print("  继续使用本地规范库...")

        return regulations

    # ========================================================
    # Prompt 构建:⭐ 核心法条完整原文 + 本地主题摘要 + 威科结构化
    # ========================================================
    def _build_prompt(self, clauses: Dict, regulations: Dict) -> str:
        """构建审查提示词(v1.7 去 200 字截断,核心法条完整呈现)"""
        parts = []

        parts.append("请对以下转租合同进行合规审查:\n")

        # ---- 合同条款 ----
        parts.append("【合同条款】")
        for category, clause_data in clauses.get('clauses', {}).items():
            if category == '所有条款':
                continue
            if clause_data.get('found'):
                parts.append(f"\n{category}:")
                for section in clause_data.get('sections', []):
                    parts.append(f"  {section.get('title', '')}")
                    parts.append(f"  {section.get('content', '')}")

        # ---- ⭐ 核心法条(完整原文,按争议点组织) ----
        core_articles = regulations.get('core_articles', {})
        if core_articles:
            parts.append("\n\n================================================================")
            parts.append("【核心适用法条 —— 已为你检索好,请直接引用,不得凭记忆重构】")
            parts.append("================================================================")
            parts.append("以下法条已通过本地权威规范库精准定位,均为【完整原文】。")
            parts.append("你在出具合规意见时,引用法条【必须】来自本节,禁止凭记忆引用未在此列出的条款编号。\n")

            for topic, items in core_articles.items():
                if not items:
                    continue
                parts.append(f"\n━━━ {topic} ━━━")
                for it in items:
                    law = it.get('law_name', '')
                    art_cn = it.get('article_number_cn', '')
                    content = it.get('content', '')
                    source = it.get('source', '')
                    note = it.get('note', '')
                    source_tag = "[本地规范库]" if source == 'local_kb' else "[核心法律事实]"
                    parts.append(f"\n• 《{law}》{art_cn} {source_tag}")
                    parts.append(f"  {content}")
                    if note:
                        parts.append(f"  ⚠️ 适用提示:{note}")

        # ---- 本地主题检索(补充面上的参考) ----
        local_topics = regulations.get('local_topics', [])
        if local_topics:
            parts.append("\n\n================================================================")
            parts.append("【本地规范库主题检索(补充参考)】")
            parts.append("================================================================")
            # 按法律名分组去重后呈现
            seen = set()
            for reg in local_topics[:20]:
                law = reg.get('law_name', '')
                art = reg.get('article', '')
                content = reg.get('content', '')
                key = (law, art)
                if key in seen or not content:
                    continue
                seen.add(key)
                parts.append(f"\n• 《{law}》{art}:")
                parts.append(f"  {content}")   # 不再截断

        # ---- 威科先行法规 ----
        weko_regs = regulations.get('weko_regulations', {})
        if weko_regs:
            parts.append("\n\n================================================================")
            parts.append("【威科先行法规检索结果】")
            parts.append("================================================================")
            for round_key in ['round1', 'round2']:
                round_data = weko_regs.get(round_key, {})
                if not round_data:
                    continue
                query = round_data.get('query', round_key)
                parts.append(f"\n─── 检索主题:{query} ───")
                # 优先用结构化 parsed(上一轮改过),否则 fallback 到 results
                parsed = round_data.get('_parsed', {})
                items = parsed.get('items', []) if isinstance(parsed, dict) else []
                if items:
                    for it in items[:8]:
                        title = it.get('title', '').strip()
                        excerpt = it.get('excerpt', '').strip()
                        if title:
                            parts.append(f"• {title}")
                        if excerpt:
                            parts.append(f"  {excerpt[:500]}")
                else:
                    # 退回到原文 results(不截断)
                    parts.append(round_data.get('results', ''))

        # ---- 威科先行案例 ----
        weko_cases = regulations.get('weko_cases', {})
        if weko_cases:
            parts.append("\n\n================================================================")
            parts.append("【威科先行案例检索结果(按争议点)】")
            parts.append("================================================================")
            for dispute, case_data in weko_cases.items():
                if not isinstance(case_data, dict):
                    continue
                parts.append(f"\n─── 争议点:{dispute} ───")
                parsed = case_data.get('_parsed', {})
                case_numbers = parsed.get('case_numbers', []) if isinstance(parsed, dict) else []
                items = parsed.get('items', []) if isinstance(parsed, dict) else []
                if case_numbers:
                    parts.append(f"返回案号({len(case_numbers)} 个):")
                    for cn in case_numbers[:10]:
                        parts.append(f"  · {cn}")
                if items:
                    parts.append("案例摘要:")
                    for it in items[:5]:
                        title = it.get('title', '').strip()
                        excerpt = it.get('excerpt', '').strip()
                        if title:
                            parts.append(f"• {title}")
                        if excerpt:
                            parts.append(f"  {excerpt[:500]}")
                if not case_numbers and not items:
                    parts.append(case_data.get('results', '')[:1500])

        # ---- 最后的引用约束重申(放在 prompt 末尾,靠近回答) ----
        parts.append("\n\n================================================================")
        parts.append("【引用规则最终确认】")
        parts.append("================================================================")
        parts.append("1. 法条引用:仅限【核心适用法条】和【本地规范库主题检索】两节出现的条款编号")
        parts.append("2. 案号引用:仅限【威科先行案例检索结果】中实际返回的案号")
        parts.append("3. 管辖条款审查:必须引用民诉法第34条 + 司法解释第28条,禁止引用第24条")
        parts.append("4. 押金评价:分'金额合规'和'传递机制'两维分别标注,禁止在同一条款上打架")
        parts.append("5. 违约金畸高论证:使用定性表述,不要写出具体 LPR 数字或年化百分比")

        return "\n".join(parts)

    # ========================================================
    # 问题提取和评分(维持原逻辑)
    # ========================================================
    def _extract_issues(self, review_text: str) -> List[Dict]:
        """从审查文本中提取合规问题"""
        issues = []
        issue_patterns = {
            'validity': ['无效', '效力瑕疵', '不生效'],
            'unfair':   ['不公平', '显失公平', '格式条款'],
            'illegal':  ['违法', '违反', '不符合'],
            'missing':  ['缺失', '未约定', '未明确'],
            'risky':    ['风险', '不利', '可能导致'],
        }
        for issue_type, keywords in issue_patterns.items():
            for keyword in keywords:
                if keyword in review_text:
                    issues.append({'type': issue_type, 'keyword': keyword})
                    break
        return issues

    def _calculate_score(self, review_text: str) -> int:
        """计算合规评分(0-100)"""
        score = 100
        if '无效' in review_text:
            score -= 30
        if '违法' in review_text or '违反' in review_text:
            score -= 20
        if '不公平' in review_text:
            score -= 15
        if '缺失' in review_text:
            score -= 10
        if '风险' in review_text:
            score -= 5
        return max(0, score)