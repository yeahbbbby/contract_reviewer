"""
本地规范库加载器 v1.7
加载和检索北京租房相关规范JSON文件

v1.7 改动:
- 新增 get_article_by_number 精准查询(按法律名+条号,返回完整原文)
- 新增 get_core_articles_for_sublease 预打包转租合同核心法条组合
- 新增 _CORE_LEGAL_FACTS 硬编码本地库缺失但必需的核心法条(民诉法 34、司法解释 28)
- 扩展 search_by_topic 主题关键词,加"管辖""争议解决"
- 倒排索引带完整法律名 + 条号中文,search 返回不再是无意义的"content"字段
"""
import json
from typing import Dict, List, Optional, Tuple
from pathlib import Path


# ============================================================
# 核心法律事实库 —— 本地 JSON 未覆盖但公认必需的基础法条
# 条文内容来自全国人大网/最高法公报,公开、稳定、不会变动
# 用途:Agent② prompt 喂料 + Agent④ 验证兜底
# ============================================================
_CORE_LEGAL_FACTS: Dict[Tuple[str, int], Dict] = {
    # 民事诉讼法(本地 JSON 里没有,但必需)
    ("民事诉讼法", 34): {
        "law_name": "中华人民共和国民事诉讼法",
        "article_number": 34,
        "article_number_cn": "第三十四条",
        "content": (
            "下列案件,由本条规定的人民法院专属管辖:"
            "(一)因不动产纠纷提起的诉讼,由不动产所在地人民法院管辖;"
            "(二)因港口作业中发生纠纷提起的诉讼,由港口所在地人民法院管辖;"
            "(三)因继承遗产纠纷提起的诉讼,由被继承人死亡时住所地或者主要遗产所在地人民法院管辖。"
        ),
        "note": "本条是专属管辖条款。房屋租赁合同纠纷依司法解释第28条按不动产纠纷确定管辖,当事人无权协议变更。",
    },
    ("民事诉讼法", 35): {
        "law_name": "中华人民共和国民事诉讼法",
        "article_number": 35,
        "article_number_cn": "第三十五条",
        "content": (
            "合同或者其他财产权益纠纷的当事人可以书面协议选择被告住所地、合同履行地、"
            "合同签订地、原告住所地、标的物所在地等与争议有实际联系的地点的人民法院管辖,"
            "但不得违反本法对级别管辖和专属管辖的规定。"
        ),
        "note": "协议管辖不得违反专属管辖。房屋租赁属专属管辖,即使双方约定也不得变更不动产所在地法院管辖的法定安排。",
    },
    # 最高法司法解释(本地 JSON 里没有)
    ("最高人民法院关于适用《中华人民共和国民事诉讼法》的解释", 28): {
        "law_name": "最高人民法院关于适用《中华人民共和国民事诉讼法》的解释",
        "article_number": 28,
        "article_number_cn": "第二十八条",
        "content": (
            "民事诉讼法第三十四条第一项规定的不动产纠纷,是指因不动产的权利确认、分割、相邻关系等引起的物权纠纷。"
            "农村土地承包经营合同纠纷、房屋租赁合同纠纷、建设工程施工合同纠纷、政策性房屋买卖合同纠纷,"
            "按照不动产纠纷确定管辖。"
            "不动产已登记的,以不动产登记簿记载的所在地为不动产所在地;"
            "不动产未登记的,以不动产实际所在地为不动产所在地。"
        ),
        "note": "这是管辖条款审查的直接依据 —— 房屋租赁合同纠纷明确按不动产纠纷专属管辖。",
    },
}


