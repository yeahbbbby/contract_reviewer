"""
主程序
编排整个合同审查流程
"""
import os
from pathlib import Path
from dotenv import load_dotenv

from src.parsers.document_parser import DocumentParser
from src.parsers.clause_extractor import ClauseExtractor
from src.comparators.template_comparator import TemplateComparator
from src.knowledge.regulation_loader import RegulationLoader
from src.utils.mcp_client import MCPClient
from src.agents.agent_01_structure import Agent01Structure
from src.agents.agent_02_compliance import Agent02Compliance
from src.agents.agent_03_risk import Agent03Risk
from src.agents.agent_04_validation import Agent04Validation
from src.agents.agent_05_report import Agent05Report
from src.utils.docx_redline import DocxRedline


def review_contract(contract_path: str, context_info: dict = None,
                   template_path: str = None, output_dir: str = None) -> dict:
    """
    审查合同主流程

    Args:
        contract_path: 待审查合同路径
        context_info: 背景信息（角色、阶段、关注点等）
        template_path: 示范合同路径
        output_dir: 输出目录

    Returns:
        审查结果
    """
    # 加载配置
    load_dotenv()

    # 设置默认值
    if context_info is None:
        context_info = {
            'role': '二房东',
            'stage': '待签',
            'concerns': ['收租安全', '清退效率']
        }

    if output_dir is None:
        output_dir = './output'
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("北京二房东转租合同审查系统")
    print("=" * 60)
    print()

    # Step 1: 文档解析
    print("Step 1: 解析合同文档...")
    parser = DocumentParser()
    parsed_doc = parser.parse(contract_path)
    print(f"  ✓ 解析完成: {parsed_doc['metadata']['total_paragraphs']}段落, "
          f"{parsed_doc['metadata']['total_sections']}章节")
    print()

    # Step 2: 条款提取
    print("Step 2: 提取合同条款...")
    extractor = ClauseExtractor()
    clauses = extractor.extract(parsed_doc)
    print(f"  ✓ 提取完成: 发现{clauses['summary']['found_categories']}类条款")
    if clauses['summary']['missing_categories']:
        print(f"  ⚠ 缺失条款: {', '.join(clauses['summary']['missing_categories'])}")
    print()

    # Step 3: 示范文本比对
    comparison_result = None
    if template_path and os.path.exists(template_path):
        print("Step 3: 示范文本比对...")
        comparator = TemplateComparator(template_path)
        comparison_result = comparator.compare(clauses)
        print(f"  ✓ 比对完成: 符合率{comparison_result['summary']['compliance_rate']:.1f}%")
        print(f"  - 缺失条款: {comparison_result['summary']['missing_count']}项")
        print(f"  - 偏离条款: {comparison_result['summary']['different_count']}项")
        print(f"  - 风险条款: {comparison_result['summary']['risky_count']}项")
        print()

    # Step 4: 初始化知识库和MCP客户端
    print("Step 4: 加载知识库...")
    regulations_path = os.getenv('REGULATIONS_PATH', '../北京租房合同相关规范')
    regulation_loader = RegulationLoader(regulations_path)
    stats = regulation_loader.get_statistics()
    print(f"  ✓ 加载完成: {stats['total_files']}个规范文件, "
          f"{stats['total_indexed_items']}条索引")
    print()

    print("Step 5: 连接北大法宝MCP...")
    mcp_url = os.getenv('PKULAW_MCP_URL', 'https://mcp.pkulaw.com/apis')
    mcp_client = MCPClient(mcp_url)
    print(f"  ✓ 连接成功: {mcp_url}")
    print()

    # Step 6: Agent① 主体+交易结构分析
    print("Step 6: Agent① 主体+交易结构分析...")
    agent01 = Agent01Structure()
    structure_report = agent01.analyze(clauses, context_info)
    print(f"  ✓ 分析完成: 识别{len(structure_report['risks'])}个风险点")
    print()

    # Step 7: Agent② 合规审查
    print("Step 7: Agent② 合规审查...")
    agent02 = Agent02Compliance()
    compliance_report = agent02.review(clauses, regulation_loader, mcp_client)
    print(f"  ✓ 审查完成: 合规评分{compliance_report['compliance_score']}/100")
    print(f"  - 发现问题: {len(compliance_report['issues'])}项")
    print()

    # Step 8: Agent③ 风险综合研判
    print("Step 8: Agent③ 风险综合研判...")
    agent03 = Agent03Risk()
    risk_report = agent03.assess(structure_report, compliance_report,
                                 regulation_loader, mcp_client)
    feasibility = risk_report['feasibility']['conclusion']
    print(f"  ✓ 研判完成: 可行性结论 - {feasibility}")
    risk_matrix = risk_report['risk_matrix']
    print(f"  - 红线风险: {len(risk_matrix.get('red_line', []))}项")
    print(f"  - 高风险: {len(risk_matrix.get('high', []))}项")
    print(f"  - 中风险: {len(risk_matrix.get('medium', []))}项")
    print()

    # Step 9: Agent④ 交叉验证
    print("Step 9: Agent④ 交叉验证...")
    agent04 = Agent04Validation()
    validation_report = agent04.validate(structure_report, compliance_report,
                                        risk_report, mcp_client)
    print(f"  ✓ 验证完成")
    print(f"  - 法条验证: {len(validation_report['law_validations'])}条")
    print(f"  - 案例验证: {len(validation_report['case_validations'])}个")
    consistency = validation_report['consistency_check']
    print(f"  - 一致性: {'✓ 通过' if consistency['consistent'] else '✗ 发现冲突'}")
    print()

    # Step 10: Agent⑤ 意见书生成
    print("Step 10: Agent⑤ 生成审查报告...")
    agent05 = Agent05Report()
    all_reports = {
        'structure': structure_report,
        'compliance': compliance_report,
        'risk': risk_report,
        'validation': validation_report
    }
    final_report = agent05.generate(all_reports, parsed_doc, mcp_client,
                                    comparison_result)
    print(f"  ✓ 报告生成完成")
    print(f"  - 修改建议: {len(final_report['modifications'])}项")
    print()

    # Step 11: 生成输出文件
    print("Step 11: 生成输出文件...")

    # 保存文本报告
    report_path = os.path.join(output_dir, '审查意见书.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(final_report['report_text'])
    print(f"  ✓ 审查意见书: {report_path}")

    # 生成Word红线版本
    if contract_path.endswith('.docx') or contract_path.endswith('.doc'):
        redline_path = os.path.join(output_dir, '合同_红线修订版.docx')
        redline = DocxRedline(contract_path)
        redline.generate_redline_from_report(final_report, redline_path)
        print(f"  ✓ 红线修订版: {redline_path}")

    # 保存比对报告
    if comparison_result:
        comparison_path = os.path.join(output_dir, '示范文本比对报告.txt')
        comparator_report = comparator.generate_comparison_report(comparison_result)
        with open(comparison_path, 'w', encoding='utf-8') as f:
            f.write(comparator_report)
        print(f"  ✓ 比对报告: {comparison_path}")

    print()
    print("=" * 60)
    print("审查完成！")
    print("=" * 60)

    return {
        'parsed_doc': parsed_doc,
        'clauses': clauses,
        'comparison': comparison_result,
        'reports': all_reports,
        'final_report': final_report,
        'output_dir': output_dir
    }


if __name__ == '__main__':
    # 示例用法
    result = review_contract(
        contract_path='北京市住房租赁合同.doc',
        context_info={
            'role': '二房东',
            'stage': '待签',
            'concerns': ['收租安全', '清退效率', '责任边界']
        },
        template_path='北京市住房租赁合同.doc',
        output_dir='./output'
    )
