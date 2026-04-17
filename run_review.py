#!/usr/bin/env python
"""
合同审查系统启动脚本
"""
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.parsers.document_parser import DocumentParser
from src.parsers.clause_extractor import ClauseExtractor
from src.knowledge.regulation_loader import RegulationLoader
from src.utils.weko_client import WekoMCPClient
from src.agents.agent_01_structure import Agent01Structure
from src.agents.agent_02_compliance import Agent02Compliance
from src.agents.agent_03_risk import Agent03Risk
from src.agents.agent_04_validation import Agent04Validation
from src.agents.agent_05_report import Agent05Report
import json


def main():
    print("=" * 60)
    print("北京二房东转租合同审查系统")
    print("=" * 60)

    # 1. 解析合同文档
    print("\n[步骤1] 解析合同文档...")
    contract_path = project_root / "data" / "test_contract.docx"

    if not contract_path.exists():
        print(f"错误：找不到合同文件 {contract_path}")
        return

    parser = DocumentParser()
    parsed_doc = parser.parse(str(contract_path))
    print(f"✓ 文档解析完成，共 {len(parsed_doc['sections'])} 个章节")

    # 2. 提取条款
    print("\n[步骤2] 提取关键条款...")
    extractor = ClauseExtractor()
    clauses = extractor.extract(parsed_doc)
    print(f"✓ 条款提取完成，识别 {len(clauses['clauses'])} 类条款")

    # 3. 加载本地规范库
    print("\n[步骤3] 加载本地规范库...")
    regulations_path = project_root.parent / "北京租房合同相关规范"
    regulation_loader = RegulationLoader(str(regulations_path))
    print(f"✓ 规范库加载完成")

    # 4. 连接威科先行MCP
    print("\n[步骤4] 连接威科先行MCP服务...")
    weko_client = WekoMCPClient()
    weko_client.start_session()

    # 打开威科先行首页
    print("  正在打开威科先行首页...")
    weko_client.open_home()

    # 等待用户登录
    print("  请在浏览器中登录威科先行账号...")
    print("  登录完成后，系统会自动继续（30秒超时）")
    weko_client.wait_for_login(timeout_ms=30000)  # 30秒超时
    print("✓ 威科先行MCP连接成功")

    try:
        # 5. Agent① 主体和交易结构分析
        print("\n[步骤5] Agent① 主体和交易结构分析...")
        agent01 = Agent01Structure()
        structure_report = agent01.analyze(clauses, context_info={
            "user_role": "二房东（转租方）",
            "contract_type": "房屋转租合同",
            "location": "北京市"
        })
        print("✓ 结构分析完成")
        print(f"  识别风险: {len(structure_report.get('risks', []))} 项")

        # 6. Agent② 合规审查
        print("\n[步骤6] Agent② 合规审查...")
        agent02 = Agent02Compliance()
        compliance_report = agent02.review(clauses, regulation_loader, weko_client)
        print("✓ 合规审查完成")
        print(f"  合规评分: {compliance_report.get('compliance_score', 0)}/100")
        print(f"  发现问题: {len(compliance_report.get('issues', []))} 项")

        # 7. Agent③ 风险综合研判
        print("\n[步骤7] Agent③ 风险综合研判...")
        agent03 = Agent03Risk()
        risk_report = agent03.assess(structure_report, compliance_report,
                                     regulation_loader, weko_client)
        print("✓ 风险研判完成")
        feasibility = risk_report.get('feasibility', {}).get('conclusion', 'unknown')
        print(f"  可行性结论: {feasibility}")

        # 8. Agent④ 交叉验证
        print("\n[步骤8] Agent④ 交叉验证...")
        agent04 = Agent04Validation()
        validation_report = agent04.validate(structure_report, compliance_report,
                                            risk_report, weko_client)
        print("✓ 交叉验证完成")
        print(f"  法条验证: {len(validation_report.get('law_validations', []))} 条")
        print(f"  案例验证: {len(validation_report.get('case_validations', []))} 个")

        # 9. Agent⑤ 生成审查报告
        print("\n[步骤9] Agent⑤ 生成审查报告...")
        agent05 = Agent05Report()
        all_reports = {
            'structure': structure_report,
            'compliance': compliance_report,
            'risk': risk_report,
            'validation': validation_report
        }
        final_report = agent05.generate(
            all_reports=all_reports,
            parsed_doc=parsed_doc,
            mcp_client=weko_client
        )
        print("✓ 审查报告生成完成")

        # 10. 保存结果
        print("\n[步骤10] 保存审查结果...")
        output_dir = project_root / "output"
        output_dir.mkdir(exist_ok=True)

        # 保存JSON报告
        report_path = output_dir / "review_report.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump({
                'structure': structure_report,
                'compliance': compliance_report,
                'risk': risk_report,
                'validation': validation_report,
                'final': final_report
            }, f, ensure_ascii=False, indent=2)
        print(f"✓ JSON报告已保存: {report_path}")

        # 保存文本报告
        text_report_path = output_dir / "review_report.txt"
        with open(text_report_path, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("北京二房东转租合同审查报告\n")
            f.write("=" * 60 + "\n\n")

            f.write("【Agent① 主体和交易结构分析】\n")
            f.write(structure_report.get('analysis', '') + "\n\n")

            f.write("【Agent② 合规审查】\n")
            f.write(compliance_report.get('review', '') + "\n\n")

            f.write("【Agent③ 风险综合研判】\n")
            f.write(risk_report.get('assessment', '') + "\n\n")

            f.write("【Agent④ 交叉验证】\n")
            f.write(validation_report.get('validation', '') + "\n\n")

            f.write("【Agent⑤ 最终审查意见】\n")
            f.write(final_report.get('opinion', '') + "\n\n")

        print(f"✓ 文本报告已保存: {text_report_path}")

        print("\n" + "=" * 60)
        print("审查完成！")
        print("=" * 60)
        print(f"\n报告位置: {output_dir}")
        print(f"- JSON格式: review_report.json")
        print(f"- 文本格式: review_report.txt")

    finally:
        # 关闭威科先行连接
        weko_client.stop_session()
        print("\n✓ 威科先行MCP连接已关闭")


if __name__ == "__main__":
    main()
