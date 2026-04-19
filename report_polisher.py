"""
ReportPolisher v1.7.2 —— 报告可读性加工器(两层嵌套 + 三观四步法对齐)

定位:在原 Agent①~⑤ 流水线跑完之后,作为独立后处理步骤,
将 review_report.json + review_report.txt 重新加工成一份"律师友好"的最终报告。

v1.7.2 架构重构(相对 v1.7.1):
- 从"六章倒金字塔"改为"两层嵌套",以契合项目的三观四步法理论骨架
- 第一部分(用户视角,4 章):执行摘要、风险仪表盘、行动清单、条款对照
- 第二部分(三观四步法过程透明,4 章):沟通需求、三观分析、复核、提交
- 每个 Agent 产出映射到三观四步法的相应步骤,让用户看到审查流程与理论框架的对应

设计原则:
1. 不触碰现有 Agent 流水线 —— 只做"加工",不做"重新分析"
2. LLM 角色 = 编辑,不是作者 —— 只重组素材,不添加新观点
3. 两层嵌套 —— 第一层结论用户看,第二层过程律师/合规审计看
4. 三观四步法对齐 —— 过程层严格按项目的理论骨架组织
5. 分段生成 —— 8 个章节分别调用,避免 LLM 长文质量衰减
6. 白名单/黑名单显式约束 —— 引用必须来自 Agent④ 已核实
7. 每节"三要素":输入 → 依据 → 产出,便于追溯

使用方式:
    python -m src.postprocess.report_polisher
    # 或
    from src.postprocess.report_polisher import ReportPolisher
    polisher = ReportPolisher(output_dir="output")
    polisher.polish()

    # 调试某一章节(省 token)
    python -m src.postprocess.report_polisher --sections executive_summary
    python -m src.postprocess.report_polisher --sections step2_three_perspectives

输出:
    output/review_report_精装版.md  —— 两层嵌套的最终报告
    output/polish_log.json         —— 加工日志

运行时长:约 3-5 分钟(8 段 LLM 调用)
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# ==================================================================
# 允许 python -m src.postprocess.report_polisher 与
# python src/postprocess/report_polisher.py 两种运行方式
# ==================================================================
try:
    from ..utils.llm_client import get_llm_client, LLMClient
except ImportError:
    _here = Path(__file__).resolve().parent
    project_root = _here.parent.parent
    sys.path.insert(0, str(project_root))
    from src.utils.llm_client import get_llm_client, LLMClient


# ==================================================================
# 报告模板:两层结构,共 8 个章节 + 附录
# 第一部分(用户视角):4 章
# 第二部分(三观四步法过程透明):4 章
# ==================================================================
SECTION_TEMPLATES = {
    # ============ 第一部分 · 用户视角 ============
    'executive_summary': {
        'title': '一、执行摘要',
        'layer': '第一部分 · 用户视角的整体结果',
        'purpose': '10 秒读完:告诉用户能不能签、关键理由、补救方向',
        'max_tokens': 800,
    },
    'risk_dashboard': {
        'title': '二、风险仪表盘',
        'layer': '第一部分 · 用户视角的整体结果',
        'purpose': '30 秒读完:按风险等级汇总全部风险,一表看全',
        'max_tokens': 1200,
    },
    'action_checklist': {
        'title': '三、三阶段行动清单',
        'layer': '第一部分 · 用户视角的整体结果',
        'purpose': '3 分钟读完:按签约前/时/后时间线给出可勾选动作',
        'max_tokens': 2000,
    },
    'clause_revision': {
        'title': '四、条款修改对照表',
        'layer': '第一部分 · 用户视角的整体结果',
        'purpose': '10 分钟读完:律师工作台,原条款 → 问题 → 建议改法',
        'max_tokens': 3000,
    },

    # ============ 第二部分 · 三观四步法过程透明 ============
    'step1_communication': {
        'title': '五、第一步 · 沟通需求',
        'layer': '第二部分 · 依三观四步法的过程透明',
        'purpose': '展示 Agent① 如何理解交易背景、主体、结构,形成初步画像',
        'max_tokens': 1800,
    },
    'step2_three_perspectives': {
        'title': '六、第二步 · 三观分析',
        'layer': '第二部分 · 依三观四步法的过程透明',
        'purpose': '按宏观/中观/微观三层展示 Agent② 检索了什么、Agent③ 如何综合研判',
        'max_tokens': 4000,  # 这一节最长,要覆盖三观 + Agent③
    },
    'step3_review': {
        'title': '七、第三步 · 复核',
        'layer': '第二部分 · 依三观四步法的过程透明',
        'purpose': '展示 Agent④ 对法条和案号的核实过程,白名单/黑名单/一致性',
        'max_tokens': 2000,
    },
    'step4_submission': {
        'title': '八、第四步 · 提交',
        'layer': '第二部分 · 依三观四步法的过程透明',
        'purpose': '最终审查意见 + 法律依据全集 + 参考案例 + 免责声明',
        'max_tokens': 3000,
    },
}


class ReportPolisher:
    """报告可读性加工器(两层嵌套 · 三观四步法对齐)"""

    def __init__(self, output_dir: str = None, llm_client: LLMClient = None):
        if output_dir is None:
            output_dir = Path(__file__).resolve().parent / "output"
        self.output_dir = Path(output_dir)
        self.llm = llm_client or get_llm_client()
        self.raw_data: Dict = {}
        self.polish_log: Dict = {
            'started_at': datetime.now().isoformat(),
            'version': 'v1.7.2',
            'architecture': 'two_layer_aligned_with_three_perspectives_four_steps',
            'sections': {},
        }

    # ==============================================================
    # 主入口
    # ==============================================================
    def polish(self) -> str:
        print("=" * 64)
        print("ReportPolisher v1.7.2 · 两层结构 · 对齐三观四步法")
        print("=" * 64)

        print("\n[1/4] 读取原始报告...")
        self._load_raw_data()
        print(f"✓ JSON 字段:{list(self.raw_data.get('json', {}).keys())}")
        print(f"✓ txt 长度:{len(self.raw_data.get('txt', ''))} 字符")

        print("\n[2/4] 提取核心素材...")
        materials = self._extract_materials()
        print(f"✓ 合规评分:{materials['meta']['compliance_score']}")
        print(f"✓ 可行性:{materials['meta']['feasibility']}")
        print(f"✓ 白名单法条 {len(materials['whitelist']['laws'])} 条 / 案号 {len(materials['whitelist']['cases'])} 个")
        print(f"✓ 黑名单法条 {len(materials['blacklist']['laws'])} 条 / 案号 {len(materials['blacklist']['cases'])} 个")
        print(f"✓ 核心法条(已按争议点分组){len(materials['core_articles'])} 条")

        print("\n[3/4] 分段调用 LLM 重组内容(8 章节)...")
        sections = {}
        for section_id in SECTION_TEMPLATES.keys():
            tpl = SECTION_TEMPLATES[section_id]
            print(f"  → [{tpl['layer'].split('·')[0].strip()}] {tpl['title']}")
            start = time.time()
            content = self._generate_section(section_id, materials)
            sections[section_id] = content
            elapsed = time.time() - start
            print(f"    ✓ 完成 ({elapsed:.1f}s, {len(content)} 字符)")

        print("\n[4/4] 拼装最终报告...")
        final_md = self._assemble_markdown(sections, materials)
        md_path = self.output_dir / "review_report_精装版.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(final_md)
        print(f"✓ 精装版报告已保存:{md_path}")

        self.polish_log['finished_at'] = datetime.now().isoformat()
        log_path = self.output_dir / "polish_log.json"
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(self.polish_log, f, ensure_ascii=False, indent=2)
        print(f"✓ 加工日志已保存:{log_path}")

        print("\n" + "=" * 64)
        print("加工完成")
        print("=" * 64)
        print(f"\n用户阅读:{md_path}")

        return str(md_path)

    # ==============================================================
    # 数据加载
    # ==============================================================
    def _load_raw_data(self):
        json_path = self.output_dir / "review_report.json"
        txt_path = self.output_dir / "review_report.txt"
        if not json_path.exists():
            raise FileNotFoundError(f"未找到 {json_path},请先运行 run_review.py")
        if not txt_path.exists():
            raise FileNotFoundError(f"未找到 {txt_path},请先运行 run_review.py")
        with open(json_path, 'r', encoding='utf-8') as f:
            self.raw_data['json'] = json.load(f)
        with open(txt_path, 'r', encoding='utf-8') as f:
            self.raw_data['txt'] = f.read()

    # ==============================================================
    # 素材提取
    # ==============================================================
    def _extract_materials(self) -> Dict:
        j = self.raw_data.get('json', {})
        txt = self.raw_data.get('txt', '')

        structure = j.get('structure', {})
        compliance = j.get('compliance', {})
        risk = j.get('risk', {})
        validation = j.get('validation', {})
        final = j.get('final', {})

        meta = {
            'compliance_score': compliance.get('compliance_score', 'N/A'),
            'feasibility': risk.get('feasibility', {}).get('conclusion', 'unknown'),
            'generated_at': final.get('generated_at', datetime.now().isoformat()),
        }

        narratives = self._split_narratives(txt)

        whitelist = validation.get('whitelist', {'laws': [], 'cases': []})
        blacklist = validation.get('blacklist', {'laws': [], 'cases': []})
        if not whitelist.get('laws') and not blacklist.get('laws'):
            whitelist, blacklist = self._derive_lists_from_v17(validation)

        core_articles = self._extract_core_articles(compliance)

        # v1.7.2 新增:按三观(宏观/中观/微观)把 core_articles 分组
        core_by_perspective = self._group_core_by_perspective(core_articles)

        # 威科检索的调用记录(如有)
        weko_calls = self._extract_weko_calls(compliance)

        return {
            'meta': meta,
            'narratives': narratives,
            'whitelist': whitelist,
            'blacklist': blacklist,
            'core_articles': core_articles,
            'core_by_perspective': core_by_perspective,
            'weko_calls': weko_calls,
            'issues': compliance.get('issues', []),
            'risk_matrix': risk.get('risk_matrix', {}),
        }

    def _split_narratives(self, txt: str) -> Dict[str, str]:
        markers = [
            ('structure',  '【Agent① 主体和交易结构分析】'),
            ('compliance', '【Agent② 合规审查】'),
            ('risk',       '【Agent③ 风险综合研判】'),
            ('validation', '【Agent④ 交叉验证】'),
            ('final',      '【Agent⑤ 最终审查意见】'),
        ]
        sections = {}
        for i, (key, marker) in enumerate(markers):
            if marker not in txt:
                sections[key] = ''
                continue
            start = txt.index(marker) + len(marker)
            if i + 1 < len(markers) and markers[i + 1][1] in txt:
                end = txt.index(markers[i + 1][1])
            else:
                end = len(txt)
            sections[key] = txt[start:end].strip()
        return sections

    def _extract_core_articles(self, compliance: Dict) -> List[Dict]:
        items = []
        regs = compliance.get('regulations_used', {})
        core = regs.get('core_articles', {})
        if isinstance(core, dict):
            for topic, arts in core.items():
                for a in (arts or []):
                    items.append({
                        'topic': topic,
                        'law_name': a.get('law_name', ''),
                        'article_number_cn': a.get('article_number_cn', ''),
                        'article_number': a.get('article_number'),
                        'content': a.get('content', ''),
                        'source': a.get('source', ''),
                    })
        return items

    def _group_core_by_perspective(self, core_articles: List[Dict]) -> Dict[str, List[Dict]]:
        """
        v1.7.2 新增:按三观(宏观/中观/微观)把 core_articles 分组
        利用架构文档第二部分的主题→三观映射
        """
        # 主题 → 三观的映射(基于规范索引文档第二部分)
        perspective_map = {
            # 宏观(交易结构):主体、标的、程序、交易结构
            '转租合法性与期限': 'macro',  # 涉及交易结构
            # 中观(合同形式):书面、格式条款、示范文本
            '格式条款提示义务': 'meso',
            # 微观(合同条款):租金、押金、维修、违约、解除、争议
            '押金规范': 'micro',
            '违约金调整规则': 'micro',
            '维修责任划分': 'micro',
            '租赁物返还': 'micro',
            '争议管辖': 'micro',
        }

        result = {'macro': [], 'meso': [], 'micro': [], 'unassigned': []}
        for art in core_articles:
            topic = art.get('topic', '')
            perspective = perspective_map.get(topic)
            if perspective:
                result[perspective].append(art)
            else:
                result['unassigned'].append(art)
        return result

    def _extract_weko_calls(self, compliance: Dict) -> Dict:
        """提取威科检索调用记录"""
        regs = compliance.get('regulations_used', {}) or {}
        return {
            'weko_regulations': bool(regs.get('weko_regulations')),
            'weko_cases_count': len((regs.get('weko_cases') or {})),
        }

    def _derive_lists_from_v17(self, validation: Dict) -> (Dict, Dict):
        """兼容 v1.7 Agent④(无 whitelist/blacklist 字段)"""
        whitelist = {'laws': [], 'cases': []}
        blacklist = {'laws': [], 'cases': []}

        for v in validation.get('law_validations', []):
            law = v.get('law', {})
            entry = {
                'law_name': law.get('law_name', ''),
                'article': str(law.get('article', '')),
                'source': v.get('source', ''),
                'raw_pattern': f"《{law.get('law_name','')}》第{law.get('article','')}条",
            }
            if v.get('valid'):
                whitelist['laws'].append(entry)
            else:
                entry['reason'] = v.get('evidence', '未通过验证')
                blacklist['laws'].append(entry)

        for v in validation.get('case_validations', []):
            entry = {
                'case_number': v.get('case_number', ''),
                'source': v.get('source', ''),
            }
            if v.get('valid'):
                whitelist['cases'].append(entry)
            else:
                entry['reason'] = v.get('reason', '未在威科核实')
                blacklist['cases'].append(entry)

        return whitelist, blacklist

    # ==============================================================
    # LLM 调用:分段生成
    # ==============================================================
    def _generate_section(self, section_id: str, materials: Dict) -> str:
        template = SECTION_TEMPLATES[section_id]
        system_prompt = self._build_system_prompt(section_id, template)
        user_prompt = self._build_user_prompt(section_id, materials)

        try:
            result = self.llm.analyze(
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=template['max_tokens'],
            )
        except Exception as e:
            result = f"[本节生成失败:{e}]\n\n原始素材预览:\n{user_prompt[:500]}..."

        self.polish_log['sections'][section_id] = {
            'title': template['title'],
            'layer': template['layer'],
            'system_prompt_len': len(system_prompt),
            'user_prompt_len': len(user_prompt),
            'output_len': len(result),
            'output_preview': result[:200],
        }
        return result

    # ==============================================================
    # System Prompt
    # ==============================================================
    def _build_system_prompt(self, section_id: str, template: Dict) -> str:
        # 通用部分
        base = f"""你是一位资深法律文书编辑,不是作者。

