"""
北大法宝MCP客户端
连接北大法宝MCP服务进行法规和案例检索
"""
import requests
from typing import Dict, List, Optional
import time


class MCPClient:
    """北大法宝MCP客户端"""

    def __init__(self, base_url: str, timeout: int = 30):
        """
        初始化MCP客户端

        Args:
            base_url: MCP服务基础URL
            timeout: 请求超时时间（秒）
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.session = requests.Session()
        self.retry_times = 3
        self.retry_delay = 1

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """
        发送HTTP请求

        Args:
            method: HTTP方法
            endpoint: API端点
            **kwargs: 其他请求参数

        Returns:
            响应数据
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        for attempt in range(self.retry_times):
            try:
                response = self.session.request(
                    method,
                    url,
                    timeout=self.timeout,
                    **kwargs
                )
                response.raise_for_status()
                return response.json()

            except requests.exceptions.Timeout:
                if attempt < self.retry_times - 1:
                    time.sleep(self.retry_delay)
                    continue
                raise Exception(f"请求超时: {url}")

            except requests.exceptions.RequestException as e:
                if attempt < self.retry_times - 1:
                    time.sleep(self.retry_delay)
                    continue
                raise Exception(f"请求失败: {e}")

        raise Exception(f"请求失败，已重试{self.retry_times}次")

    def search_law(self, keyword: str, law_type: str = None, limit: int = 10) -> List[Dict]:
        """
        检索法律法规

        Args:
            keyword: 检索关键词
            law_type: 法规类型（如"法律"、"行政法规"、"地方性法规"）
            limit: 返回结果数量限制

        Returns:
            法规列表
        """
        params = {
            'keyword': keyword,
            'limit': limit
        }
        if law_type:
            params['type'] = law_type

        try:
            result = self._request('GET', '/search/law', params=params)
            return result.get('data', [])
        except Exception as e:
            print(f"法规检索失败: {e}")
            return []

    def get_regulation(self, regulation_id: str) -> Optional[Dict]:
        """
        获取法规全文

        Args:
            regulation_id: 法规ID

        Returns:
            法规详情
        """
        try:
            result = self._request('GET', f'/regulation/{regulation_id}')
            return result.get('data')
        except Exception as e:
            print(f"获取法规全文失败: {e}")
            return None

    def search_case(self, keyword: str, court: str = None, limit: int = 10) -> List[Dict]:
        """
        检索案例

        Args:
            keyword: 检索关键词
            court: 法院名称
            limit: 返回结果数量限制

        Returns:
            案例列表
        """
        params = {
            'keyword': keyword,
            'limit': limit
        }
        if court:
            params['court'] = court

        try:
            result = self._request('GET', '/search/case', params=params)
            return result.get('data', [])
        except Exception as e:
            print(f"案例检索失败: {e}")
            return []

    def get_case(self, case_id: str) -> Optional[Dict]:
        """
        获取案例详情

        Args:
            case_id: 案例ID或案号

        Returns:
            案例详情
        """
        try:
            result = self._request('GET', f'/case/{case_id}')
            return result.get('data')
        except Exception as e:
            print(f"获取案例详情失败: {e}")
            return None

    def verify_article(self, law_name: str, article_number: str) -> Optional[Dict]:
        """
        验证法条引用

        Args:
            law_name: 法律名称
            article_number: 条款号

        Returns:
            法条内容
        """
        try:
            params = {
                'law': law_name,
                'article': article_number
            }
            result = self._request('GET', '/verify/article', params=params)
            return result.get('data')
        except Exception as e:
            print(f"法条验证失败: {e}")
            return None

    def verify_case_number(self, case_number: str) -> Optional[Dict]:
        """
        验证案号真实性

        Args:
            case_number: 案号

        Returns:
            案例基本信息
        """
        try:
            params = {'case_number': case_number}
            result = self._request('GET', '/verify/case', params=params)
            return result.get('data')
        except Exception as e:
            print(f"案号验证失败: {e}")
            return None

    def search_rental_regulations(self, region: str = "北京") -> List[Dict]:
        """
        检索租赁相关法规

        Args:
            region: 地区

        Returns:
            相关法规列表
        """
        keywords = [
            f"{region}市住房租赁",
            f"{region}市房屋租赁",
            "住房租赁条例",
            "房屋租赁管理"
        ]

        results = []
        for keyword in keywords:
            laws = self.search_law(keyword, limit=5)
            results.extend(laws)

        # 去重
        seen = set()
        unique_results = []
        for item in results:
            item_id = item.get('id') or item.get('title')
            if item_id not in seen:
                seen.add(item_id)
                unique_results.append(item)

        return unique_results

    def search_sublease_cases(self, limit: int = 20) -> List[Dict]:
        """
        检索转租相关案例

        Args:
            limit: 返回结果数量限制

        Returns:
            案例列表
        """
        keywords = [
            "转租 违约",
            "次承租人 权利",
            "二房东 纠纷",
            "转租合同 效力"
        ]

        results = []
        for keyword in keywords:
            cases = self.search_case(keyword, limit=limit // len(keywords))
            results.extend(cases)

        return results

    def get_hyperlink(self, resource_type: str, resource_id: str) -> str:
        """
        生成北大法宝资源超链接

        Args:
            resource_type: 资源类型（law/case）
            resource_id: 资源ID

        Returns:
            超链接URL
        """
        return f"{self.base_url}/{resource_type}/{resource_id}"
