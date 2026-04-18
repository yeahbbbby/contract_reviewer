#!/usr/bin/env python
"""
合同审查系统启动脚本(v1.5)

相对原版的改动:
  1. 登录超时 30s → 10min(可用性)
  2. 规范库路径修正(path bug 修掉)
  3. 威科首页 URL 可配(支持校园代理)
  4. 末尾新增一步:生成带修订痕迹的 .docx(红线稿)
  5. ClauseExtractor 内部走 LLM 提取(格式无关)
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 先加载 .env
load_dotenv()

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
    # v1.5 修复:原版的路径指向项目外,实际文件在 data/regulations 下
    regulations_path = project_root / "data" / "regulations" / "北京租房合同相关规范"
    regulation_loader = RegulationLoader(str(regulations_path))
    print(f"✓ 规范库加载完成")

    # 4. 连接威科先行MCP
    print("\n[步骤4] 连接威科先行MCP服务...")
    weko_client = WekoMCPClient()
    weko_client.start_session()

    # 打开威科先行首页(v1.5:支持从环境变量读校园代理 URL)
    weko_home_url = os.getenv('WEKO_HOME_URL') or None
    if weko_home_url:
        print(f"  正在打开威科先行(校园代理):{weko_home_url}")
    else:
        print("  正在打开威科先行首页...")
    weko_client.open_home(url=weko_home_url)

    # 等待用户登录(v1.5:默认 10 分钟,足够手动登录 SSO)
    login_timeout_ms = int(os.getenv('WEKO_LOGIN_TIMEOUT_MS', '600000'))
    print(f"  请在浏览器中登录(最多等 {login_timeout_ms // 1000} 秒)...")
    weko_client.wait_for_login(timeout_ms=login_timeout_ms)
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
        # validation_report = agent04.validate(structure_report, compliance_report,
        #                                     risk_report, weko_client)
        validation_report = agent04.validate(structure_report, compliance_report,
                                    risk_report, weko_client,
                                    regulation_loader=regulation_loader)
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

            # f.write("【Agent⑤ 最终审查意见】\n")
            # f.write(final_report.get('opinion', '') + "\n\n")
            f.write("【Agent⑤ 最终审查意见】\n")
            # 作者原版把意见书存为 'report_text',但读取时写成 'opinion'(bug)
            # 这里兼容两种,优先读 report_text
            f.write(final_report.get('report_text', '') or final_report.get('opinion', '') + "\n\n")

        print(f"✓ 文本报告已保存: {text_report_path}")

        # v1.5 新增:生成带修订痕迹的 .docx 红线稿
        print("\n[步骤11] 生成红线稿(带修订痕迹).docx...")
        try:
            original_md = parsed_doc.get('full_text', '')

            # 让 LLM 把 opinion 中的修订意见应用到原合同上,得到"修改后"全文
            from src.utils.llm_client import get_llm_client
            llm = get_llm_client()
            opinion_text = final_report.get('opinion', '') or final_report.get('report_text', '')

            apply_prompt = f"""你是合同修订助手。下面有两份材料:
A. 原合同全文
B. 审查意见(含逐条修订建议)

任务:
基于 A 的原文逐处应用 B 的修订建议,输出"修改后合同全文"。

核心原则(严格遵守):
1. 原文中未涉及修改的部分必须 **一字不改** 保留
2. 修改必须发生在原位,不要把原条款完整保留后在后面追加"优化版"
3. 如果 B 中没有明确说要改的内容,一律保持原样
4. 输出的是修改后的最终清洁版合同全文,不要附任何解释、注释、"修订说明"

【A. 原合同全文】
{original_md}

【B. 审查意见】
{opinion_text}

请直接输出修改后的合同全文:
"""
            revised_md = llm.analyze(prompt=apply_prompt, max_tokens=8000)

            # 调用原版在 MCP 里写好的 redline 导出工具
            redline_path = output_dir / "红线稿.docx"
            weko_client.export_redline_docx(
                file_path=str(redline_path),
                title="房屋转租合同审查(红线版)",
                original_markdown=original_md,
                revised_markdown=revised_md,
            )
            print(f"✓ 红线稿已保存: {redline_path}")
        except Exception as e:
            print(f"⚠ 红线稿生成失败: {e}")
            print("  JSON/TXT 报告仍可用,红线稿可稍后基于 opinion 手动生成")

        print("\n" + "=" * 60)
        print("审查完成！")
        print("=" * 60)
        print(f"\n报告位置: {output_dir}")
        print(f"- JSON格式: review_report.json")
        print(f"- 文本格式: review_report.txt")
        print(f"- 红线稿: 红线稿.docx")

    finally:
        # 关闭威科先行连接
        weko_client.stop_session()
        print("\n✓ 威科先行MCP连接已关闭")


if __name__ == "__main__":
    main()