# ============================================================
# 法律名归一化表 —— 处理 LLM 引用时的各种写法变体
# ============================================================
_LAW_NAME_ALIASES: Dict[str, str] = {
    "民法典": "民法典_查询版",
    "中华人民共和国民法典": "民法典_查询版",
    "《民法典》": "民法典_查询版",
    "《中华人民共和国民法典》": "民法典_查询版",
    "北京市住房租赁条例": "北京市住房租赁条例_查询版",
    "《北京市住房租赁条例》": "北京市住房租赁条例_查询版",
    "住房租赁条例": "住房租赁条例_查询版",
    "《住房租赁条例》": "住房租赁条例_查询版",
    "北京市房屋租赁管理若干规定": "北京市房屋租赁管理若干规定_查询版",
    "商品房屋租赁管理办法": "商品房屋租赁管理办法_查询版",
    "城市房地产管理法": "城市房地产管理法_查询版",
    "担保问题司法解释": "担保问题司法解释_查询版",
    "总则编司法解释": "总则编司法解释_查询版",
    "合同通则司法解释": "合同通则司法解释_查询版",
    "最高法九民纪要": "最高法 九民纪要_查询版",
    "九民纪要": "最高法 九民纪要_查询版",
    "最高法城镇房屋租赁合同纠纷": "最高法 城镇房屋租赁合同纠纷_查询版",
    "城镇房屋租赁合同纠纷": "最高法 城镇房屋租赁合同纠纷_查询版",
    "北京市住房租赁示范合同": "北京市住房租赁示范合同_查询版",
}


def _chinese_to_arabic(s: str) -> Optional[int]:
    """
    中文数字转阿拉伯数字(支持"第七百一十六条"这种)
    仅处理 1-9999 范围,足够法律条号使用
    """
    if not s:
        return None
    s = str(s).strip().replace("第", "").replace("条", "").replace(" ", "")

    # 如果已经是阿拉伯数字,直接返回
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
                current = 1  # "十"单独出现时视为 10
            result += current * unit
            current = 0
        else:
            return None

    result += current
    return result if result > 0 else None