你正在编辑一份已经分析完毕的房屋转租合同审查报告,该报告由基于"三观四步法"
(《合同起草审查指南》,何力等著,法律出版社 2024 年第 5 版)的多 Agent 流水线产出。

【整体报告结构】
报告分两层:
- 第一部分(用户视角):执行摘要、风险仪表盘、行动清单、条款对照
- 第二部分(三观四步法过程透明):第一步沟通需求、第二步三观分析、第三步复核、第四步提交

【当前章节】{template['title']}
【本章所属层】{template['layer']}
【本章目的】{template['purpose']}

【你的行为准则】
1. 只使用用户提示词中提供的素材,不要发挥、不要补充、不要引入外部知识
2. 不要引用任何未在素材中明确出现的法条、案号、规章号、百分比数字
3. 如果素材里信息不足,直接说"本节信息不足,建议补充",不要编造
4. 写作立场:严格中立,站在"为二房东提供客观风险提示"的专业顾问角度
5. 语言风格:简练、专业、可操作,避免情绪化表述
6. 格式要求:Markdown,使用表格、列表、加粗突出重点

【硬性约束】
- 禁止出现具体 LPR 百分比数字(如 "14.8%" "18.25%")
- 禁止自行扩写未经核实的案号细节(如"该案裁判要旨为...")
- 引用法条必须来自素材中的【法条白名单】
- 引用案号必须来自素材中的【案号白名单】
- 管辖条款引用:《民诉法》第 34 条 + 司法解释第 28 条,不得引用第 24 条
"""
        specific = SECTION_SPECIFIC_GUIDES.get(section_id, '')
        if specific:
            base += f"\n【本章具体要求】\n{specific}\n"
        return base

    # ==============================================================
    # User Prompt
    # ==============================================================
    def _build_user_prompt(self, section_id: str, materials: Dict) -> str:
        meta = materials['meta']
        wl = materials['whitelist']
        bl = materials['blacklist']

        parts = [f"# 输入素材(供 {SECTION_TEMPLATES[section_id]['title']} 使用)\n"]

        # 元信息
        parts.append("## 基本结论(来自原始 Agent 流水线)")
        parts.append(f"- 合规评分:{meta['compliance_score']}/100")
        parts.append(f"- 可行性:{meta['feasibility']}")
        parts.append("")

        # 白名单
        parts.append("## 可引用的法条(白名单)")
        if wl.get('laws'):
            for e in wl['laws'][:25]:
                parts.append(f"- 《{e.get('law_name','')}》第{e.get('article','')}条  [来源:{e.get('source','')}]")
        else:
            parts.append("- (无,本章请不要引用具体法条编号)")
        parts.append("")

        parts.append("## 可引用的案号(白名单)")
        if wl.get('cases'):
            for e in wl['cases'][:12]:
                parts.append(f"- {e.get('case_number','')}")
        else:
            parts.append("- (无,本章请不要引用具体案号)")
        parts.append("")

        # 黑名单
        if bl.get('laws') or bl.get('cases'):
            parts.append("## ❌ 严禁引用(黑名单,未通过核实)")
            for e in bl.get('laws', []):
                parts.append(f"- 《{e.get('law_name','')}》第{e.get('article','')}条")
            for e in bl.get('cases', []):
                parts.append(f"- {e.get('case_number','')}")
            parts.append("")

        parts.append("---")
        parts.append(self._build_section_specific_materials(section_id, materials))
        return "\n".join(parts)

    def _build_section_specific_materials(self, section_id: str, materials: Dict) -> str:
        """每章喂不同素材"""
        narr = materials['narratives']

        # -------- 第一部分 · 用户视角 --------
        if section_id == 'executive_summary':
            return f"""## 用于本节的素材

