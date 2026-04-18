"""
Agent⑤ 意见书生成
生成最终审查报告和Word红线修订版
"""
from typing import Dict, List
from datetime import datetime
from ..utils.llm_client import get_llm_client, LLMClient


class Agent05Report:
    """意见书生成Agent"""

    def __init__(self, llm_client: LLMClient = None):
        """
        初始化Agent

        Args:
            llm_client: LLM客户端（可选，默认使用全局客户端）
        """
        self.llm_client = llm_client or get_llm_client()

    def generate(self, all_reports: Dict, parsed_doc: Dict, mcp_client,
                 comparison_result: Dict = None) -> Dict:
        """
        生成审查报告

        Args:
            all_reports: 所有Agent的报告
            parsed_doc: 解析后的原始文档
            mcp_client: 北大法宝MCP客户端
            comparison_result: 示范文本比对结果

        Returns:
            最终报告
        """
        # 构建报告生成提示词
        prompt = self._build_prompt(all_reports, comparison_result)

        # 调用LLM生成报告
        report_text = self.llm_client.analyze(
            prompt=prompt,
            system_prompt=self._get_system_prompt(),
            max_tokens=16384
        )

        # 生成结构化报告
        structured_report = self._structure_report(report_text, all_reports)

        # 生成修改建议
        modifications = self._generate_modifications(all_reports, report_text)

        return {
            'agent': 'Agent05_Report',
            'report_text': report_text,
            'structured_report': structured_report,
            'modifications': modifications,
            'hyperlinks': self._collect_hyperlinks(all_reports, mcp_client),
            'generated_at': datetime.now().isoformat()
        }

    def _get_system_prompt(self) -> str:
        """获取系统提示词"""
        return """你是一位专业的法律文书撰写专家，负责生成房屋转租合同审查意见书。

你的任务是综合前四个Agent的分析结果，生成一份专业、完整、实用的审查意见书。

【报告结构】
一、基本情况
   - 合同概况
   - 审查范围
   - 审查依据

二、主体和交易结构分析
   - 主体资格审查
   - 交易结构分析
   - 结构性风险

三、合规性审查
   - 宏观合规性
   - 中观合规性
   - 微观合规性
   - 合规问题清单

四、风险综合评估
   - 风险矩阵
   - 风险等级分类
   - 风险类型分类
   - 可行性结论

五、交叉验证结果
   - 法条验证
   - 案例验证
   - 一致性检查

六、审查结论
   - 总体评价
   - 可行性意见
   - 风险提示

七、修改建议
   - 必须修改项（红线问题）
   - 建议修改项（高风险）
   - 可选修改项（中低风险）
   - 具体修改方案

八、附件
   - 法律依据清单
   - 参考案例清单
   - 北大法宝超链接

【【撰写要求】
1. 立场明确：始终站在二房东（转租方）的立场
2. 逻辑清晰：结论有据，推理严密
3. 语言专业：使用法律术语，表述准确
4. 实用性强：提供可操作的修改建议
5. 风险导向：突出关键风险点

【重点关注】
- 收租安全：租金差价、支付周期、收租权利
- 押金控制：押金金额、退还条件、传递机制
- 清退效率：解除条件、清退程序、清退成本
- 责任边界：对上对下责任、第三方责任

【严格禁止 — 否则属于失职】
- ❌ 禁止编造或虚构案号(如末位是 12345、56789、9876 这类顺序/逆序数字的案号)
- ❌ 禁止编造 URL、"北大法宝链接"、"人大官网链接"。你没有能力生成真实链接。
- ❌ 禁止虚构律所名称、律师姓名、邮箱、电话、版权声明。报告末尾不要署名。
- ❌ 禁止在报告中罗列"交付文件包"/"Word 批注版"/"附件 X:Excel 可填版"/"现状照片册"
     等实际不存在的文件。本系统只输出:
       (1) 你现在写的这份意见书文本
       (2) 一份单独的红线修订版 .docx
     没有其他附件包、Word 批注版、Excel 模板等。禁止暗示用户会收到它们。
- ❌ 禁止编造"司法基准分"/"合理审慎注意义务 60 分线"这类听起来专业但无权威出处的数字
- ❌ 对前序 Agent 提供的案号和法条引用:
     - 若其来源清晰可靠,可正常引用
     - 若你无法确认其真实性(特别是末位数字可疑的),应当从本报告中删除,
       或标注"[待独立核实]";禁止自行打勾"✅ 已核验"

【引用规范】
- 法条引用只写:《法律名称》第 N 条 + 条文摘要(无需附链接)
- 案例引用只写:案号 + 一句话裁判要旨(无需附链接)
- 如果某个结论找不到可靠依据,明确写"[本结论建议由律师独立核验]",而不是强行附依据

输出格式：使用 Markdown 格式,层次分明,便于阅读。报告结尾不加署名、版权和联系方式。
"""

    def _build_prompt(self, all_reports: Dict, comparison_result: Dict = None) -> str:
        """构建报告生成提示词"""
        prompt_parts = []

        prompt_parts.append("请基于以下分析结果生成审查意见书：\n")

        # Agent①结构分析
        if 'structure' in all_reports:
            prompt_parts.append("【主体和交易结构分析】")
            prompt_parts.append(all_reports['structure'].get('analysis', ''))
            prompt_parts.append("")

        # Agent②合规审查
        if 'compliance' in all_reports:
            prompt_parts.append("【合规审查结果】")
            prompt_parts.append(all_reports['compliance'].get('review', ''))
            prompt_parts.append(f"合规评分: {all_reports['compliance'].get('compliance_score', 0)}/100")
            prompt_parts.append("")

        # Agent③风险评估
        if 'risk' in all_reports:
            prompt_parts.append("【风险综合评估】")
            prompt_parts.append(all_reports['risk'].get('assessment', ''))
            feasibility = all_reports['risk'].get('feasibility', {})
            prompt_parts.append(f"可行性结论: {feasibility.get('conclusion', 'unknown')}")
            prompt_parts.append("")

        # Agent④验证结果
        if 'validation' in all_reports:
            prompt_parts.append("【交叉验证结果】")
            prompt_parts.append(all_reports['validation'].get('validation', ''))
            prompt_parts.append("")

        # 示范文本比对
        if comparison_result:
            prompt_parts.append("【示范文本比对】")
            summary = comparison_result.get('summary', {})
            prompt_parts.append(f"符合率: {summary.get('compliance_rate', 0):.1f}%")
            prompt_parts.append(f"缺失条款: {summary.get('missing_count', 0)}项")
            prompt_parts.append(f"风险条款: {summary.get('risky_count', 0)}项")
            prompt_parts.append("")

        return "\n".join(prompt_parts)

    def _structure_report(self, report_text: str, all_reports: Dict) -> Dict:
        """将报告文本结构化"""
        return {
            'title': '房屋转租合同审查意见书',
            'date': datetime.now().strftime('%Y年%m月%d日'),
            'sections': self._parse_sections(report_text),
            'summary': {
                'compliance_score': all_reports.get('compliance', {}).get('compliance_score', 0),
                'feasibility': all_reports.get('risk', {}).get('feasibility', {}).get('conclusion', 'unknown'),
                'risk_count': len(all_reports.get('risk', {}).get('risk_matrix', {}).get('high', [])),
            }
        }

    def _parse_sections(self, report_text: str) -> List[Dict]:
        """解析报告章节"""
        sections = []
        current_section = None
        lines = report_text.split('\n')

        for line in lines:
            # 识别一级标题
            if line.strip().startswith('一、') or line.strip().startswith('# '):
                if current_section:
                    sections.append(current_section)
                current_section = {
                    'title': line.strip(),
                    'content': [],
                    'level': 1
                }
            # 识别二级标题
            elif line.strip().startswith('（') or line.strip().startswith('## '):
                if current_section:
                    current_section['content'].append({
                        'subtitle': line.strip(),
                        'text': []
                    })
            else:
                if current_section and line.strip():
                    if current_section['content'] and isinstance(current_section['content'][-1], dict):
                        current_section['content'][-1]['text'].append(line.strip())
                    else:
                        current_section['content'].append(line.strip())

        if current_section:
            sections.append(current_section)

        return sections

    def _generate_modifications(self, all_reports: Dict, report_text: str) -> List[Dict]:
        """生成修改建议列表"""
        modifications = []

        # 从风险评估中提取修改建议
        if 'risk' in all_reports:
            recommendations = all_reports['risk'].get('recommendations', [])
            for rec in recommendations:
                modifications.append({
                    'priority': rec.get('priority', 'medium'),
                    'description': rec['text'],
                    'source': 'risk_assessment'
                })

        # 从验证结果中提取修正建议
        if 'validation' in all_reports:
            corrections = all_reports['validation'].get('corrections', [])
            for corr in corrections:
                modifications.append({
                    'priority': 'high',
                    'description': corr['text'],
                    'source': 'validation'
                })

        # 从报告文本中提取修改建议
        if '修改建议' in report_text or '建议修改' in report_text:
            lines = report_text.split('\n')
            in_modification_section = False

            for line in lines:
                if '修改建议' in line or '建议修改' in line:
                    in_modification_section = True
                    continue

                if in_modification_section and line.strip().startswith('-'):
                    priority = 'high' if '必须' in line or '立即' in line else 'medium'
                    modifications.append({
                        'priority': priority,
                        'description': line.strip()[1:].strip(),
                        'source': 'report'
                    })

        # 按优先级排序
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        modifications.sort(key=lambda x: priority_order.get(x['priority'], 3))

        return modifications

    def _collect_hyperlinks(self, all_reports: Dict, mcp_client) -> Dict:
        """收集北大法宝超链接"""
        hyperlinks = {
            'laws': [],
            'cases': []
        }

        # 从合规报告中提取法规
        if 'compliance' in all_reports:
            regulations = all_reports['compliance'].get('regulations_used', {})

            for law in regulations.get('national', [])[:10]:
                if law.get('id'):
                    hyperlinks['laws'].append({
                        'title': law.get('title', ''),
                        'url': mcp_client.get_hyperlink('law', law['id'])
                    })

            for case in regulations.get('cases', [])[:10]:
                if case.get('id'):
                    hyperlinks['cases'].append({
                        'title': case.get('title', ''),
                        'case_number': case.get('case_number', ''),
                        'url': mcp_client.get_hyperlink('case', case['id'])
                    })

        return hyperlinks
