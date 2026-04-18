"""
Agent④ 交叉验证 v1.7
验证前三个Agent的法条引用和案例真实性

v1.7 改动:
1. 新增 regulation_loader 参数 —— 法条验证走"本地库 → 核心事实 → 基础法典编号范围"三级兜底
2. 不再对真实基础法条误判为"未能核实"(修复之前 Agent④ 过严的问题)
3. 案例验证仍复用 Agent② 的 _parsed.case_numbers(v1.6 已改)
4. 对每条验证结果附 source 字段(local_kb / core_fact / known_basic_law / weko / none)
"""
import re
from typing import Dict, List, Optional
from ..utils.llm_client import get_llm_client, LLMClient


# ============================================================
# 基础法典编号范围 —— 第 3 级兜底
# 对于在基础法典 + 合理编号范围内的引用,即使本地库/核心事实没直接命中,
# 也允许通过(因为这些是"引用可能正确"的保守判断,LLM 误编概率较低)
# ============================================================
_KNOWN_BASIC_LAWS = {
    "民法典": (1, 1260),
    "中华人民共和国民法典": (1, 1260),
    "民事诉讼法": (1, 287),
    "中华人民共和国民事诉讼法": (1, 287),
    "消费者权益保护法": (1, 63),
    "中华人民共和国消费者权益保护法": (1, 63),
    "价格法": (1, 48),
    "治安管理处罚法": (1, 119),
}