### 五个 Agent 的核心结论(摘要)
**Agent① 结构分析:**
{self._trim(narr.get('structure', ''), 1500)}

**Agent② 合规审查:**
{self._trim(narr.get('compliance', ''), 1500)}

**Agent③ 可行性评估:**
{self._trim(narr.get('risk', ''), 1000)}

### 本节产出要求(Markdown)
```
## 🎯 能否签署
[一句话结论,必须以"本合同当前版本[可以/不可以]签署,原因是..."开头]

## ⛔ 最关键的 2-3 个红线问题
[每个一行,格式:条款定位 → 问题 → 法律后果]

## ✅ 修正后可签署的前提
[3-5 条必须完成的动作]

## 📊 关键指标
| 指标 | 数值 |
| 合规评分 | XX/100 |
| 红线风险 | X 项 |
| 高风险 | X 项 |
| 中低风险 | X 项 |
| 建议修改条款 | X 处 |
```
"""
        elif section_id == 'risk_dashboard':
            return f"""## 用于本节的素材

### Agent② 识别的合规问题清单
{self._trim(narr.get('compliance', ''), 2500)}

### Agent③ 风险矩阵
{self._trim(narr.get('risk', ''), 2500)}

### 本节产出要求
```
## 风险仪表盘(按风险等级排序,共 X 项)

| 等级 | 风险类型 | 条款定位 | 风险描述(一句话,≤30 字) | 补救难度 |
|---|---|---|---|---|
| 🔴 红线 | ... | 条款 X.X | ... | 高/中/低 |
| 🟠 高危 | ... | 条款 X.X | ... | 高/中/低 |
| 🟡 中低 | ... | 条款 X.X | ... | 高/中/低 |
```
排序:先等级(红线→高→中→低),同级按补救难度(高→低)
"""
        elif section_id == 'action_checklist':
            return f"""## 用于本节的素材

