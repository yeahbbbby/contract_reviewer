"""
本地规范库加载器
加载和检索北京租房相关规范JSON文件
"""
import json
import os
from typing import Dict, List, Optional
from pathlib import Path


class RegulationLoader:
    """本地规范库加载器"""

    def __init__(self, regulations_path: str):
        """
        初始化规范库加载器

        Args:
            regulations_path: 规范库根目录路径
        """
        self.regulations_path = Path(regulations_path)
        self.regulations = {}
        self.index = {}
        self._load_all()

    def _load_all(self):
        """加载所有规范文件"""
        # 加载规范总集目录下的所有JSON文件
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
        """构建倒排索引"""
        # 提取关键词和法条号
        if isinstance(data, dict):
            for key, value in data.items():
                # 索引法条号
                if '第' in key and '条' in key:
                    if key not in self.index:
                        self.index[key] = []
                    self.index[key].append({
                        'file': file_key,
                        'article': key,
                        'content': value
                    })

                # 递归处理嵌套结构
                if isinstance(value, dict):
                    self._build_index(file_key, value)
                elif isinstance(value, str):
                    # 提取关键词
                    keywords = self._extract_keywords(value)
                    for kw in keywords:
                        if kw not in self.index:
                            self.index[kw] = []
                        self.index[kw].append({
                            'file': file_key,
                            'article': key,
                            'content': value
                        })

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        keywords = []
        # 租赁相关关键词
        key_terms = [
            '租金', '押金', '租期', '转租', '违约', '解除', '终止',
            '维修', '保证金', '定金', '承租人', '出租人', '次承租人',
            '房屋', '租赁', '合同', '协议', '争议', '仲裁', '诉讼'
        ]

        for term in key_terms:
            if term in text:
                keywords.append(term)

        return keywords

    def search_by_keyword(self, keyword: str) -> List[Dict]:
        """
        按关键词检索

        Args:
            keyword: 关键词

        Returns:
            匹配的法条列表
        """
        results = []

        # 精确匹配
        if keyword in self.index:
            results.extend(self.index[keyword])

        # 模糊匹配
        for key, items in self.index.items():
            if keyword in key:
                results.extend(items)

        # 去重
        seen = set()
        unique_results = []
        for item in results:
            key = f"{item['file']}_{item['article']}"
            if key not in seen:
                seen.add(key)
                unique_results.append(item)

        return unique_results

    def search_by_article(self, article_number: str) -> Optional[Dict]:
        """
        按法条号检索

        Args:
            article_number: 法条号（如"第10条"）

        Returns:
            法条内容
        """
        if article_number in self.index:
            return self.index[article_number][0] if self.index[article_number] else None
        return None

    def get_regulation(self, file_key: str) -> Optional[Dict]:
        """
        获取完整规范文件

        Args:
            file_key: 文件名（不含扩展名）

        Returns:
            规范内容
        """
        return self.regulations.get(file_key)

    def search_by_topic(self, topic: str) -> List[Dict]:
        """
        按主题检索

        Args:
            topic: 主题（如"转租"、"押金"）

        Returns:
            相关法条列表
        """
        # 主题关键词映射
        topic_keywords = {
            '转租': ['转租', '再转租', '分租', '次承租'],
            '押金': ['押金', '保证金', '定金'],
            '租金': ['租金', '租赁费', '支付'],
            '违约': ['违约', '违约金', '赔偿', '责任'],
            '解除': ['解除', '终止', '提前解除'],
            '维修': ['维修', '修缮', '保养'],
            '争议': ['争议', '仲裁', '诉讼', '管辖'],
        }

        keywords = topic_keywords.get(topic, [topic])
        results = []

        for kw in keywords:
            results.extend(self.search_by_keyword(kw))

        # 去重
        seen = set()
        unique_results = []
        for item in results:
            key = f"{item['file']}_{item['article']}"
            if key not in seen:
                seen.add(key)
                unique_results.append(item)

        return unique_results

    def get_all_regulations(self) -> Dict:
        """获取所有规范"""
        return self.regulations

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        return {
            'total_files': len(self.regulations),
            'total_indexed_items': len(self.index),
            'files': list(self.regulations.keys())
        }
