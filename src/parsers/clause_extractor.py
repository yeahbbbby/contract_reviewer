"""
条款提取模块
从解析后的文档中提取和分类关键条款
"""
import re
from typing import Dict, List, Optional


class ClauseExtractor:
    """条款提取器"""

    def __init__(self):
        # 关键条款识别模式
        self.patterns = {
            '主体信息': {
                'keywords': ['出租方', '承租方', '甲方', '乙方', '转租方', '次承租人'],
                'patterns': [
                    r'(出租方|甲方|转租方)[：:](.*?)(?=承租方|乙方|$)',
                    r'(承租方|乙方|次承租人)[：:](.*?)(?=\n|$)',
                ]
            },
            '标的物': {
                'keywords': ['房屋', '坐落', '地址', '面积', '用途'],
                'patterns': [
                    r'房屋坐落[：:](.*?)(?=\n|，)',
                    r'建筑面积[：:]?([\d.]+).*?平方米',
                    r'房屋用途[：:](.*?)(?=\n|，)',
                ]
            },
            '租期': {
                'keywords': ['租赁期限', '租期', '起止日期'],
                'patterns': [
                    r'租赁期限[：:].*?(\d{4}年\d{1,2}月\d{1,2}日).*?至.*?(\d{4}年\d{1,2}月\d{1,2}日)',
                    r'租期[：:].*?(\d+).*?[年月]',
                ]
            },
            '租金': {
                'keywords': ['租金', '月租金', '年租金', '支付方式'],
                'patterns': [
                    r'租金[：:].*?([\d,]+).*?元',
                    r'月租金[：:].*?([\d,]+).*?元',
                    r'支付方式[：:](.*?)(?=\n|。)',
                ]
            },
            '押金': {
                'keywords': ['押金', '保证金', '定金'],
                'patterns': [
                    r'押金[：:].*?([\d,]+).*?元',
                    r'保证金[：:].*?([\d,]+).*?元',
                ]
            },
            '违约责任': {
                'keywords': ['违约', '违约金', '赔偿', '责任'],
                'patterns': [
                    r'违约金[：:].*?([\d,]+).*?元',
                    r'违约责任[：:](.*?)(?=第|$)',
                ]
            },
            '解除条件': {
                'keywords': ['解除', '终止', '提前解除'],
                'patterns': [
                    r'(提前)?解除.*?条件[：:](.*?)(?=第|$)',
                ]
            },
            '争议解决': {
                'keywords': ['争议', '仲裁', '诉讼', '管辖'],
                'patterns': [
                    r'争议解决[：:](.*?)(?=第|$)',
                    r'管辖.*?法院[：:](.*?)(?=\n|。)',
                ]
            },
            '转租条款': {
                'keywords': ['转租', '再转租', '分租'],
                'patterns': [
                    r'转租[：:](.*?)(?=第|$)',
                ]
            },
            '维修责任': {
                'keywords': ['维修', '修缮', '保养'],
                'patterns': [
                    r'维修.*?责任[：:](.*?)(?=第|$)',
                ]
            },
        }

    def extract(self, parsed_doc: Dict) -> Dict:
        """
        提取条款

        Args:
            parsed_doc: 解析后的文档

        Returns:
            提取的条款字典
        """
        full_text = parsed_doc['full_text']
        sections = parsed_doc['sections']

        clauses = {}

        # 按类别提取
        for category, config in self.patterns.items():
            clauses[category] = self._extract_category(
                full_text,
                sections,
                config
            )

        # 提取所有条款编号
        clauses['所有条款'] = self._extract_all_articles(sections)

        return {
            'clauses': clauses,
            'summary': self._generate_summary(clauses)
        }

    def _extract_category(self, full_text: str, sections: List[Dict], config: Dict) -> Dict:
        """提取特定类别的条款"""
        result = {
            'found': False,
            'content': [],
            'sections': [],
            'extracted_values': {}
        }

        # 关键词匹配章节
        for section in sections:
            title = section['title']
            content_text = '\n'.join(section['content'])

            # 检查标题是否包含关键词
            if any(kw in title for kw in config['keywords']):
                result['found'] = True
                result['sections'].append({
                    'title': title,
                    'content': content_text
                })

        # 正则提取具体值
        for pattern in config['patterns']:
            matches = re.findall(pattern, full_text, re.DOTALL)
            if matches:
                result['found'] = True
                result['content'].extend(matches)

        return result

    def _extract_all_articles(self, sections: List[Dict]) -> List[Dict]:
        """提取所有条款"""
        articles = []

        for section in sections:
            if re.match(r'^第[一二三四五六七八九十百]+条|^第\d+条', section['title']):
                articles.append({
                    'number': section['title'],
                    'content': '\n'.join(section['content']),
                    'level': section['level']
                })

        return articles

    def _generate_summary(self, clauses: Dict) -> Dict:
        """生成摘要"""
        summary = {
            'total_categories': len(clauses),
            'found_categories': sum(1 for c in clauses.values() if isinstance(c, dict) and c.get('found')),
            'missing_categories': []
        }

        for category, data in clauses.items():
            if isinstance(data, dict) and not data.get('found'):
                summary['missing_categories'].append(category)

        return summary
