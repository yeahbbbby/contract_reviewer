"""
Agent② 合规审查
基于本地规范库和北大法宝进行合规性审查
"""
from typing import Dict, List
from ..utils.llm_client import get_llm_client, LLMClient


class Agent02Compliance:
    """合规审查Agent"""

    def __init__(self, llm_client: LLMClient = None):
        """
        初始化Agent

        Args:
            llm_client: LLM客户端（可选，默认使用全局客户端）
        """
        self.llm_client = llm_client or get_llm_client()

    def review(self, clauses: Dict, regulation_loader, weko_client) -> Dict:
        """
        进行合规审查

        Args:
            clauses: 提取的条款
            regulation_loader: 本地规范库加载器
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

    def _get_system_prompt(self) -> str:
        """获取系统提示词"""
        return """你是一位专业的房屋租赁合同合规审查专家，专门为二房东（转租方）提供合规性审查。

你的审查框架采用"三观四步法"：

【三观】
1. 宏观：交易可行性、主体资格、标的合法性
2. 中观：合同形式、格式条款、示范文本符合度
3. 微观：具体条款的合规性

【四步法】
1. 识别条款类型和性质
2. 匹配适用法律规范
3. 判断合规性和效力
4. 提出修改建议

重点审查内容：
- 转租合法性（是否有原房东书面同意）
- 租期合规性（不得超过原租期）
- 租金条款（支付方式、调整机制）
- 押金条款（金额限制、退还条件）
- 违约责任（是否对等、是否过高）
- 解除条件（是否合理、是否单方）
- 格式条款（是否存在不公平条款）
- 争议解决（管辖约定是否有效）

请以二房东的立场，识别：
- 效力风险（可能导致合同无效的条款）
- 履约风险（可能导致违约的条款）
- 清退风险（影响清退次承租人的条款）
- 证据风险（举证责任不利的条款）

输出格式：
【宏观审查】
【中观审查】
【微观审查】
【合规问题清单】
【法条依据】
【修改建议】
"""

    def _collect_regulations(self, clauses: Dict, regulation_loader, weko_client) -> Dict:
        """收集相关法规"""
        regulations = {
            'local': [],
            'weko_regulations': {},
            'weko_cases': {}
        }

        # 从本地规范库检索
        topics = ['转租', '租金', '押金', '违约', '解除']
        for topic in topics:
            results = regulation_loader.search_by_topic(topic)
            regulations['local'].extend(results[:3])  # 每个主题取前3条

        # 从威科先行检索法规（固定两轮）
        try:
            print("  威科先行法规检索...")
            weko_regs = weko_client.search_rental_regulations(region="北京")
            regulations['weko_regulations'] = weko_regs
        except Exception as e:
            print(f"  威科先行法规检索失败: {e}")
            print("  继续使用本地规范库...")

        # 从威科先行检索案例（按争议点）
        try:
            print("  威科先行案例检索...")
            weko_cases = weko_client.search_sublease_cases(region="北京")
            regulations['weko_cases'] = weko_cases
        except Exception as e:
            print(f"  威科先行案例检索失败: {e}")
            print("  继续使用本地规范库...")

        return regulations

    def _build_prompt(self, clauses: Dict, regulations: Dict) -> str:
        """构建审查提示词"""
        prompt_parts = []

        prompt_parts.append("请对以下转租合同进行合规审查：\n")

        # 合同条款
        prompt_parts.append("【合同条款】")
        for category, clause_data in clauses['clauses'].items():
            if category == '所有条款':
                continue
            if clause_data.get('found'):
                prompt_parts.append(f"\n{category}:")
                for section in clause_data.get('sections', []):
                    prompt_parts.append(f"  {section['title']}")
                    prompt_parts.append(f"  {section['content']}")

        prompt_parts.append("\n【适用法规】")

        # 本地规范
        if regulations['local']:
            prompt_parts.append("\n本地规范库:")
            for reg in regulations['local'][:10]:  # 限制数量
                prompt_parts.append(f"- {reg.get('article', '')}: {reg.get('content', '')[:200]}")

        # 威科先行法规检索结果
        if regulations.get('weko_regulations'):
            prompt_parts.append("\n威科先行法规检索:")
            weko_regs = regulations['weko_regulations']

            if weko_regs.get('round1'):
                prompt_parts.append("\n第一轮（租赁合同）:")
                prompt_parts.append(weko_regs['round1'].get('results', '')[:1000])

            if weko_regs.get('round2'):
                prompt_parts.append("\n第二轮（转租）:")
                prompt_parts.append(weko_regs['round2'].get('results', '')[:1000])

        # 威科先行案例检索结果
        if regulations.get('weko_cases'):
            prompt_parts.append("\n威科先行案例检索（按争议点）:")
            for dispute, case_data in regulations['weko_cases'].items():
                prompt_parts.append(f"\n争议点：{dispute}")
                prompt_parts.append(case_data.get('results', '')[:800])

        return "\n".join(prompt_parts)

    def _extract_issues(self, review_text: str) -> List[Dict]:
        """从审查文本中提取合规问题"""
        issues = []

        # 识别问题类型
        issue_patterns = {
            'validity': ['无效', '效力瑕疵', '不生效'],
            'unfair': ['不公平', '显失公平', '格式条款'],
            'illegal': ['违法', '违反', '不符合'],
            'missing': ['缺失', '未约定', '未明确'],
            'risky': ['风险', '不利', '可能导致']
        }

        for issue_type, keywords in issue_patterns.items():
            for keyword in keywords:
                if keyword in review_text:
                    issues.append({
                        'type': issue_type,
                        'keyword': keyword
                    })
                    break

        return issues

    def _calculate_score(self, review_text: str) -> int:
        """计算合规评分（0-100）"""
        # 简单的评分逻辑
        score = 100

        # 扣分项
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
