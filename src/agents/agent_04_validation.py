"""
Agent④ 交叉验证
验证前三个Agent的法条引用和案例真实性
"""
from typing import Dict, List
from ..utils.llm_client import get_llm_client, LLMClient


class Agent04Validation:
    """交叉验证Agent"""

    def __init__(self, llm_client: LLMClient = None):
        """
        初始化Agent

        Args:
            llm_client: LLM客户端（可选，默认使用全局客户端）
        """
        self.llm_client = llm_client or get_llm_client()

    def validate(self, structure_report: Dict, compliance_report: Dict,
                 risk_report: Dict, weko_client) -> Dict:
        """
        进行交叉验证

        Args:
            structure_report: Agent①的报告
            compliance_report: Agent②的报告
            risk_report: Agent③的报告
            weko_client: 威科先行MCP客户端

        Returns:
            验证报告
        """
        # 提取需要验证的内容
        citations = self._extract_citations(structure_report, compliance_report, risk_report)

        # 验证法条引用（使用威科先行）
        law_validations = self._validate_laws(citations.get('laws', []), weko_client)

        # 验证案例引用（使用威科先行）
        case_validations = self._validate_cases(citations.get('cases', []), weko_client)

        # 检查结论一致性
        consistency_check = self._check_consistency(structure_report, compliance_report, risk_report)

        # 构建验证提示词
        prompt = self._build_prompt(structure_report, compliance_report, risk_report,
                                    law_validations, case_validations, consistency_check)

        # 调用LLM进行综合验证
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
            'corrections': self._extract_corrections(validation_text)
        }

    def _get_system_prompt(self) -> str:
        """获取系统提示词"""
        return """你是一位专业的法律文书交叉验证专家，负责验证前三个Agent的分析结果。

你的任务是：
1. 验证法条引用准确性
   - 法条是否存在
   - 引用是否准确
   - 适用是否恰当

2. 验证案例真实性
   - 案号是否真实
   - 案情是否相关
   - 裁判观点是否准确

3. 检查结论一致性
   - 三个Agent的结论是否一致
   - 是否存在矛盾
   - 逻辑是否连贯

4. 识别和修正幻觉
   - 虚构的法条
   - 虚构的案例
   - 不准确的表述

输出格式：
【法条验证结果】
【案例验证结果】
【一致性检查】
【发现的问题】
【修正建议】
"""

    def _extract_citations(self, *reports) -> Dict:
        """提取所有报告中的法条和案例引用"""
        citations = {
            'laws': [],
            'cases': []
        }

        for report in reports:
            text = report.get('analysis', '') or report.get('review', '') or report.get('assessment', '')

            # 提取法条引用（简单模式匹配）
            import re
            law_patterns = [
                r'《([^》]+)》第(\d+)条',
                r'《([^》]+)》第([一二三四五六七八九十百]+)条',
            ]

            for pattern in law_patterns:
                matches = re.findall(pattern, text)
                for match in matches:
                    citations['laws'].append({
                        'law_name': match[0],
                        'article': match[1]
                    })

            # 提取案例引用
            case_pattern = r'\((\d{4}).*?第\d+号\)'
            case_matches = re.findall(case_pattern, text)
            citations['cases'].extend(case_matches)

        return citations

    def _validate_laws(self, laws: List[Dict], weko_client) -> List[Dict]:
        """验证法条引用（使用威科先行）"""
        validations = []

        for law in laws[:10]:  # 限制验证数量
            try:
                # 使用威科先行检索法条
                result = weko_client.search_regulations(
                    query=f"{law['law_name']} 第{law['article']}条",
                    region="全国"
                )

                # 简单判断：如果检索到结果就认为有效
                valid = bool(result.get('results'))

                validations.append({
                    'law': law,
                    'valid': valid,
                    'search_result': result.get('results', '')[:200] if valid else None
                })
            except Exception as e:
                # 威科先行失败时，标记为未验证而不是无效
                validations.append({
                    'law': law,
                    'valid': None,  # None表示未验证
                    'error': f"验证失败: {str(e)}"
                })

        return validations

    def _validate_cases(self, cases: List[str], weko_client) -> List[Dict]:
        """验证案例引用（使用威科先行）"""
        validations = []

        for case_number in cases[:10]:  # 限制验证数量
            try:
                # 使用威科先行检索案例
                result = weko_client.search_cases(
                    query=case_number,
                    region="全国"
                )

                # 简单判断：如果检索到结果就认为有效
                valid = bool(result.get('results'))

                validations.append({
                    'case_number': case_number,
                    'valid': valid,
                    'search_result': result.get('results', '')[:200] if valid else None
                })
            except Exception as e:
                # 威科先行失败时，标记为未验证
                validations.append({
                    'case_number': case_number,
                    'valid': None,  # None表示未验证
                    'error': f"验证失败: {str(e)}"
                })

        return validations

    def _check_consistency(self, structure_report: Dict, compliance_report: Dict,
                          risk_report: Dict) -> Dict:
        """检查结论一致性"""
        consistency = {
            'consistent': True,
            'conflicts': []
        }

        # 检查风险识别的一致性
        structure_risks = set(structure_report.get('risks', []))
        compliance_issues = {issue['type'] for issue in compliance_report.get('issues', [])}

        # 简单的一致性检查
        if structure_risks and compliance_issues:
            # 如果结构分析发现风险，合规审查应该也有问题
            if len(structure_risks) > 0 and len(compliance_issues) == 0:
                consistency['consistent'] = False
                consistency['conflicts'].append({
                    'type': 'risk_mismatch',
                    'description': '结构分析发现风险，但合规审查未发现问题'
                })

        # 检查可行性结论
        risk_feasibility = risk_report.get('feasibility', {}).get('conclusion')
        compliance_score = compliance_report.get('compliance_score', 100)

        if risk_feasibility == 'recommended' and compliance_score < 60:
            consistency['consistent'] = False
            consistency['conflicts'].append({
                'type': 'feasibility_mismatch',
                'description': '风险评估建议签署，但合规评分较低'
            })

        return consistency

    def _build_prompt(self, structure_report: Dict, compliance_report: Dict,
                     risk_report: Dict, law_validations: List, case_validations: List,
                     consistency_check: Dict) -> str:
        """构建验证提示词"""
        prompt_parts = []

        prompt_parts.append("请对以下分析结果进行交叉验证：\n")

        # 法条验证结果
        prompt_parts.append("【法条验证结果】")
        for validation in law_validations:
            law = validation['law']
            status = "✓ 有效" if validation['valid'] else "✗ 无效"
            prompt_parts.append(f"{status}: 《{law['law_name']}》第{law['article']}条")
        prompt_parts.append("")

        # 案例验证结果
        prompt_parts.append("【案例验证结果】")
        for validation in case_validations:
            status = "✓ 有效" if validation['valid'] else "✗ 无效"
            prompt_parts.append(f"{status}: {validation['case_number']}")
        prompt_parts.append("")

        # 一致性检查
        prompt_parts.append("【一致性检查】")
        if consistency_check['consistent']:
            prompt_parts.append("✓ 各Agent结论一致")
        else:
            prompt_parts.append("✗ 发现以下冲突:")
            for conflict in consistency_check['conflicts']:
                prompt_parts.append(f"  - {conflict['description']}")
        prompt_parts.append("")

        # 各Agent的核心结论
        prompt_parts.append("【各Agent核心结论】")
        prompt_parts.append(f"Agent①风险: {', '.join(structure_report.get('risks', []))}")
        prompt_parts.append(f"Agent②评分: {compliance_report.get('compliance_score', 0)}/100")
        prompt_parts.append(f"Agent③可行性: {risk_report.get('feasibility', {}).get('conclusion', 'unknown')}")

        return "\n".join(prompt_parts)

    def _extract_corrections(self, validation_text: str) -> List[Dict]:
        """提取修正建议"""
        corrections = []

        if '修正' in validation_text or '更正' in validation_text:
            lines = validation_text.split('\n')
            for line in lines:
                if line.strip().startswith('-') and ('修正' in line or '更正' in line):
                    corrections.append({
                        'text': line.strip()[1:].strip(),
                        'type': 'correction'
                    })

        return corrections
