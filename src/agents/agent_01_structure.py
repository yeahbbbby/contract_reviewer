"""
Agent① 主体+交易结构分析
分析合同主体资格和转租交易结构
"""
from typing import Dict, List
from ..utils.llm_client import get_llm_client, LLMClient


class Agent01Structure:
    """主体和交易结构分析Agent"""

    def __init__(self, llm_client: LLMClient = None):
        """
        初始化Agent

        Args:
            llm_client: LLM客户端（可选，默认使用全局客户端）
        """
        self.llm_client = llm_client or get_llm_client()

    def analyze(self, clauses: Dict, context_info: Dict) -> Dict:
        """
        分析主体和交易结构

        Args:
            clauses: 提取的条款
            context_info: 用户提供的背景信息

        Returns:
            分析报告
        """
        # 构建分析提示词
        prompt = self._build_prompt(clauses, context_info)

        # 调用LLM
        analysis_text = self.llm_client.analyze(
            prompt=prompt,
            system_prompt=self._get_system_prompt(),
            max_tokens=4096
        )

        return {
            'agent': 'Agent01_Structure',
            'analysis': analysis_text,
            'findings': self._extract_findings(analysis_text),
            'risks': self._extract_risks(analysis_text)
        }

    def _get_system_prompt(self) -> str:
        """获取系统提示词"""
        return """你是一位专业的房屋租赁合同审查专家，专门为二房东（转租方）提供主体资格和交易结构分析。

你的任务是：
1. 分析合同主体资格
   - 转租方（二房东）的身份和权利来源
   - 次承租人的身份和资格
   - 原房东的授权情况

2. 分析交易结构
   - 租期衔接：转租期限是否在原租期内
   - 租金结构：租金差价、支付周期、资金流
   - 押金传递：押金金额、退还机制
   - 责任链条：各方责任边界

3. 识别结构性风险
   - 主体资格缺陷
   - 租期错配风险
   - 资金链风险
   - 责任不清风险

请以二房东的立场，重点关注：
- 转租合法性
- 收租安全性
- 清退可行性
- 责任边界清晰度

输出格式：
【主体资格分析】
【交易结构分析】
【风险识别】
【结论和建议】
"""

    def _build_prompt(self, clauses: Dict, context_info: Dict) -> str:
        """构建分析提示词"""
        prompt_parts = []

        prompt_parts.append("请分析以下转租合同的主体和交易结构：\n")

        # 背景信息
        prompt_parts.append("【背景信息】")
        prompt_parts.append(f"角色定位: {context_info.get('role', '二房东')}")
        prompt_parts.append(f"合同阶段: {context_info.get('stage', '待签')}")
        if context_info.get('concerns'):
            prompt_parts.append(f"关注重点: {', '.join(context_info['concerns'])}")
        prompt_parts.append("")

        # 主体信息
        subject_clause = clauses['clauses'].get('主体信息', {})
        if subject_clause.get('found'):
            prompt_parts.append("【主体信息】")
            for section in subject_clause.get('sections', []):
                prompt_parts.append(f"{section['title']}")
                prompt_parts.append(section['content'])
            prompt_parts.append("")

        # 标的物
        property_clause = clauses['clauses'].get('标的物', {})
        if property_clause.get('found'):
            prompt_parts.append("【标的物】")
            for section in property_clause.get('sections', []):
                prompt_parts.append(f"{section['title']}")
                prompt_parts.append(section['content'])
            prompt_parts.append("")

        # 租期
        term_clause = clauses['clauses'].get('租期', {})
        if term_clause.get('found'):
            prompt_parts.append("【租期】")
            for section in term_clause.get('sections', []):
                prompt_parts.append(f"{section['title']}")
                prompt_parts.append(section['content'])
            prompt_parts.append("")

        # 租金
        rent_clause = clauses['clauses'].get('租金', {})
        if rent_clause.get('found'):
            prompt_parts.append("【租金】")
            for section in rent_clause.get('sections', []):
                prompt_parts.append(f"{section['title']}")
                prompt_parts.append(section['content'])
            prompt_parts.append("")

        # 押金
        deposit_clause = clauses['clauses'].get('押金', {})
        if deposit_clause.get('found'):
            prompt_parts.append("【押金】")
            for section in deposit_clause.get('sections', []):
                prompt_parts.append(f"{section['title']}")
                prompt_parts.append(section['content'])
            prompt_parts.append("")

        # 转租条款
        sublease_clause = clauses['clauses'].get('转租条款', {})
        if sublease_clause.get('found'):
            prompt_parts.append("【转租条款】")
            for section in sublease_clause.get('sections', []):
                prompt_parts.append(f"{section['title']}")
                prompt_parts.append(section['content'])
            prompt_parts.append("")

        return "\n".join(prompt_parts)

    def _extract_findings(self, analysis_text: str) -> List[Dict]:
        """从分析文本中提取关键发现"""
        findings = []

        # 简单的关键词提取
        if '缺失' in analysis_text or '未明确' in analysis_text:
            findings.append({
                'type': 'missing_info',
                'severity': 'high'
            })

        if '不符' in analysis_text or '违反' in analysis_text:
            findings.append({
                'type': 'non_compliance',
                'severity': 'high'
            })

        if '风险' in analysis_text:
            findings.append({
                'type': 'risk_identified',
                'severity': 'medium'
            })

        return findings

    def _extract_risks(self, analysis_text: str) -> List[str]:
        """从分析文本中提取风险点"""
        risks = []

        risk_keywords = [
            '主体资格', '租期错配', '资金链', '责任不清',
            '授权缺失', '租金倒挂', '押金不足', '清退困难'
        ]

        for keyword in risk_keywords:
            if keyword in analysis_text:
                risks.append(keyword)

        return risks
