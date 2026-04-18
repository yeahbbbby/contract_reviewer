"""
Agent③ 风险综合研判
综合前两个Agent的输出进行风险评估
"""
from typing import Dict, List
from ..utils.llm_client import get_llm_client, LLMClient


class Agent03Risk:
    """风险综合研判Agent"""

    def __init__(self, llm_client: LLMClient = None):
        """
        初始化Agent

        Args:
            llm_client: LLM客户端（可选，默认使用全局客户端）
        """
        self.llm_client = llm_client or get_llm_client()

    def assess(self, structure_report: Dict, compliance_report: Dict,
               regulation_loader, weko_client) -> Dict:
        """
        进行风险综合研判

        Args:
            structure_report: Agent①的结构分析报告
            compliance_report: Agent②的合规审查报告
            regulation_loader: 本地规范库加载器
            weko_client: 威科先行MCP客户端

        Returns:
            风险评估报告
        """
        # 构建研判提示词
        prompt = self._build_prompt(structure_report, compliance_report)

        # 调用LLM
        assessment_text = self.llm_client.analyze(
            prompt=prompt,
            system_prompt=self._get_system_prompt(),
            max_tokens=8192
        )

        return {
            'agent': 'Agent03_Risk',
            'assessment': assessment_text,
            'risk_matrix': self._build_risk_matrix(assessment_text),
            'feasibility': self._assess_feasibility(assessment_text),
            'recommendations': self._extract_recommendations(assessment_text)
        }

    def _get_system_prompt(self) -> str:
        """获取系统提示词"""
        return """你是一位专业的房屋租赁合同风险评估专家，专门为二房东（转租方）提供风险综合研判。

你的任务是综合前两个Agent的分析结果，进行全面的风险评估。

【风险分类】
按风险等级：
- 红线风险：导致合同无效或严重违法的风险
- 高风险：可能导致重大损失的风险
- 中风险：可能导致一般损失的风险
- 低风险：影响较小的风险

按风险类型：
- 效力风险：合同效力瑕疵
- 履约风险：合同履行障碍
- 清退风险：清退次承租人困难
- 证据风险：举证责任不利
- 资金风险：租金押金损失
- 责任风险：承担过重责任

【二房东立场的关键风险点】
1. 收租安全
   - 租金差价是否合理
   - 支付周期是否错配
   - 收租权利是否明确

2. 押金控制
   - 押金是否足够覆盖风险
   - 押金退还条件是否清晰
   - 押金传递机制是否合理

3. 清退效率
   - 解除条件是否明确
   - 清退程序是否可行
   - 清退成本是否可控

4. 责任边界
   - 对原房东的责任是否清晰
   - 对次承租人的责任是否合理
   - 第三方责任是否明确
【极其重要的约束 — 关乎风险评估的法律可信度】
1. 引用法条时,必须来自下方 prompt 提供的前序 Agent 材料中真实出现的条款。
   禁止编造法条号、禁止编造条文内容。
2. 引用案例时,必须来自前序材料中真实出现的案号原文。
3. 【禁止"脱字幻觉"】禁止使用"(XXXX)京XXXX民初XXXX号"这种末位为 X 的占位案号,
   **并为其编造裁判要旨**。如果手头没有真实案号,就不要提案号,不要写"案号真实"。
4. 禁止编造"北京高院指导意见""最高法会议纪要"等具体文件名和内容,除非前序材料明确引用。
5. 禁止为"LPR 四倍"等数字制造看似精确的年化百分比,这些数字会过时且难以验证。
6. 如果某个结论找不到可靠依据,写"[此点建议由律师独立核验]",而不是强行附依据。

【研判输出】
1. 风险矩阵（按等级和类型分类）
2. 可行性结论（建议签署/谨慎签署/不建议签署）
3. 风险应对建议（规避/转移/降低/接受）
4. 优先处理事项

输出格式：
【风险矩阵】
【可行性评估】
【风险应对建议】
【优先处理事项】
"""

    def _build_prompt(self, structure_report: Dict, compliance_report: Dict) -> str:
        """构建研判提示词"""
        prompt_parts = []

        prompt_parts.append("请基于以下分析结果进行风险综合研判：\n")

        # Agent①的结构分析
        prompt_parts.append("【主体和交易结构分析】")
        prompt_parts.append(structure_report.get('analysis', ''))
        prompt_parts.append("")

        # Agent②的合规审查
        prompt_parts.append("【合规审查结果】")
        prompt_parts.append(compliance_report.get('review', ''))
        prompt_parts.append(f"\n合规评分: {compliance_report.get('compliance_score', 0)}/100")
        prompt_parts.append("")

        # 识别的风险
        if structure_report.get('risks'):
            prompt_parts.append("【已识别风险】")
            for risk in structure_report['risks']:
                prompt_parts.append(f"- {risk}")
            prompt_parts.append("")

        # 合规问题
        if compliance_report.get('issues'):
            prompt_parts.append("【合规问题】")
            for issue in compliance_report['issues']:
                prompt_parts.append(f"- {issue['type']}: {issue['keyword']}")
            prompt_parts.append("")

        return "\n".join(prompt_parts)

    def _build_risk_matrix(self, assessment_text: str) -> Dict:
        """构建风险矩阵"""
        matrix = {
            'red_line': [],      # 红线风险
            'high': [],          # 高风险
            'medium': [],        # 中风险
            'low': []            # 低风险
        }

        # 简单的关键词匹配
        risk_keywords = {
            'red_line': ['无效', '违法', '禁止', '红线'],
            'high': ['重大', '严重', '高风险', '可能导致'],
            'medium': ['一般', '中等', '需要注意'],
            'low': ['轻微', '较小', '低风险']
        }

        lines = assessment_text.split('\n')
        for line in lines:
            for level, keywords in risk_keywords.items():
                if any(kw in line for kw in keywords):
                    if line.strip() and line.strip().startswith('-'):
                        matrix[level].append(line.strip()[1:].strip())

        return matrix

    def _assess_feasibility(self, assessment_text: str) -> Dict:
        """评估可行性"""
        feasibility = {
            'conclusion': 'unknown',
            'confidence': 0,
            'reasons': []
        }

        # 判断结论
        if '不建议签署' in assessment_text or '不可行' in assessment_text:
            feasibility['conclusion'] = 'not_recommended'
            feasibility['confidence'] = 80
        elif '谨慎签署' in assessment_text or '需要修改' in assessment_text:
            feasibility['conclusion'] = 'conditional'
            feasibility['confidence'] = 60
        elif '建议签署' in assessment_text or '可行' in assessment_text:
            feasibility['conclusion'] = 'recommended'
            feasibility['confidence'] = 70

        return feasibility

    def _extract_recommendations(self, assessment_text: str) -> List[Dict]:
        """提取建议"""
        recommendations = []

        # 查找建议部分
        if '建议' in assessment_text:
            lines = assessment_text.split('\n')
            in_recommendation_section = False

            for line in lines:
                if '建议' in line and ('【' in line or '#' in line):
                    in_recommendation_section = True
                    continue

                if in_recommendation_section:
                    if line.strip().startswith('-') or line.strip().startswith('•'):
                        recommendations.append({
                            'text': line.strip()[1:].strip(),
                            'priority': 'high' if '优先' in line or '立即' in line else 'medium'
                        })
                    elif line.strip().startswith('【') or line.strip().startswith('#'):
                        break

        return recommendations
