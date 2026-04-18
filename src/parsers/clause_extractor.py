"""
条款提取模块(v1.5 — LLM 驱动 + 规则兜底)

相对原版的改动:
  - 原版:10 类条款靠关键词匹配 + 正则,严重依赖"第X条/押金/月租金"这种固定措辞
  - 新版:用 Qwen-Max 做语义级提取,格式无关;失败时自动降级到原规则引擎

保持不变的地方(下游 5 个 Agent 无需改动):
  - 类名 ClauseExtractor
  - 方法 extract(parsed_doc) -> Dict
  - 返回结构 {"clauses": {..10 类..}, "summary": {...}}
  - 每一类条款的 "found" / "sections" / "content" / "extracted_values" 四个字段

作者保留:10 个类别的 taxonomy 是作者沉淀的领域本体,不动。
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

from dotenv import load_dotenv

# 每次 import 都确保 .env 被加载(幂等)
load_dotenv()


# ============================================================
# 10 类条款的"语义定义"—— 领域知识,保留
# ============================================================
CLAUSE_CATEGORIES = {
    '主体信息': {
        'description': '合同双方当事人的身份信息(姓名/名称、身份证号、联系方式、地址等),以及各方在本合同中的角色(甲方/乙方/转租方/次承租人/出租方/承租方)',
        'keywords': ['出租方', '承租方', '甲方', '乙方', '转租方', '次承租人'],
    },
    '标的物': {
        'description': '租赁房屋的基本信息,包括地址、面积、户型、用途、现状、附属设施、家具家电',
        'keywords': ['房屋', '坐落', '地址', '面积', '用途'],
    },
    '租期': {
        'description': '租赁的起止日期、租赁期限、续租安排、以及本次转租期限与原租赁合同剩余期限的关系',
        'keywords': ['租赁期限', '租期', '起止日期'],
    },
    '租金': {
        'description': '月租金或年租金金额、支付周期(押一付三等)、付款日期、付款方式(银行转账/现金)、支付账户信息、租金递增/调整机制',
        'keywords': ['租金', '月租金', '年租金', '支付方式'],
    },
    '押金': {
        'description': '押金/保证金的金额、用途、退还条件、退还时间、可扣除项目、抵扣规则',
        'keywords': ['押金', '保证金', '定金'],
    },
    '违约责任': {
        'description': '任一方违约时的责任约定,包括违约情形的具体列举、违约金金额或计算方式、滞纳金/逾期利息比例、损害赔偿范围',
        'keywords': ['违约', '违约金', '赔偿', '责任'],
    },
    '解除条件': {
        'description': '合同解除或提前终止的情形、解除通知要求、解除后的处理(腾退、押金退还、费用结算)',
        'keywords': ['解除', '终止', '提前解除'],
    },
    '争议解决': {
        'description': '争议解决方式(协商/仲裁/诉讼)、管辖机构或法院、法律适用',
        'keywords': ['争议', '仲裁', '诉讼', '管辖'],
    },
    '转租条款': {
        'description': '转租权源(原房东是否同意转租)、次承租人能否再转租、分租限制、群租限制、用途限制',
        'keywords': ['转租', '再转租', '分租'],
    },
    '维修责任': {
        'description': '日常维修、自然损耗维修、乙方过错造成的损坏、主体结构维修、紧急维修、费用承担的划分',
        'keywords': ['维修', '修缮', '保养'],
    },
}


class ClauseExtractor:
    """条款提取器 —— LLM 驱动,规则兜底"""

    def __init__(self, use_llm: Optional[bool] = None):
        """
        Args:
            use_llm: 是否启用 LLM 模式
                - None(默认):有 LLM_API_KEY 就启用,没有就用规则
                - True: 强制 LLM(没配 key 会 raise)
                - False: 强制用规则模式(作者原版逻辑)
        """
        if use_llm is None:
            use_llm = bool(os.getenv('LLM_API_KEY'))
        self.use_llm = use_llm

        # 规则兜底的 patterns(从作者原版搬过来)
        self._fallback_patterns = {
            '主体信息': [
                r'(出租方|甲方|转租方)[:：](.*?)(?=承租方|乙方|$)',
                r'(承租方|乙方|次承租人)[:：](.*?)(?=\n|$)',
            ],
            '标的物': [
                r'房屋坐落[:：](.*?)(?=\n|,|,)',
                r'建筑面积[:：]?([\d.]+).*?平方米',
                r'房屋用途[:：](.*?)(?=\n|,|,)',
            ],
            '租期': [
                r'租赁期限[:：].*?(\d{4}年\d{1,2}月\d{1,2}日).*?至.*?(\d{4}年\d{1,2}月\d{1,2}日)',
                r'租期[:：].*?(\d+).*?[年月]',
            ],
            '租金': [
                r'租金[:：].*?([\d,]+).*?元',
                r'月租金[:：].*?([\d,]+).*?元',
                r'支付方式[::](.*?)(?=\n|。)',
            ],
            '押金': [
                r'押金[::].*?([\d,]+).*?元',
                r'保证金[::].*?([\d,]+).*?元',
            ],
            '违约责任': [
                r'违约金[::].*?([\d,]+).*?元',
                r'违约责任[::](.*?)(?=第|$)',
            ],
            '解除条件': [r'(提前)?解除.*?条件[::](.*?)(?=第|$)'],
            '争议解决': [
                r'争议解决[::](.*?)(?=第|$)',
                r'管辖.*?法院[::](.*?)(?=\n|。)',
            ],
            '转租条款': [r'转租[::](.*?)(?=第|$)'],
            '维修责任': [r'维修.*?责任[::](.*?)(?=第|$)'],
        }

    # ------------------------------------------------------------
    # 对外接口 —— 签名和返回结构与原版完全一致
    # ------------------------------------------------------------

    def extract(self, parsed_doc: Dict) -> Dict:
        """
        从解析后的合同中提取 10 类关键条款。

        Args:
            parsed_doc: DocumentParser.parse() 的返回,含 full_text + sections

        Returns:
            {
              "clauses": { 类别名: {found, sections, content, extracted_values}, ..., "所有条款": [...] },
              "summary": { total_categories, found_categories, missing_categories }
            }
        """
        full_text = parsed_doc.get('full_text', '')
        sections = parsed_doc.get('sections', [])

        # 主路径:走 LLM
        clauses = None
        if self.use_llm:
            try:
                clauses = self._extract_by_llm(full_text, sections)
                if clauses:
                    found_count = sum(1 for v in clauses.values() if isinstance(v, dict) and v.get('found'))
                    print(f"  ✓ LLM 提取成功,共 {found_count} 类命中")
            except Exception as e:
                print(f"  ⚠ LLM 提取失败,回退到规则模式:{e}")
                clauses = None

        # 兜底:走规则
        if clauses is None:
            print("  ℹ 使用规则模式提取")
            clauses = self._extract_by_rules(full_text, sections)

        # 补上"所有条款"(任何模式下都走结构化 sections)
        clauses['所有条款'] = self._extract_all_articles(sections)

        return {
            'clauses': clauses,
            'summary': self._generate_summary(clauses),
        }

    # ------------------------------------------------------------
    # LLM 模式
    # ------------------------------------------------------------

    def _extract_by_llm(self, full_text: str, sections: List[Dict]) -> Optional[Dict[str, Dict]]:
        """
        用 Qwen-Max 做语义级提取,返回和规则版本相同结构的 dict。
        """
        if not full_text.strip():
            return None

        # 构造 schema 说明
        categories_desc = "\n".join(
            f"  - {name}:{info['description']}"
            for name, info in CLAUSE_CATEGORIES.items()
        )

        system_prompt = (
            "你是一位合同条款提取专家。任务:从用户给的合同全文中,按给定的 10 个类别"
            "抽取相关条款的原文和关键信息。\n"
            "\n"
            "核心原则:\n"
            "1. 语义识别不依赖措辞 —— 即使合同没有用 '押金' 而写 '履约保证金',也应归到 '押金' 类\n"
            "2. 引用必须使用原文片段,不得改写\n"
            "3. 一段原文可以同时归属多个类别(比如'第八条 违约责任'同时算 '违约责任' 和 '解除条件')\n"
            "4. 只抽取合同中真实存在的信息,不要编造;找不到就如实标记 found=false\n"
        )

        user_prompt = (
            f"请从下面这份合同中抽取以下 10 类条款,返回 JSON:\n\n"
            f"【10 类条款定义】\n{categories_desc}\n\n"
            f"【合同全文】\n{full_text}\n\n"
            f"【输出格式】\n"
            f"严格输出一个 JSON 对象,键为上面 10 个类别名,值是:\n"
            f"{{\n"
            f'  "found": 布尔值,是否在合同中找到了此类条款,\n'
            f'  "excerpts": [ 原文片段字符串数组,每段不超过 500 字 ],\n'
            f'  "extracted_values": {{ 结构化关键字段,如金额、日期、百分比等 }},\n'
            f'  "notes": "你的简短说明(如有,例如「条款定义模糊」「数字需核对」)"\n'
            f"}}\n\n"
            f"只返回 JSON 本身,不要任何其他文字。"
        )

        # 调用 Qwen-Max
        from openai import OpenAI
        client = OpenAI(
            api_key=os.getenv('LLM_API_KEY'),
            base_url=os.getenv('LLM_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
        )
        resp = client.chat.completions.create(
            model=os.getenv('LLM_MODEL', 'qwen-max'),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,  # 提取任务要稳定
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or ""
        data = self._parse_json_loose(raw)
        if not isinstance(data, dict):
            return None

        # 转换为原版的结构
        result: Dict[str, Dict] = {}
        for category in CLAUSE_CATEGORIES:
            item = data.get(category, {}) or {}
            excerpts = item.get('excerpts', []) or []
            extracted = item.get('extracted_values', {}) or {}
            notes = item.get('notes', '') or ''

            # 把 excerpts 包装成作者原版期望的 sections 结构
            sections_out = []
            for exc in excerpts:
                if exc and isinstance(exc, str):
                    sections_out.append({
                        'title': f'{category}(LLM 提取)',
                        'content': exc,
                    })

            result[category] = {
                'found': bool(item.get('found')) and len(sections_out) > 0,
                'sections': sections_out,
                'content': excerpts,
                'extracted_values': extracted,
                'notes': notes,
            }

        return result

    @staticmethod
    def _parse_json_loose(raw: str) -> Optional[Dict]:
        """容错解析 JSON:处理 ```json 代码块、前后缀杂音等"""
        if not raw:
            return None
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
        if m:
            raw = m.group(1)
        start = raw.find('{')
        end = raw.rfind('}')
        if start == -1 or end == -1 or start >= end:
            return None
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------
    # 规则模式(fallback)—— 原版逻辑
    # ------------------------------------------------------------

    def _extract_by_rules(self, full_text: str, sections: List[Dict]) -> Dict[str, Dict]:
        clauses: Dict[str, Dict] = {}
        for category, info in CLAUSE_CATEGORIES.items():
            clauses[category] = self._extract_category_by_rules(
                full_text, sections, info['keywords'], self._fallback_patterns.get(category, []),
            )
        return clauses

    @staticmethod
    def _extract_category_by_rules(full_text: str, sections: List[Dict],
                                    keywords: List[str], patterns: List[str]) -> Dict:
        result = {
            'found': False,
            'content': [],
            'sections': [],
            'extracted_values': {},
        }
        for section in sections:
            title = section.get('title', '')
            if any(kw in title for kw in keywords):
                content = section.get('content', [])
                if isinstance(content, list):
                    content = '\n'.join(content)
                result['found'] = True
                result['sections'].append({'title': title, 'content': content})
        for pattern in patterns:
            try:
                matches = re.findall(pattern, full_text, re.DOTALL)
                if matches:
                    result['found'] = True
                    result['content'].extend(matches)
            except re.error:
                continue
        return result

    # ------------------------------------------------------------
    # 公共辅助(照搬原版)
    # ------------------------------------------------------------

    @staticmethod
    def _extract_all_articles(sections: List[Dict]) -> List[Dict]:
        articles = []
        for section in sections:
            title = section.get('title', '')
            if re.match(r'^第[一二三四五六七八九十百]+条|^第\d+条', title):
                content = section.get('content', [])
                if isinstance(content, list):
                    content = '\n'.join(content)
                articles.append({
                    'number': title,
                    'content': content,
                    'level': section.get('level', 1),
                })
        return articles

    @staticmethod
    def _generate_summary(clauses: Dict) -> Dict:
        summary = {
            'total_categories': len(CLAUSE_CATEGORIES),
            'found_categories': 0,
            'missing_categories': [],
        }
        for category in CLAUSE_CATEGORIES:
            data = clauses.get(category, {})
            if isinstance(data, dict) and data.get('found'):
                summary['found_categories'] += 1
            else:
                summary['missing_categories'].append(category)
        return summary