"""
测试脚本
测试合同审查系统的各个模块
"""
import os
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parsers.document_parser import DocumentParser
from src.parsers.clause_extractor import ClauseExtractor
from src.knowledge.regulation_loader import RegulationLoader


def test_document_parser():
    """测试文档解析"""
    print("\n" + "=" * 60)
    print("测试文档解析模块")
    print("=" * 60)

    parser = DocumentParser()

    # 测试文件路径
    test_file = "../北京市住房租赁合同.doc"

    if not os.path.exists(test_file):
        print(f"⚠ 测试文件不存在: {test_file}")
        return

    try:
        result = parser.parse(test_file)
        print(f"✓ 解析成功")
        print(f"  - 总段落数: {result['metadata']['total_paragraphs']}")
        print(f"  - 总章节数: {result['metadata']['total_sections']}")
        print(f"  - 前3个章节:")
        for i, section in enumerate(result['sections'][:3]):
            print(f"    {i+1}. {section['title']} (层级{section['level']})")
    except Exception as e:
        print(f"✗ 解析失败: {e}")


def test_clause_extractor():
    """测试条款提取"""
    print("\n" + "=" * 60)
    print("测试条款提取模块")
    print("=" * 60)

    parser = DocumentParser()
    extractor = ClauseExtractor()

    test_file = "../北京市住房租赁合同.doc"

    if not os.path.exists(test_file):
        print(f"⚠ 测试文件不存在: {test_file}")
        return

    try:
        parsed_doc = parser.parse(test_file)
        result = extractor.extract(parsed_doc)

        print(f"✓ 提取成功")
        print(f"  - 总类别数: {result['summary']['total_categories']}")
        print(f"  - 发现类别数: {result['summary']['found_categories']}")
        print(f"  - 缺失类别: {', '.join(result['summary']['missing_categories']) if result['summary']['missing_categories'] else '无'}")

        print(f"\n  已发现的条款类别:")
        for category, data in result['clauses'].items():
            if category != '所有条款' and data.get('found'):
                print(f"    ✓ {category}")
    except Exception as e:
        print(f"✗ 提取失败: {e}")


def test_regulation_loader():
    """测试规范库加载"""
    print("\n" + "=" * 60)
    print("测试规范库加载模块")
    print("=" * 60)

    regulations_path = "../北京租房合同相关规范"

    if not os.path.exists(regulations_path):
        print(f"⚠ 规范库目录不存在: {regulations_path}")
        return

    try:
        loader = RegulationLoader(regulations_path)
        stats = loader.get_statistics()

        print(f"✓ 加载成功")
        print(f"  - 规范文件数: {stats['total_files']}")
        print(f"  - 索引条目数: {stats['total_indexed_items']}")
        print(f"  - 文件列表: {', '.join(stats['files'][:5])}...")

        # 测试检索
        print(f"\n  测试关键词检索 '转租':")
        results = loader.search_by_keyword('转租')
        print(f"    找到 {len(results)} 条相关法规")
        if results:
            print(f"    示例: {results[0]['article']}")

        print(f"\n  测试主题检索 '押金':")
        results = loader.search_by_topic('押金')
        print(f"    找到 {len(results)} 条相关法规")

    except Exception as e:
        print(f"✗ 加载失败: {e}")


def test_full_pipeline():
    """测试完整流程"""
    print("\n" + "=" * 60)
    print("测试完整审查流程")
    print("=" * 60)

    from src.main import review_contract

    test_file = "../北京市住房租赁合同.doc"

    if not os.path.exists(test_file):
        print(f"⚠ 测试文件不存在: {test_file}")
        return

    # 检查API密钥
    if not os.getenv('ANTHROPIC_API_KEY'):
        print("⚠ 未设置ANTHROPIC_API_KEY环境变量")
        print("  请在.env文件中配置API密钥")
        return

    try:
        print("开始完整流程测试...")
        result = review_contract(
            contract_path=test_file,
            context_info={
                'role': '二房东',
                'stage': '待签',
                'concerns': ['收租安全', '清退效率']
            },
            template_path=test_file,
            output_dir='./test_output'
        )
        print(f"\n✓ 完整流程测试成功")
        print(f"  输出目录: {result['output_dir']}")
    except Exception as e:
        print(f"✗ 完整流程测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    print("\n北京二房东转租合同审查系统 - 测试套件")

    # 运行各模块测试
    test_document_parser()
    test_clause_extractor()
    test_regulation_loader()

    # 询问是否运行完整流程测试
    print("\n" + "=" * 60)
    response = input("是否运行完整流程测试？(需要API密钥) [y/N]: ")
    if response.lower() == 'y':
        test_full_pipeline()

    print("\n测试完成！")