### Agent③ 优先处理事项
{self._trim(narr.get('risk', ''), 3000)}

### Agent⑤ 修改建议
{self._trim(narr.get('final', ''), 2500)}

### 本节产出要求
```
## 三阶段行动清单

### 🔴 签约前必做(未完成不得签约)
- [ ] 1. [具体动作,含对象和标准]
- [ ] 2. [...]

### 🟠 签约时必做(合同文本修订)
- [ ] 4. [具体条款修订]

### 🟡 签约后定期做(履约管理)
- [ ] 6. [每月/每季的动作]
```
要求:每个动作包含"做什么、向谁做、什么标准"三要素。不要抽象口号。
"""
        elif section_id == 'clause_revision':
            return f"""## 用于本节的素材

### Agent② 微观审查 + 修改建议
{self._trim(narr.get('compliance', ''), 3500)}

### Agent⑤ 条款修改建议
{self._trim(narr.get('final', ''), 3000)}

### 本节产出要求
```
## 条款修改对照表

| 条款 | 当前约定 | 问题 | 风险等级 | 建议改法 |
|---|---|---|---|---|
| 2.1 | 声称"已获原房东书面同意" | 无附件佐证 | 🔴 红线 | 新增附件《同意转租确认书》 |
| 4.4 | 每季末 25 日付下季租金 | 无宽限期 | 🟡 中 | 增加 3 日宽限期 |
```
要求:
1. 严格按合同条款号从小到大排序
2. "建议改法"写具体替换文本,不要只说"建议修改"
3. 不遗漏前序 Agent 提到的任何修改点
"""

        # -------- 第二部分 · 三观四步法过程透明 --------
        elif section_id == 'step1_communication':
            return f"""## 用于本节的素材