class RegulationLoader:
    """本地规范库加载器"""

    def __init__(self, regulations_path: str):
        self.regulations_path = Path(regulations_path)
        self.regulations = {}
        self.index = {}
        self.master_index = {}
        self._load_all()

    # ========================================================
    # 初始化:加载与索引构建
    # ========================================================
    def _load_all(self):
        """加载所有规范文件"""
        regulations_dir = self.regulations_path / "规范总集"
        if not regulations_dir.exists():
            raise FileNotFoundError(f"规范总集目录不存在: {regulations_dir}")

        for json_file in regulations_dir.glob("*.json"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    file_key = json_file.stem
                    self.regulations[file_key] = data
                    self._build_index(file_key, data)
            except Exception as e:
                print(f"加载文件失败 {json_file}: {e}")

        # 加载索引文件
        index_file = self.regulations_path / "北京租房合同审核规范索引.json"
        if index_file.exists():
            with open(index_file, 'r', encoding='utf-8') as f:
                self.master_index = json.load(f)

    def _build_index(self, file_key: str, data: Dict):
        """构建倒排索引(关键词 → [条目列表])"""
        if not isinstance(data, dict):
            return

        # 新格式:{articles: {"1": {article_number, article_number_cn, content}, ...}}
        if 'articles' in data and isinstance(data['articles'], dict):
            law_display_name = data.get('name', file_key.replace('_查询版', ''))
            for art_key, art_data in data['articles'].items():
                if not isinstance(art_data, dict):
                    continue
                content = art_data.get('content', '')
                if not content:
                    continue
                article_cn = art_data.get('article_number_cn', f'第{art_key}条')
                entry = {
                    'file': file_key,
                    'law_name': law_display_name,
                    'article': article_cn,
                    'article_number': art_data.get('article_number'),
                    'content': content,
                }
                for kw in self._extract_keywords(content):
                    self.index.setdefault(kw, []).append(entry)
            return

        # 兼容老格式
        for key, value in data.items():
            if '第' in str(key) and '条' in str(key) and isinstance(value, str):
                entry = {
                    'file': file_key,
                    'law_name': data.get('name', file_key),
                    'article': str(key),
                    'article_number': None,
                    'content': value,
                }
                for kw in self._extract_keywords(value):
                    self.index.setdefault(kw, []).append(entry)

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        """提取租赁领域关键词"""
        keywords = []
        key_terms = [
            '租金', '押金', '租期', '转租', '违约', '解除', '终止',
            '维修', '保证金', '定金', '承租人', '出租人', '次承租人',
            '房屋', '租赁', '合同', '协议', '争议', '仲裁', '诉讼',
            '管辖', '专属管辖', '不动产', '监管账户', '示范文本',
            '格式条款', '公平', '返还',
        ]
        for term in key_terms:
            if term in text:
                keywords.append(term)
        return keywords

    # ========================================================
    # 检索 API
    # ========================================================
    def search_by_keyword(self, keyword: str) -> List[Dict]:
        """按关键词检索"""
        results = []
        if keyword in self.index:
            results.extend(self.index[keyword])
        for key, items in self.index.items():
            if keyword != key and keyword in key:
                results.extend(items)

        seen = set()
        unique_results = []
        for item in results:
            key = f"{item['file']}_{item['article']}"
            if key not in seen:
                seen.add(key)
                unique_results.append(item)
        return unique_results

    def search_by_topic(self, topic: str) -> List[Dict]:
        """按主题检索,v1.7 扩展:加'管辖''争议解决'"""
        topic_keywords = {
            '转租':  ['转租', '再转租', '分租', '次承租'],
            '押金':  ['押金', '保证金', '定金', '监管账户'],
            '租金':  ['租金', '租赁费'],
            '违约':  ['违约', '违约金', '赔偿'],
            '解除':  ['解除', '终止', '提前解除'],
            '维修':  ['维修', '修缮', '保养'],
            '争议':  ['争议', '仲裁', '诉讼', '管辖'],
            '管辖':  ['管辖', '专属管辖', '不动产'],
            '格式条款': ['格式条款', '公平'],
            '返还':  ['返还'],
        }
        keywords = topic_keywords.get(topic, [topic])
        results = []
        for kw in keywords:
            results.extend(self.search_by_keyword(kw))

        seen = set()
        unique_results = []
        for item in results:
            key = f"{item['file']}_{item['article']}"
            if key not in seen:
                seen.add(key)
                unique_results.append(item)
        return unique_results

    def get_article_by_number(self, law_name: str, article_number) -> Optional[Dict]:
        """
        ⭐ v1.7 新增:按法律名 + 条号精准查询,返回完整条文

        Args:
            law_name: 法律名称(支持变体:"民法典"/"《民法典》"/"中华人民共和国民法典")
            article_number: 条号(int 或"716"或"第七百一十六条")

        Returns:
            {law_name, article_number, article_number_cn, content, source} 或 None
        """
        if isinstance(article_number, str):
            art_num = _chinese_to_arabic(article_number)
        else:
            art_num = article_number
        if art_num is None:
            return None

        # 1) 先查本地 JSON
        file_key = _LAW_NAME_ALIASES.get(law_name.strip())
        if not file_key:
            # 模糊匹配
            for alias, fk in _LAW_NAME_ALIASES.items():
                if alias in law_name or law_name in alias:
                    file_key = fk
                    break

        if file_key and file_key in self.regulations:
            data = self.regulations[file_key]
            articles = data.get('articles', {}) if isinstance(data, dict) else {}
            art_data = articles.get(str(art_num))
            if art_data and isinstance(art_data, dict):
                return {
                    'law_name': data.get('name', law_name),
                    'article_number': art_data.get('article_number', art_num),
                    'article_number_cn': art_data.get('article_number_cn', f'第{art_num}条'),
                    'content': art_data.get('content', ''),
                    'source': 'local_kb',
                }

        # 2) 兜底查核心法律事实库
        for (fact_law, fact_num), fact in _CORE_LEGAL_FACTS.items():
            if fact_num == art_num and (fact_law in law_name or law_name in fact_law):
                return {
                    'law_name': fact['law_name'],
                    'article_number': fact['article_number'],
                    'article_number_cn': fact['article_number_cn'],
                    'content': fact['content'],
                    'note': fact.get('note', ''),
                    'source': 'core_fact',
                }

        return None

    def get_core_articles_for_sublease(self) -> Dict[str, List[Dict]]:
        """
        ⭐ v1.7 新增:为转租合同审查预打包核心法条

        按争议点组织,每个主题返回该主题下应该被 Agent② 引用的核心法条全文。
        Agent② 拿到这份数据后,在 prompt 里告诉 LLM:
        "这些是已经为你检索好的核心法条,直接引用即可,不要凭记忆重构。"

        Returns:
            {
                "转租合法性与期限": [{law_name, article_number_cn, content, source}, ...],
                "争议管辖": [...],
                ...
            }
        """
        targets = {
            "转租合法性与期限": [
                ("民法典", 716),
                ("民法典", 717),
                ("民法典", 718),
                ("民法典", 719),
            ],
            "违约金调整规则": [
                ("民法典", 585),
            ],
            "维修责任划分": [
                ("民法典", 712),
                ("民法典", 713),
                ("民法典", 731),
            ],
            "租赁物返还": [
                ("民法典", 733),
            ],
            "格式条款提示义务": [
                ("民法典", 496),
                ("民法典", 497),
            ],
            "争议管辖": [
                ("民事诉讼法", 34),
                ("最高人民法院关于适用《中华人民共和国民事诉讼法》的解释", 28),
                ("民事诉讼法", 35),
            ],
        }

        out = {}
        for topic, refs in targets.items():
            items = []
            for law_name, art_num in refs:
                hit = self.get_article_by_number(law_name, art_num)
                if hit:
                    items.append(hit)
            out[topic] = items

        # 押金规范:从本地库动态抽(各地法规不同,不走硬编码)
        deposit_items = []
        seen = set()
        for topic in ['押金']:
            for result in self.search_by_topic(topic)[:8]:
                content = result.get('content', '')
                key = (result.get('law_name'), result.get('article'))
                if '押金' in content and key not in seen:
                    seen.add(key)
                    deposit_items.append({
                        'law_name': result.get('law_name', ''),
                        'article_number_cn': result.get('article', ''),
                        'content': content,
                        'source': 'local_kb',
                    })
        out["押金规范"] = deposit_items[:5]

        return out

    def get_known_legal_fact(self, law_name: str, article_number) -> Optional[Dict]:
        """
        ⭐ v1.7 新增:仅查核心法律事实库(不查本地 JSON)
        供 Agent④ 验证时作为第二级兜底使用
        """
        if isinstance(article_number, str):
            art_num = _chinese_to_arabic(article_number)
        else:
            art_num = article_number
        if art_num is None:
            return None
        for (fact_law, fact_num), fact in _CORE_LEGAL_FACTS.items():
            if fact_num == art_num and (fact_law in law_name or law_name in fact_law):
                return fact
        return None

    # ========================================================
    # 其他辅助
    # ========================================================
    def search_by_article(self, article_number: str) -> Optional[Dict]:
        """按条号(中文或阿拉伯)检索 - 旧 API 兼容"""
        if article_number in self.index:
            return self.index[article_number][0] if self.index[article_number] else None
        return None

    def get_regulation(self, file_key: str) -> Optional[Dict]:
        return self.regulations.get(file_key)

    def get_all_regulations(self) -> Dict:
        return self.regulations

    def get_statistics(self) -> Dict:
        return {
            'total_files': len(self.regulations),
            'total_indexed_items': len(self.index),
            'core_legal_facts': len(_CORE_LEGAL_FACTS),
            'files': list(self.regulations.keys()),
        }