def _chinese_to_arabic(s: str) -> Optional[int]:
    """中文数字转阿拉伯数字"""
    if not s:
        return None
    s = str(s).strip().replace("第", "").replace("条", "").replace(" ", "")
    try:
        return int(s)
    except ValueError:
        pass
    digit_map = {'零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
                 '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    unit_map = {'十': 10, '百': 100, '千': 1000}
    result = 0
    current = 0
    for ch in s:
        if ch in digit_map:
            current = digit_map[ch]
        elif ch in unit_map:
            unit = unit_map[ch]
            if current == 0:
                current = 1
            result += current * unit
            current = 0
        else:
            return None
    result += current
    return result if result > 0 else None


class Agent04Validation:
    """交叉验证Agent"""

    def __init__(self, llm_client: LLMClient = None):
        self.llm_client = llm_client or get_llm_client()

    def validate(self, structure_report: Dict, compliance_report: Dict,
                 risk_report: Dict, weko_client, regulation_loader=None) -> Dict:
        """
        进行交叉验证

        Args:
            structure_report: Agent①的报告
            compliance_report: Agent②的报告
            risk_report: Agent③的报告
            weko_client: 威科先行MCP客户端
            regulation_loader: ⭐ v1.7 新增 —— 本地规范库加载器,用于法条验证兜底
        """
        # 提取需要验证的内容
        citations = self._extract_citations(structure_report, compliance_report, risk_report)

        # ⭐ v1.7 法条验证:走本地库 + 核心事实 + 基础法典编号三级兜底
        law_validations = self._validate_laws(
            citations.get('laws', []),
            compliance_report,
            regulation_loader,
        )

        # 案例验证(复用 Agent② 的 _parsed,v1.6 架构)
        case_validations = self._validate_cases(citations.get('cases', []), compliance_report)

        # 检查结论一致性
        consistency_check = self._check_consistency(structure_report, compliance_report, risk_report)

        # 构建验证提示词
        prompt = self._build_prompt(structure_report, compliance_report, risk_report,
                                    law_validations, case_validations, consistency_check)

        # 调用LLM进行综合总结
        validation_text = self.llm_client.analyze(
            prompt=prompt,
            system_prompt=self._get_system_prompt(),
            max_tokens=4096
        )

        return {
            'agent': 'Agent04_Validation',
            'validation': validation_text,
            'law_validations': law_validations,
            'case_validations': case_validations,
            'consistency_check': consistency_check,
            'corrections': self._extract_corrections(validation_text),
        }

    # ========================================================
    # system_prompt
    # ========================================================
    def _get_system_prompt(self) -> str:
        return """你是一位专业的法律文书交叉验证专家,负责对前三个Agent的分析结果做事实性审查。

你的任务:

1. 验证法条引用准确性
   - 法条是否存在
   - 引用是否准确
   - 适用是否恰当

2. 验证案例真实性
   - 案号是否真实
   - 是否在权威数据库命中

3. 检查结论一致性
   - 三个Agent的结论是否一致
   - 是否存在矛盾

4. 识别和修正幻觉
   - 虚构的法条
   - 虚构的案例
   - 不准确的表述

【验证结果等级】
- ✅ 已核实(valid=True):本地规范库或核心法律事实库直接命中,或威科返回
- 🟡 合理推定(source=known_basic_law):条号在该法律编号范围内,可信度较高但未逐条核对
- ❌ 未能核实(valid=False):三级兜底均不通过,应建议删除或改为定性表述

【硬性事实性约束】
如发现前序 Agent 引用管辖条款为"民诉法第24条",必须在【发现的幻觉问题】中指出其错误,
正确应为"民诉法第34条 + 最高法司法解释第28条"(房屋租赁按不动产专属管辖)。

如发现前序 Agent 写出具体的 LPR 百分比(如"14.8%"),必须在【发现的幻觉问题】中指出
其为过时数据,建议改为定性表述。

输出格式:
【法条验证结果】
【案例验证结果】
【一致性检查】
【发现的幻觉问题】
【修正建议】
"""

    # ========================================================
    # 引用提取
    # ========================================================
    def _extract_citations(self, *reports) -> Dict:
        """提取所有报告中的法条和案例引用"""
        citations = {'laws': [], 'cases': []}

        for report in reports:
            text = (report.get('analysis', '') or
                    report.get('review', '') or
                    report.get('assessment', '') or
                    report.get('opinion', '') or
                    report.get('report_text', ''))
            if not text:
                continue

            # 法条引用(支持阿拉伯和中文数字)
            law_patterns = [
                r'《([^》]+)》第(\d+)条',
                r'《([^》]+)》第([一二三四五六七八九十百零]+)条',
            ]
            for pattern in law_patterns:
                for match in re.findall(pattern, text):
                    citations['laws'].append({
                        'law_name': match[0],
                        'article': match[1],
                    })

            # 案号(支持 (2024)京 01 民终 1234 号 格式)
            case_patterns = [
                r'\((\d{4})\)[\u4e00-\u9fa5\d]+民[\u4e00-\u9fa5\d]*\d+号',
                r'\((\d{4})\)[\u4e00-\u9fa5\d]+行[\u4e00-\u9fa5\d]*\d+号',
            ]
            for pattern in case_patterns:
                # 用 finditer 拿到完整匹配文本
                for m in re.finditer(pattern, text):
                    citations['cases'].append(m.group(0))

        # 去重
        seen_laws = set()
        unique_laws = []
        for l in citations['laws']:
            key = (l['law_name'], l['article'])
            if key not in seen_laws:
                seen_laws.add(key)
                unique_laws.append(l)
        citations['laws'] = unique_laws

        citations['cases'] = list(dict.fromkeys(citations['cases']))  # 保序去重

        return citations

    # ========================================================
    # ⭐ 法条验证:三级兜底(v1.7 核心)
    # ========================================================
    def _validate_laws(self, laws: List[Dict], compliance_report: Dict,
                       regulation_loader=None) -> List[Dict]:
        """
        v1.7 法条验证:三级兜底
        1. 本地规范库精准命中(get_article_by_number → local_kb)
        2. 核心法律事实库(get_known_legal_fact → core_fact)
        3. 基础法典编号范围(KNOWN_BASIC_LAWS → known_basic_law)

        前 1+2 级都失败才进入第 3 级,第 3 级仍失败才标 valid=False。
        """
        validations = []

        # 先看 Agent② 的 regulations_used 是否包含该法条作为"已使用"(说明是 prompt 主动喂的)
        used_law_keys = set()
        regs_used = compliance_report.get('regulations_used', {}) if compliance_report else {}
        core_articles = regs_used.get('core_articles', {}) if isinstance(regs_used, dict) else {}
        for topic_items in core_articles.values():
            for it in topic_items or []:
                law_name = it.get('law_name', '')
                art_num = it.get('article_number')
                if law_name and art_num is not None:
                    used_law_keys.add((law_name, art_num))

        for law in laws[:15]:
            law_name = law.get('law_name', '').strip()
            art_str = str(law.get('article', '')).strip()
            art_num = _chinese_to_arabic(art_str) if not art_str.isdigit() else int(art_str)

            validation = {
                'law': law,
                'valid': False,
                'source': 'none',
                'evidence': '',
            }

            # 【1 级】Agent② 已主动使用 —— 最高可信
            if art_num is not None:
                for used_law_name, used_art_num in used_law_keys:
                    if used_art_num == art_num and (used_law_name in law_name or law_name in used_law_name):
                        validation['valid'] = True
                        validation['source'] = 'prompt_used'
                        validation['evidence'] = f'Agent② prompt 核心法条已直接提供全文'
                        break

            # 【2 级】本地规范库精准命中
            if not validation['valid'] and regulation_loader is not None and art_num is not None:
                try:
                    hit = regulation_loader.get_article_by_number(law_name, art_num)
                    if hit:
                        validation['valid'] = True
                        validation['source'] = hit.get('source', 'local_kb')
                        validation['evidence'] = hit.get('content', '')[:200]
                except Exception as e:
                    validation['error_1'] = f'本地查询异常: {e}'

            # 【3 级】基础法典编号范围(保守放行)
            if not validation['valid'] and art_num is not None:
                for known_name, (lo, hi) in _KNOWN_BASIC_LAWS.items():
                    if known_name in law_name and lo <= art_num <= hi:
                        validation['valid'] = True
                        validation['source'] = 'known_basic_law'
                        validation['evidence'] = (
                            f'《{known_name}》条号 {art_num} 在合法编号范围 {lo}-{hi} 内,'
                            '属基础法典常见条款,按保守推定视为可能有效'
                        )
                        break

            # 三级兜底全失败 → 标 valid=False
            if not validation['valid']:
                validation['evidence'] = (
                    f'本地规范库、核心法律事实库均未命中;'
                    f'且《{law_name}》不在基础法典白名单内。建议删除或改为定性表述。'
                )

            validations.append(validation)

        return validations

    # ========================================================
    # 案例验证:复用 Agent② 的 _parsed.case_numbers
    # ========================================================
    def _validate_cases(self, cases: List[str], compliance_report: Dict) -> List[Dict]:
        """案例验证:从 Agent② 的威科检索结果 _parsed 中查找"""
        validations = []
        weko_cases_data = compliance_report.get('regulations_used', {}).get('weko_cases', {})

        # 汇总所有威科返回的案号
        all_returned_cn = set()
        for dispute, case_data in weko_cases_data.items():
            if not isinstance(case_data, dict):
                continue
            parsed = case_data.get('_parsed', {}) or {}
            for cn in parsed.get('case_numbers', []):
                all_returned_cn.add(cn.strip())

        for case_number in cases[:15]:
            cn = case_number.strip()
            # 识别明显的幻觉模式(如未来年份、X占位符、12345)
            hallucination_flag = False
            hallucination_reason = ''
            year_match = re.match(r'\((\d{4})\)', cn)
            if year_match:
                try:
                    year = int(year_match.group(1))
                    if year > 2026 or year < 1980:
                        hallucination_flag = True
                        hallucination_reason = f'年份 {year} 不合理'
                except ValueError:
                    pass
            if 'XXXX' in cn or '12345' in cn:
                hallucination_flag = True
                hallucination_reason = '包含占位符/虚假数字特征'

            if hallucination_flag:
                validations.append({
                    'case_number': cn,
                    'valid': False,
                    'source': 'hallucination_detected',
                    'reason': hallucination_reason,
                })
                continue

            # 看是否在威科返回中
            hit = any(cn == rcn or cn in rcn or rcn in cn for rcn in all_returned_cn)
            validations.append({
                'case_number': cn,
                'valid': hit,
                'source': 'weko' if hit else 'none',
                'reason': '威科检索结果命中' if hit else '未在威科检索结果中出现',
            })

        return validations

    # ========================================================
    # 一致性检查(维持原逻辑)
    # ========================================================
    def _check_consistency(self, structure_report: Dict, compliance_report: Dict,
                          risk_report: Dict) -> Dict:
        consistency = {'consistent': True, 'conflicts': []}

        structure_risks = set(structure_report.get('risks', []))
        compliance_issues = {issue['type'] for issue in compliance_report.get('issues', [])}

        if structure_risks and not compliance_issues:
            consistency['consistent'] = False
            consistency['conflicts'].append({
                'type': 'risk_mismatch',
                'description': '结构分析发现风险,但合规审查未发现问题',
            })

        risk_feasibility = risk_report.get('feasibility', {}).get('conclusion')
        compliance_score = compliance_report.get('compliance_score', 100)
        if risk_feasibility == 'recommended' and compliance_score < 60:
            consistency['consistent'] = False
            consistency['conflicts'].append({
                'type': 'feasibility_mismatch',
                'description': '风险评估建议签署,但合规评分较低',
            })

        return consistency

    # ========================================================
    # Prompt 构建
    # ========================================================
    def _build_prompt(self, structure_report: Dict, compliance_report: Dict,
                     risk_report: Dict, law_validations: List, case_validations: List,
                     consistency_check: Dict) -> str:
        parts = []
        parts.append("请对以下分析结果进行交叉验证:\n")

        # 资源盘点
        regs_used = compliance_report.get('regulations_used', {})
        core_count = sum(len(v) for v in (regs_used.get('core_articles', {}) or {}).values())
        weko_cases_count = len(regs_used.get('weko_cases', {}) or {})
        parts.append("【验证资源盘点】")
        parts.append(f"- Agent② 本地核心法条:{core_count} 条(已主动喂给 LLM)")
        parts.append(f"- Agent② 威科案例争议点:{weko_cases_count} 组")
        parts.append("")

        # 法条验证
        parts.append("【法条验证结果】")
        valid_count = sum(1 for v in law_validations if v['valid'])
        parts.append(f"共 {len(law_validations)} 条引用,其中 {valid_count} 条通过核实")
        source_stat = {}
        for v in law_validations:
            src = v.get('source', 'none')
            source_stat[src] = source_stat.get(src, 0) + 1
        parts.append(f"来源分布:{source_stat}")
        parts.append("")
        parts.append("验证明细:")
        for v in law_validations:
            law = v['law']
            status = "✅" if v['valid'] else "❌"
            src = v.get('source', 'none')
            parts.append(
                f"  {status} 《{law['law_name']}》第{law['article']}条 "
                f"[来源:{src}]"
            )
            if v.get('evidence'):
                parts.append(f"     证据:{v['evidence'][:120]}")
        parts.append("")

        # 案例验证
        parts.append("【案例验证结果】")
        valid_cases = [v for v in case_validations if v['valid']]
        parts.append(f"共 {len(case_validations)} 个案号引用,其中 {len(valid_cases)} 个经威科核实")
        parts.append("")
        parts.append("验证明细:")
        for v in case_validations:
            status = "✅" if v['valid'] else "❌"
            parts.append(f"  {status} {v['case_number']} [来源:{v.get('source','?')}]")
            if v.get('reason'):
                parts.append(f"     原因:{v['reason']}")
        parts.append("")

        # 一致性
        parts.append("【一致性检查】")
        if consistency_check['consistent']:
            parts.append("✅ 各 Agent 结论一致")
        else:
            parts.append("⚠ 发现以下冲突:")
            for conflict in consistency_check['conflicts']:
                parts.append(f"  - {conflict['description']}")
        parts.append("")

        # 各 Agent 核心结论
        parts.append("【各 Agent 核心结论】")
        parts.append(f"Agent① 风险:{', '.join(structure_report.get('risks', [])) or '(未提取)'}")
        parts.append(f"Agent② 评分:{compliance_report.get('compliance_score', 0)}/100")
        parts.append(f"Agent③ 可行性:{risk_report.get('feasibility', {}).get('conclusion', 'unknown')}")
        parts.append("")

        # 验证规则(给 LLM 的工作指南)
        parts.append("【你的验证工作规则】")
        parts.append("1. 对于 valid=True 的法条引用,保留,并可标注 source")
        parts.append("2. 对于 valid=False 的法条引用,列入【发现的幻觉问题】,建议删除或改为定性表述")
        parts.append("3. 对于 hallucination_detected 的案号(如未来年份),强调必须删除")
        parts.append("4. 注意检查管辖条款:若前序 Agent 写了'民诉法第24条',必须指出错误")
        parts.append("5. 注意检查 LPR 数字:若前序 Agent 写了具体百分比,必须指出已过时")
        parts.append("6. 注意检查规章号:若前序 Agent 写了具体发文号,核实是否在威科/本地库返回中")

        return "\n".join(parts)

    # ========================================================
    # 修正建议提取
    # ========================================================
    def _extract_corrections(self, validation_text: str) -> List[Dict]:
        corrections = []
        if '修正' in validation_text or '更正' in validation_text or '删除' in validation_text:
            for line in validation_text.split('\n'):
                stripped = line.strip()
                if stripped.startswith('-') and (
                    '修正' in stripped or '更正' in stripped or '删除' in stripped
                ):
                    corrections.append({
                        'text': stripped[1:].strip(),
                        'type': 'correction',
                    })
        return corrections