### 本步在"三观四步法"中的定位
第一步"沟通需求" —— 了解交易背景、客户需求,形成交易画像。
对应 Agent① 主体和交易结构分析。

### Agent① 的完整产出
{self._trim(narr.get('structure', ''), 3500)}

### 本节产出要求
严格按"输入 → 依据 → 产出"三要素组织。输出模板:

```
## 五、第一步 · 沟通需求

> 按三观四步法,第一步的目的是了解交易背景、主体、结构,形成交易画像。
> 本项目由 Agent① 主体和交易结构分析实现。

### 5.1 交易背景与客户诉求
[2-3 句话:交易类型(二房东转租)、各方角色、用户立场(为二房东张三审查)]

### 5.2 主体资格审查
| 主体 | 身份 | 合法性判断 | 风险提示 |
| 甲方(张三) | ... | ... | ... |
| 乙方(李四) | ... | ... | ... |
| 原房东(王五) | ... | ... | ... |

### 5.3 交易结构认定
[4-5 行:租期、租金、押金、责任链条的核心判断]

### 5.4 本步产出(用于后续步骤)
- 主体资格结论:[一句话]
- 结构性风险初判:[一句话]
- 需进一步深入的审查点:[2-3 条,承接第二步]
```
"""
        elif section_id == 'step2_three_perspectives':
            # 这是最长的一节,要覆盖三观 + Agent③ 综合研判
            core_by_p = materials['core_by_perspective']

            macro_items = core_by_p.get('macro', []) + core_by_p.get('unassigned', [])
            meso_items = core_by_p.get('meso', [])
            micro_items = core_by_p.get('micro', [])

            def _format_articles(items: List[Dict], limit: int = 6) -> str:
                if not items:
                    return "  (本层无匹配的核心法条)"
                lines = []
                for a in items[:limit]:
                    src_tag = {
                        'local_kb': '本地规范库',
                        'core_fact': '核心法律事实库',
                        'weko': '威科先行',
                    }.get(a.get('source', ''), a.get('source', ''))
                    lines.append(f"- 《{a.get('law_name','')}》{a.get('article_number_cn','')} [来源:{src_tag}]")
                    lines.append(f"  *争议点:{a.get('topic','')}*")
                return "\n".join(lines)

            return f"""## 用于本节的素材

### 本步在"三观四步法"中的定位
第二步"三观分析" —— 从宏观(交易结构)、中观(合同形式)、微观(合同条款)三个层面全面分析。
对应 Agent② 合规审查 + Agent③ 风险综合研判。

### 本地规范库检索到的核心法条(按三观分组)

**宏观层(交易结构)引用的法条:**
{_format_articles(macro_items)}

**中观层(合同形式)引用的法条:**
{_format_articles(meso_items)}

**微观层(合同条款)引用的法条:**
{_format_articles(micro_items)}

### Agent② 合规审查完整产出
{self._trim(narr.get('compliance', ''), 3500)}

### Agent③ 风险综合研判完整产出
{self._trim(narr.get('risk', ''), 2500)}

### 威科检索调用
{"- 法规检索:已调用" if materials['weko_calls']['weko_regulations'] else "- 法规检索:未调用或失败"}
- 案例检索争议点数:{materials['weko_calls']['weko_cases_count']}

### 本节产出要求
严格按"宏观 → 中观 → 微观 → 综合研判"顺序。每小节按"输入 → 依据 → 产出"三要素组织:

