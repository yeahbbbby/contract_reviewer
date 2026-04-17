"""
示范文本比对模块
将提取的条款与北京市住房租赁示范合同进行比对
"""
from typing import Dict, List
from ..parsers.document_parser import DocumentParser
from ..parsers.clause_extractor import ClauseExtractor


class TemplateComparator:
    """示范文本比对器"""

    def __init__(self, template_path: str):
        """
        初始化比对器

        Args:
            template_path: 示范合同文件路径
        """
        self.template_path = template_path
        self.template_clauses = None
        self._load_template()

    def _load_template(self):
        """加载示范合同"""
        parser = DocumentParser()
        extractor = ClauseExtractor()

        # 解析示范合同
        parsed_template = parser.parse(self.template_path)
        # 提取条款
        self.template_clauses = extractor.extract(parsed_template)

    def compare(self, contract_clauses: Dict) -> Dict:
        """
        比对合同与示范文本

        Args:
            contract_clauses: 待审查合同的条款

        Returns:
            比对结果
        """
        result = {
            'missing_clauses': [],      # 缺失条款
            'different_clauses': [],    # 偏离条款
            'risky_clauses': [],        # 风险条款
            'compliant_clauses': [],    # 符合条款
            'summary': {}
        }

        # 比对各类别条款
        template_data = self.template_clauses['clauses']
        contract_data = contract_clauses['clauses']

        for category in template_data.keys():
            if category == '所有条款':
                continue

            template_cat = template_data[category]
            contract_cat = contract_data.get(category, {'found': False})

            # 检查缺失
            if template_cat.get('found') and not contract_cat.get('found'):
                result['missing_clauses'].append({
                    'category': category,
                    'template_content': template_cat.get('sections', []),
                    'severity': self._assess_severity(category)
                })

            # 检查偏离
            elif template_cat.get('found') and contract_cat.get('found'):
                diff = self._compare_content(
                    category,
                    template_cat,
                    contract_cat
                )
                if diff:
                    result['different_clauses'].append(diff)
                else:
                    result['compliant_clauses'].append(category)

        # 识别风险条款
        result['risky_clauses'] = self._identify_risks(contract_data)

        # 生成摘要
        result['summary'] = {
            'total_categories': len(template_data) - 1,  # 排除"所有条款"
            'missing_count': len(result['missing_clauses']),
            'different_count': len(result['different_clauses']),
            'risky_count': len(result['risky_clauses']),
            'compliant_count': len(result['compliant_clauses']),
            'compliance_rate': len(result['compliant_clauses']) / (len(template_data) - 1) * 100
        }

        return result

    def _compare_content(self, category: str, template: Dict, contract: Dict) -> Dict:
        """比对具体内容"""
        # 提取关键信息进行比对
        template_sections = template.get('sections', [])
        contract_sections = contract.get('sections', [])

        differences = []

        # 比对章节标题
        template_titles = {s['title'] for s in template_sections}
        contract_titles = {s['title'] for s in contract_sections}

        missing_titles = template_titles - contract_titles
        extra_titles = contract_titles - template_titles

        if missing_titles or extra_titles:
            differences.append({
                'type': 'structure',
                'missing': list(missing_titles),
                'extra': list(extra_titles)
            })

        # 比对提取的值
        template_content = template.get('content', [])
        contract_content = contract.get('content', [])

        if template_content != contract_content:
            differences.append({
                'type': 'content',
                'template': template_content,
                'contract': contract_content
            })

        if differences:
            return {
                'category': category,
                'differences': differences,
                'severity': self._assess_severity(category)
            }

        return None

    def _identify_risks(self, contract_clauses: Dict) -> List[Dict]:
        """识别风险条款"""
        risks = []

        # 风险识别规则
        risk_patterns = {
            '租金': {
                'keywords': ['一次性支付', '预付', '年付'],
                'risk_level': 'high',
                'description': '租金支付方式可能存在资金风险'
            },
            '押金': {
                'keywords': ['不退', '扣除', '没收'],
                'risk_level': 'high',
                'description': '押金条款可能存在不公平条款'
            },
            '违约责任': {
                'keywords': ['单方', '仅限', '不承担'],
                'risk_level': 'medium',
                'description': '违约责任可能不对等'
            },
            '解除条件': {
                'keywords': ['随时', '无需', '不退'],
                'risk_level': 'high',
                'description': '解除条件可能对承租方不利'
            },
            '转租条款': {
                'keywords': ['禁止', '不得', '无权'],
                'risk_level': 'critical',
                'description': '转租限制可能影响二房东权益'
            }
        }

        for category, rule in risk_patterns.items():
            clause = contract_clauses.get(category, {})
            if not clause.get('found'):
                continue

            # 检查风险关键词
            sections = clause.get('sections', [])
            for section in sections:
                content = section.get('content', '')
                for keyword in rule['keywords']:
                    if keyword in content:
                        risks.append({
                            'category': category,
                            'section': section.get('title'),
                            'content': content,
                            'keyword': keyword,
                            'risk_level': rule['risk_level'],
                            'description': rule['description']
                        })

        return risks

    def _assess_severity(self, category: str) -> str:
        """评估缺失或偏离的严重程度"""
        severity_map = {
            '主体信息': 'critical',
            '标的物': 'critical',
            '租期': 'high',
            '租金': 'high',
            '押金': 'high',
            '违约责任': 'medium',
            '解除条件': 'medium',
            '争议解决': 'low',
            '转租条款': 'critical',  # 对二房东至关重要
            '维修责任': 'medium'
        }
        return severity_map.get(category, 'low')

    def get_template_clauses(self) -> Dict:
        """获取示范合同条款"""
        return self.template_clauses

    def generate_comparison_report(self, comparison_result: Dict) -> str:
        """生成比对报告文本"""
        report = []
        report.append("=" * 50)
        report.append("示范文本比对报告")
        report.append("=" * 50)
        report.append("")

        # 摘要
        summary = comparison_result['summary']
        report.append("【比对摘要】")
        report.append(f"总类别数: {summary['total_categories']}")
        report.append(f"缺失条款: {summary['missing_count']}")
        report.append(f"偏离条款: {summary['different_count']}")
        report.append(f"风险条款: {summary['risky_count']}")
        report.append(f"符合条款: {summary['compliant_count']}")
        report.append(f"符合率: {summary['compliance_rate']:.1f}%")
        report.append("")

        # 缺失条款
        if comparison_result['missing_clauses']:
            report.append("【缺失条款】")
            for item in comparison_result['missing_clauses']:
                report.append(f"- {item['category']} (严重程度: {item['severity']})")
            report.append("")

        # 偏离条款
        if comparison_result['different_clauses']:
            report.append("【偏离条款】")
            for item in comparison_result['different_clauses']:
                report.append(f"- {item['category']} (严重程度: {item['severity']})")
                for diff in item['differences']:
                    report.append(f"  类型: {diff['type']}")
            report.append("")

        # 风险条款
        if comparison_result['risky_clauses']:
            report.append("【风险条款】")
            for item in comparison_result['risky_clauses']:
                report.append(f"- {item['category']} - {item['section']}")
                report.append(f"  风险等级: {item['risk_level']}")
                report.append(f"  说明: {item['description']}")
            report.append("")

        report.append("=" * 50)
        return "\n".join(report)