```
## 六、第二步 · 三观分析

> 按三观四步法,第二步分宏观(交易结构)、中观(合同形式)、微观(合同条款)三层全面分析。
> 宏观/中观/微观三层由 Agent② 合规审查完成,综合研判由 Agent③ 完成。

### 6.1 宏观层 · 交易结构
**【输入】** 本步读取 Agent① 的主体和交易结构结论
**【依据】** 本地规范库涉及的规范(按实际白名单列出,举例:《民法典》第 716-719 条关于转租规则、《北京市住房租赁条例》关于主体登记等)
**【审查发现】**
- [问题 1,一句话]
- [问题 2,一句话]
**【产出】** 宏观层结论 + 传递给后续步骤的要点

### 6.2 中观层 · 合同形式
**【输入】** 合同文本整体(格式条款、示范文本符合度)
**【依据】** [按实际白名单:《民法典》第 496-497 条关于格式条款、《北京市住房租赁示范合同》等]
**【审查发现】**
- [问题 1,一句话]
**【产出】** 中观层结论

### 6.3 微观层 · 合同条款
按条款类型逐项审查:
#### 6.3.1 租金支付(条款 4.1-4.5)
**【依据】**【审查发现】【产出】三要素
#### 6.3.2 押金(条款 5.1-5.4)
...
#### 6.3.3 违约责任(条款 8.1-8.4)
...
#### 6.3.4 解除条件(条款 9.1-9.2)
...
#### 6.3.5 维修责任(条款 6.3-6.4)
...
#### 6.3.6 转租限制(条款 2.1, 6.2, 8.3)
...
#### 6.3.7 争议解决(条款 11)
...

### 6.4 风险综合研判(Agent③)
**【输入】** 宏观/中观/微观三层的审查发现
**【综合方法】** 按风险等级(红线/高/中/低)汇总,形成风险矩阵
**【产出】** 可行性结论(signable / not_recommended / recommended)及理由
```

要求:
1. 每一小节必须按"输入 → 依据 → 产出"三要素,不得省略
2. 每条"依据"必须具体到规范名称和条号(从白名单取)
3. 微观层覆盖合同的所有关键条款类型,不漏项
4. 避免过多叙述,重在结构清晰
"""
        elif section_id == 'step3_review':
            return f"""## 用于本节的素材

### 本步在"三观四步法"中的定位
第三步"复核" —— 检查前序分析的法条/案号引用是否真实,结论是否自洽。
对应 Agent④ 交叉验证。

### Agent④ 完整产出
{self._trim(narr.get('validation', ''), 2500)}

### 白名单摘要
- 已核实法条:{len(materials['whitelist']['laws'])} 条
- 已核实案号:{len(materials['whitelist']['cases'])} 个

### 黑名单摘要
- 未核实法条:{len(materials['blacklist']['laws'])} 条
- 未核实案号:{len(materials['blacklist']['cases'])} 个

### 本节产出要求
```
## 七、第三步 · 复核

> 按三观四步法,第三步目的是检查遗漏、验证引用、确保各步结论协调。
> 本项目由 Agent④ 交叉验证实现。

### 7.1 法条引用核实
**【核实机制】** 三级兜底:Agent② 主动提供 > 本地规范库+核心法律事实库 > 基础法典编号范围
**【核实结果】**
- 已核实:X 条,来源分布:Agent② 已核 Y / 本地库 Z / 编号推定 W
- 未核实:X 条,已标记为黑名单,不出现在最终意见书中

### 7.2 案号引用核实
**【核实机制】** 比对 Agent② 威科检索返回的 _parsed.case_numbers
**【核实结果】**
- 已核实:X 个(威科命中)
- 未核实:X 个(其中 Y 个疑似幻觉,含未来年份或占位符特征)

### 7.3 一致性检查
各 Agent 结论是否自洽(无矛盾/无跳跃/无自我否定)。
[✅ 一致 / ⚠ 发现冲突:...]

### 7.4 复核结论
- 整体可信度:[高/中/低]
- 引用污染率:[已核实 / (已核实 + 未核实)] = XX%
```

要求:只陈述程序性核实结果,不要扩写任何案号细节或裁判要旨。
"""
        elif section_id == 'step4_submission':
            core = materials['core_articles']
            wl = materials['whitelist']
            bl = materials['blacklist']

            # 准备核心法条全文(作为法律依据全集的素材)
            core_text_lines = []
            for a in core[:15]:
                core_text_lines.append(f"\n**《{a['law_name']}》{a['article_number_cn']}** [主题:{a['topic']}]")
                core_text_lines.append(f"> {a['content']}")
            core_text = "\n".join(core_text_lines) if core_text_lines else "(无核心法条数据)"

            return f"""## 用于本节的素材

### 本步在"三观四步法"中的定位
第四步"提交" —— 形成最终审查意见,保留底稿,便于客户决策与后续追溯。
对应 Agent⑤ 意见书 + 本节拼装。

### Agent⑤ 最终意见书(原文)
{self._trim(materials['narratives'].get('final', ''), 2500)}

### 已核实的核心法条全文(法律依据全集素材)
{core_text[:4000]}

### 已核实案号
{', '.join([e['case_number'] for e in wl.get('cases', [])]) or '(无)'}

### 本节产出要求
```
## 八、第四步 · 提交

> 按三观四步法,第四步的目的是形成书面审查意见,保留工作底稿。
> 本项目由 Agent⑤ 生成意见书,由本节整合法律依据全集并附免责声明。

### 8.1 最终审查意见
[一段话,300 字以内:审查结论 + 主要理由 + 补救方向 + 风险提示]

### 8.2 法律依据全集(已核实)
按三观分组列出实际引用的法条全文:

#### 8.2.1 宏观层面法条
[列出宏观层引用的法条,格式:法律名 + 条号 + 内容摘要一句话]

#### 8.2.2 中观层面法条
...

#### 8.2.3 微观层面法条
...

### 8.3 参考案例(已核实)
按白名单列出,每个案号一行,格式:案号 + 案由(≤15 字),禁止扩写裁判要旨

### 8.4 免责声明
本报告由合同审查系统基于三观四步法分析框架自动生成。报告中所有法条引用和案号引用均经 Agent④ 交叉验证模块核实;未通过核实的引用已在黑名单中记录并从本意见书中剔除。

即便如此,本报告:
- 仅基于提供的合同文本进行分析,不含现场尽调
- AI 辅助分析存在局限,不能替代执业律师的专业判断
- 重大交易请务必委托执业律师开展独立法律审查

用户基于本报告作出的任何决策,应由用户自行承担责任。
```

要求:
1. 8.2 节的法条分组要体现三观分析逻辑(宏观/中观/微观)
2. 8.3 节案号只写案号本身和案由,禁止"该案裁判要旨为..."
3. 8.4 免责声明必须完整、严肃
"""
        return ""

    @staticmethod
    def _trim(text: str, max_chars: int) -> str:
        if not text:
            return "(无内容)"
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...(素材截断,本节仅用前 %d 字符)..." % max_chars

    # ==============================================================
    # 最终 Markdown 拼装
    # ==============================================================
    def _assemble_markdown(self, sections: Dict[str, str], materials: Dict) -> str:
        now = datetime.now().strftime('%Y年%m月%d日 %H:%M')
        meta = materials['meta']

        header = f"""# 房屋转租合同审查意见书

> **生成时间**:{now}
> **合规评分**:{meta['compliance_score']}/100
> **可行性结论**:{meta['feasibility']}
> **审查工具**:Contract Reviewer v1.7(内置 Agent①~⑤ 多 Agent 流水线 + 威科先行检索 + 本地规范库)
> **理论框架**:《合同起草审查指南:三观四步法》(何力等著,法律出版社 2024 年第 5 版)

---

## 📖 阅读说明

本报告采用**两层结构**:

- **第一部分 · 用户视角的整体结果**(第一至四章):面向决策,倒金字塔组织,结论在前
- **第二部分 · 依三观四步法的过程透明**(第五至八章):面向审计,按理论框架组织每一步

按时间预算选择阅读深度:
- ⏱ 10 秒决策:读第一章
- ⏱ 5 分钟快审:读第一至四章
- ⏱ 深度追溯:读第一至八章 + 附录

---

# 第一部分 · 用户视角的整体结果

"""

        body_parts = [header]

        # 第一部分 4 章
        first_part_ids = ['executive_summary', 'risk_dashboard', 'action_checklist', 'clause_revision']
        for sid in first_part_ids:
            body_parts.append(sections.get(sid, f"[{sid} 生成失败]"))
            body_parts.append("\n\n---\n\n")

        # 过渡
        body_parts.append("""
# 第二部分 · 依三观四步法的过程透明

> 以下内容展示本次审查**每一步做了什么、依据什么规范、产出什么结论**。
> 按项目采用的"三观四步法"理论骨架组织:
> - 第一步 · 沟通需求 → Agent① 主体和交易结构分析
> - 第二步 · 三观分析 → Agent② 合规审查 + Agent③ 风险综合研判
> - 第三步 · 复核 → Agent④ 交叉验证
> - 第四步 · 提交 → Agent⑤ 意见书 + 本节整合

---

""")

        # 第二部分 4 章
        second_part_ids = ['step1_communication', 'step2_three_perspectives', 'step3_review', 'step4_submission']
        for sid in second_part_ids:
            body_parts.append(sections.get(sid, f"[{sid} 生成失败]"))
            body_parts.append("\n\n---\n\n")

        # 附录
        appendix = self._build_appendix(materials)
        body_parts.append(appendix)

        return "".join(body_parts)

    def _build_appendix(self, materials: Dict) -> str:
        out = ["# 附录\n"]

        # A. 原始五份 Agent 分析
        out.append("\n## 附录 A · 原始五份 Agent 分析\n")
        out.append("> 保留原始 Agent 流水线的完整输出,供追溯与审计。\n")

        narr = materials['narratives']
        agent_titles = {
            'structure':  'A.1 Agent① 主体和交易结构分析',
            'compliance': 'A.2 Agent② 合规审查',
            'risk':       'A.3 Agent③ 风险综合研判',
            'validation': 'A.4 Agent④ 交叉验证',
            'final':      'A.5 Agent⑤ 原始意见书',
        }
        for key, title in agent_titles.items():
            content = narr.get(key, '').strip()
            if not content:
                continue
            out.append(f"\n### {title}\n")
            out.append(content)
            out.append("\n")

        # B. 引用核实日志
        out.append("\n---\n\n## 附录 B · 引用核实日志\n")
        bl = materials['blacklist']
        wl = materials['whitelist']

        out.append("\n### B.1 未通过核实的引用(已从主报告中剔除)\n")
        if bl.get('laws') or bl.get('cases'):
            for e in bl.get('laws', []):
                out.append(f"- 法条:《{e.get('law_name','')}》第{e.get('article','')}条  原因:{e.get('reason','')}")
            for e in bl.get('cases', []):
                out.append(f"- 案号:{e.get('case_number','')}  原因:{e.get('reason','')}")
        else:
            out.append("(无)")

        out.append(f"\n\n### B.2 已通过核实的引用\n")
        out.append(f"- 法条:{len(wl.get('laws',[]))} 条")
        out.append(f"- 案号:{len(wl.get('cases',[]))} 个")

        # C. 生成方法说明
        out.append("\n\n---\n\n## 附录 C · 本报告的生成方法\n")
        out.append("""
本报告由 Contract Reviewer v1.7 自动生成,技术实现:

1. **多 Agent 流水线**
   - Agent① 主体和交易结构分析(对应三观四步法第一步"沟通需求")
   - Agent② 合规审查(对应第二步"三观分析"的主体执行)
   - Agent③ 风险综合研判(对应第二步的综合研判部分)
   - Agent④ 交叉验证(对应第三步"复核")
   - Agent⑤ 意见书生成(对应第四步"提交")

2. **法律规范检索**
   - 本地规范库:30 部法律法规 + 司法解释 JSON 化查询
   - 核心法律事实库:硬编码基础条款(民诉法、司法解释等)
   - 威科先行 MCP:法规和案例在线检索

3. **防幻觉机制**
   - Agent② system_prompt 硬性约束(管辖=34条、LPR 不写数字等)
   - Agent② 主动预加载核心法条全文
   - Agent④ 三级兜底验证(prompt_used / local_kb+core_fact / known_basic_law)
   - 白名单 / 黑名单显式隔离

4. **报告加工**
   - 本报告由 ReportPolisher 后处理模块生成
   - 采用"两层嵌套"结构,契合三观四步法理论骨架
   - qwen-plus 仅作编辑,不作作者,避免引入新幻觉
""")

        out.append("\n\n---\n\n")
        out.append("*本报告由 Contract Reviewer 自动生成,采用三观四步法理论框架。*  \n")
        out.append("*AI 辅助分析仅供参考,不能替代执业律师的专业判断。重大交易请委托执业律师复核。*\n")

        return "".join(out)


# ==================================================================
# 每个章节的特殊指令
# ==================================================================
SECTION_SPECIFIC_GUIDES = {
    # 第一部分
    'executive_summary': """- 本节目标:让用户 10 秒内做出"能不能签"的判断
- 最多 5 个要点,每个要点不超过 2 行
- 开头第一句必须是"本合同当前版本[可以/不可以]签署,原因是..."
""",
    'risk_dashboard': """- 本节是一张表格,不需要叙述文字
- 表格按风险等级排序,红线在最上
- 每行"风险描述"不超过 30 字
""",
    'action_checklist': """- 每个动作用可勾选格式(- [ ])
- 必须包含"做什么、向谁做、什么标准"三要素
- 不要口号,只要操作
""",
    'clause_revision': """- 严格按合同条款号从小到大排序
- "建议改法"要给出具体的替换文本,不要只说"建议修改"
- 不遗漏任何前序 Agent 提到的修改点
""",
    # 第二部分
    'step1_communication': """- 每个子章节围绕"输入 → 依据 → 产出"三要素组织
- 说明本步对应 Agent① 的哪些具体工作
- 结尾必须说明"传递给第二步的要点",承上启下
""",
    'step2_three_perspectives': """- 本节是全报告最重要的一节,篇幅允许最长
- 必须严格按"宏观 → 中观 → 微观 → Agent③ 综合研判"顺序
- 每一小节都要有"输入/依据/产出"三要素
- 微观层必须覆盖所有关键条款类型(租金/押金/违约/解除/维修/转租/争议)
- 不漏项、不重复、不引入白名单以外的引用
""",
    'step3_review': """- 本节只陈述"程序性核实结果",不做任何实体判断
- 数字要准:已核实 X 条、未核实 X 条都要有具体数字
- 禁止扩写任何案号细节,禁止生成"该案裁判要旨为..."
""",
    'step4_submission': """- 8.2 法律依据分组必须按"宏观/中观/微观"三层
- 8.3 案号只写"案号 + 案由",禁止任何扩写
- 8.4 免责声明必须完整、严肃
""",
}


# ==================================================================
# CLI 入口
# ==================================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Contract Reviewer v1.7.2 报告加工器(两层结构)")
    parser.add_argument('--output-dir', default=None,
                        help='输出目录(默认项目根 output/)')
    parser.add_argument('--sections', default=None,
                        help='仅生成指定章节,逗号分隔(可选:'
                             + ', '.join(SECTION_TEMPLATES.keys()) + ')')
    args = parser.parse_args()

    polisher = ReportPolisher(output_dir=args.output_dir)

    if args.sections:
        wanted = [s.strip() for s in args.sections.split(',')]
        for sid in wanted:
            if sid not in SECTION_TEMPLATES:
                print(f"⚠ 未知章节:{sid}\n可选:{list(SECTION_TEMPLATES.keys())}")
                return
        polisher._load_raw_data()
        materials = polisher._extract_materials()
        for sid in wanted:
            print(f"\n[调试模式] 生成 {sid} ({SECTION_TEMPLATES[sid]['title']})...")
            content = polisher._generate_section(sid, materials)
            print("=" * 60)
            print(content)
            print("=" * 60)
    else:
        polisher.polish()


if __name__ == "__main__":
    main()