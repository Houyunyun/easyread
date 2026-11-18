"""Discovery and mindmap prompts; language applies to prose, never source data."""
import json

from ..translate import langs
from .language import output_rule


MINDMAP_BRANCHES = {
    "ko": [
        '`연구 배경 및 문제`：연구 동기, 해결하려는 핵심 문제 또는 기존 기술의 한계.',  # i18n-ok: target-language branch example
        '`핵심 구조 및 이론`：전체 시스템/모델 아키텍처, 이론적 기초, 핵심 컴포넌트 및 모듈.',  # i18n-ok: target-language branch example
        '`방법론 및 핵심 메커니즘`：알고리즘 프로세스, 주요 설계, 손실 함수 또는 수학적 표현.',  # i18n-ok: target-language branch example
        '`실험 설계 및 벤치마크`：벤치마크 테스트, 평가 데이터셋, 비교 베이스라인, 평가 지표.',  # i18n-ok: target-language branch example
        '`주요 발견 및 성과`：주요 실험 결론, SOTA 비교 성과, 어블레이션(Ablation) 분석 인사이트.',  # i18n-ok: target-language branch example
        '`연구 기여 및 혁신`：핵심 학술적 기여, 방법론적 혁신 또는 실용적 가치.',  # i18n-ok: target-language branch example
        '`한계점 및 향후 연구`：방법의 한계, 미해결 과제 또는 향후 연구 방향.',  # i18n-ok: target-language branch example
    ],
    "ja": [
        '`研究背景と課題`：研究の動機、解決を目指す中心課題や既存技術のボトルネック。',  # i18n-ok: target-language branch example
        '`コアアーキテクチャと理論`：システム・モデル全体の構造、理論的基礎、主要コンポーネント。',  # i18n-ok: target-language branch example
        '`手法と主要メカニズム`：アルゴリズムのフロー、主要な設計、損失関数や数式表現。',  # i18n-ok: target-language branch example
        '`実験設計とベンチマーク`：ベンチマーク、評価データセット、ベースライン、評価指標。',  # i18n-ok: target-language branch example
        '`主要な発見と成果`：主要な実験結果、SOTA との比較、アブレーション (Ablation) 解析の洞察。',  # i18n-ok: target-language branch example
        '`研究の貢献と新規性`：主要な学術的貢献、手法の新規性や実用的な価値。',  # i18n-ok: target-language branch example
        '`限界と今後の課題`：手法の適用範囲・制限、未解決の課題や将来の研究方向。',  # i18n-ok: target-language branch example
    ],
    "zh": [
        '`研究背景与问题`：研究动机、欲解决的核心问题或现有技术瓶颈。',  # i18n-ok: target-language branch example
        '`核心架构与理论`：整体系统或模型架构、理论基础、核心组件模块。',  # i18n-ok: target-language branch example
        '`方法与关键机制`：算法流程、关键设计、损失函数或数学表达。',  # i18n-ok: target-language branch example
        '`实验设计与基准`：基准测试 (Benchmarks)、评估数据集、对照基准 (Baselines)、评估指标。',  # i18n-ok: target-language branch example
        '`核心发现与成果`：主要实验结论、SOTA 对比成果、消融实验 (Ablation) 洞察。',  # i18n-ok: target-language branch example
        '`研究贡献与创新`：核心学术突破、方法创新或实务价值。',  # i18n-ok: target-language branch example
        '`局限性与未来方向`：方法边界、未解决问题或改进方向。',  # i18n-ok: target-language branch example
    ],
    "en": [
        '`Research Background & Problem`：Motivation, core problem addressed, or limitations of existing methods.',  # i18n-ok: target-language branch example
        '`Core Architecture & Theory`：Overall system/model architecture, theoretical foundation, key components.',  # i18n-ok: target-language branch example
        '`Methodology & Mechanisms`：Algorithm workflow, key design choices, loss functions or mathematical formulations.',  # i18n-ok: target-language branch example
        '`Experimental Design & Benchmarks`：Benchmark tasks, datasets, baseline comparisons, evaluation metrics.',  # i18n-ok: target-language branch example
        '`Key Findings & Results`：Main empirical conclusions, SOTA comparisons, ablation study insights.',  # i18n-ok: target-language branch example
        '`Contributions & Innovations`：Key academic breakthroughs, methodological innovations, or practical value.',  # i18n-ok: target-language branch example
        '`Limitations & Future Work`：Scope boundaries, unaddressed challenges, or potential extensions.',  # i18n-ok: target-language branch example
    ],
    "es": [
        '`Contexto y Problema`：Motivación de la investigación, problema central abordado o limitaciones previas.',  # i18n-ok: target-language branch example
        '`Arquitectura y Teoría Central`：Estructura del sistema/modelo, fundamentos teóricos y componentes clave.',  # i18n-ok: target-language branch example
        '`Metodología y Mecanismos Clave`：Flujo algorítmico, diseño metodológico, funciones de pérdida o formulaciones.',  # i18n-ok: target-language branch example
        '`Diseño Experimental y Benchmarks`：Pruebas de referencia, conjuntos de datos, líneas base y métricas.',  # i18n-ok: target-language branch example
        '`Hallazgos y Resultados Principales`：Conclusiones empíricas, comparaciones SOTA y análisis de ablación.',  # i18n-ok: target-language branch example
        '`Contribuciones e Innovaciones`：Aportes académicos clave, innovaciones prácticas o metodológicas.',  # i18n-ok: target-language branch example
        '`Limitaciones y Trabajo Futuro`：Límites del método, desafíos abiertos o direcciones futuras.',  # i18n-ok: target-language branch example
    ],
    "fr": [
        '`Contexte et Problématique`：Motivation de recherche, problème central abordé ou verrous scientifiques.',  # i18n-ok: target-language branch example
        '`Architecture et Théorie Fondamentale`：Structure globale du modèle/système, fondements théoriques et modules clés.',  # i18n-ok: target-language branch example
        '`Méthodologie et Mécanismes Clés`：Déroulement algorithmique, choix de conception, fonctions de perte.',  # i18n-ok: target-language branch example
        "`Protocole Expérimental et Benchmarks`：Jeux de données, bancs d'essai, modèles de référence et métriques.",  # i18n-ok: target-language branch example
        "`Résultats et Découvertes Clés`：Conclusions empiriques, comparaison à l'état de l'art (SOTA), études d'ablation.",  # i18n-ok: target-language branch example
        '`Contributions et Innovations`：Apports scientifiques majeurs, innovations méthodologiques ou pratiques.',  # i18n-ok: target-language branch example
        "`Limites et Perspectives Futures`：Limites de l'approche, questions ouvertes et axes futurs.",  # i18n-ok: target-language branch example
    ],
    "de": [
        '`Forschungshintergrund & Problemstellung`：Forschungsmotivation, adressiertes Kernproblem oder bisherige Grenzen.',  # i18n-ok: target-language branch example
        '`Kernarchitektur & Theoretische Grundlagen`：Gesamtsystem/Modellarchitektur, theoretische Basis, Hauptkomponenten.',  # i18n-ok: target-language branch example
        '`Methodik & Schlüsselmechanismen`：Algorithmischer Ablauf, zentrale Designentscheidungen, Verlustfunktionen.',  # i18n-ok: target-language branch example
        '`Experimentelles Design & Benchmarks`：Evaluations-Datensätze, Baselines, Benchmarks und Metriken.',  # i18n-ok: target-language branch example
        '`Wichtigste Erkenntnisse & Ergebnisse`：Empirische Hauptergebnisse, SOTA-Vergleiche, Ablationsstudien.',  # i18n-ok: target-language branch example
        '`Wissenschaftliche Beiträge & Innovationen`：Zentrale wissenschaftliche Durchbrüche und methodische Innovationen.',  # i18n-ok: target-language branch example
        '`Grenzen & Zukünftige Forschungsrichtungen`：Einschränkungen der Methode, offene Fragen und zukünftige Arbeiten.',  # i18n-ok: target-language branch example
    ],
    "zh-Hant": [
        '`研究背景與問題`：研究動機、欲解決的核心問題或既有技術瓶頸。',  # i18n-ok: target-language branch example
        '`核心架構與理論`：整體系統或模型架構、理論基礎、核心組件模組。',  # i18n-ok: target-language branch example
        '`方法與關鍵機制`：演算法流程、關鍵設計、損失函數或數學表達。',  # i18n-ok: target-language branch example
        '`實驗設計與基準`：基準測試 (Benchmarks)、評估資料集、對照基準 (Baselines)、評估指標。',  # i18n-ok: target-language branch example
        '`核心發現與成果`：主要實驗結論、SOTA 對比成果、消融實驗 (Ablation) 洞察。',  # i18n-ok: target-language branch example
        '`研究貢獻與創新`：核心學術突破、方法創新或實務價值。',  # i18n-ok: target-language branch example
        '`局限性與未來方向`：方法邊界、未解決問題或改進方向（若原文未提及可精簡或略過）。',  # i18n-ok: target-language branch example
    ],
    "it": [
        'Contesto e problema di ricerca',  # i18n-ok: target-language branch example
        'Architettura e teoria',  # i18n-ok: target-language branch example
        'Metodologia e meccanismi',  # i18n-ok: target-language branch example
        'Esperimenti e benchmark',  # i18n-ok: target-language branch example
        'Risultati principali',  # i18n-ok: target-language branch example
        'Contributi e innovazioni',  # i18n-ok: target-language branch example
        'Limiti e sviluppi futuri',  # i18n-ok: target-language branch example
    ],
}


def mindmap_language_guide(meta: dict | None) -> tuple[str, dict]:
    target = langs.reply_code(meta)
    return target, {"name": langs.reply_lang({"target": target}), "branches": MINDMAP_BRANCHES[target]}


def mindmap_prompt(title: str, source_text: str, target: str) -> str:
    _, guide = mindmap_language_guide({"target": target})
    branch_lines = "\n".join(f"   - {b}" for b in guide["branches"])
    return (output_rule(target) +
        "你是一位资深的学术架构分析专家。请根据下方提供的论文文字，为其建构一份结构清晰、资讯密度高且具备强大可读性的「Mermaid 心智图 (mindmap)」。\n\n"  # i18n-ok: prompt
        f"重要语言指引：此篇论文目标语言为【{guide['name']}】。心智图的根节点、所有一级分类分支名称、以及二级至末端节点文字，请一律使用【{guide['name']}】输出。\n\n"  # i18n-ok: prompt
        "【架构与层级规范】\n"  # i18n-ok: prompt
        f"1. 根节点：论文核心主题或简化标题（使用目标语言），语法如 `  root((论文标题))`。\n"  # i18n-ok: prompt
        f"2. 主要分支（一级分支，请使用目标语言表达，依学术逻辑组织 5 至 7 个核心维度）：\n"  # i18n-ok: prompt
        f"{branch_lines}\n"
        "3. 层级深度：建议展开至 3 至 4 层；主要分支下设 2 至 4 个子分支（二级节点），末端节点（三级/四级节点）列出具体变数、数据指标、方法细节。\n\n"  # i18n-ok: prompt
        "【节点内容与视觉渲染强化】\n"  # i18n-ok: prompt
        "1. 精炼原则：节点文字必须精简有力（建议控制在 6 至 20 个字），使用名词短语或精要摘要，严禁整段复制长句。\n"  # i18n-ok: prompt
        r"2. KaTeX 数学公式：遇到数学变数、维度、复杂度或重要公式时，自然运用行内 KaTeX 格式（如 $O(N^2)$、$d=512$、$\mathcal{L}_{\text{task}}$、$\alpha=0.5$）。" "\n"  # i18n-ok: prompt
        "3. 基础 Markdown 语法：\n"  # i18n-ok: prompt
        "   - 专有名词、模组名称、演算法或程式码变数，适当使用行内代码（如 `ResNet-50`、`CrossAttention`、`AdamW`）。\n"  # i18n-ok: prompt
        "   - 关键突破、重要量化成果或核心结论，适当使用粗体突显（如 `提升 **+3.4%**`、`达到 **92.1%**`、`减少 **40%** 延迟`）。\n"  # i18n-ok: prompt
        "4. 自然融入：以上格式化元素请自然融入学术脉络中，切勿在每个节点硬性堆砌特殊符号，保持整体视觉清爽干净。\n\n"  # i18n-ok: prompt
        "【语言与真实性规范】\n"  # i18n-ok: prompt
        "严格基于提供的文字，不虚构数据、数据集或实验结果。\n\n"  # i18n-ok: prompt
        "【Mermaid 语法与输出格式严格要求】\n"  # i18n-ok: prompt
        "1. 第 1 行必须为 `mindmap`。\n"  # i18n-ok: prompt
        "2. 根节点紧接其后，缩排 2 个空格。\n"  # i18n-ok: prompt
        "3. 层级缩排：每一层级严格固定缩排 2 个空格（第一层 2 空格、第二层 4 空格、第三层 6 空格、第四层 8 空格），严禁使用 Tab。\n"  # i18n-ok: prompt
        '4. 标点安全：若节点文字中包含圆括号 ()、方括号 [] 或冒号等符号，请以双引号与方括号包裹（例如 `    ["Cross-Entropy (CE) 损失"]`），防止 Mermaid 语法树解析中断。\n'  # i18n-ok: prompt
        "5. 绝对限制：只输出 Mermaid 程式码本身！不要包含 Markdown 程式码区块标记（不要输出 ```mermaid 或 ```），不要包含任何引言、前言、解释或结尾问候语。\n\n"  # i18n-ok: prompt
        f"论文标题：{title}\n"  # i18n-ok: prompt
        f"目标语言：{guide['name']}\n"  # i18n-ok: prompt
        f"来源文字（论文结构化原文与实验数据）：\n{source_text}"  # i18n-ok: prompt
    )


def reading_path_prompt(source: list[dict], goal: str, topic: str, target: str) -> str:
    return (output_rule(target) +
        "你是一位学术研究导师。请根据下方已检索到的候选论文清单，依研究目标规划一份具备学习进阶顺序的阅读路径（由浅入深、由基础到前沿，约 5 至 10 篇）。\n"  # i18n-ok: prompt
        "规则：\n"  # i18n-ok: prompt
        "1. 只能推荐清单中存在的论文 id，不得虚构论文或作者。\n"  # i18n-ok: prompt
        "2. 角色（role）请依阅读顺序精准标注：如「基础入门」、「先备背景」、「主流方法」、「起点核心」、「代表性研究」、「延伸探索」、「前沿突破」等。\n"  # i18n-ok: prompt
        "3. 理由（reason）请具体说明「为什么要先读这篇、它为后续论文建立了什么概念或提供了什么方法」。\n"  # i18n-ok: prompt
        "4. priority 请标记阅读顺序（1 为最先读，数字依序递增）。\n"  # i18n-ok: prompt
        "5. 输出标准 JSON 阵列，每项包含 id、role、reason、priority。\n\n"  # i18n-ok: prompt
        f"研究目标：{goal or '建立主题脉络，由浅入深掌握核心研究'}\n"  # i18n-ok: prompt
        f"主题：{topic}\n"  # i18n-ok: prompt
        f"候选论文：{json.dumps(source, ensure_ascii=False)}"  # i18n-ok: prompt
    )



def summary_prompt(papers: list[dict], target: str, batch: bool = False) -> str:
    shape = ("输出 JSON 数组，每项包含 paper_key 与 summary_markdown。" if batch else "只输出 Markdown。")  # i18n-ok: prompt
    return (output_rule(target) + "整理下列论文的来源摘要。每篇只根据该篇提供的资料，不补造结果、引用或出版信息；缺失信息明确说明未提供，推论需标明。"  # i18n-ok: prompt
            "摘要涵盖研究问题、方法、结果与限制。" + shape + "\n" + json.dumps(papers, ensure_ascii=False))  # i18n-ok: prompt


def related_prompt(category: str, source: dict, target: str) -> str:
    return (output_rule(target) + "说明这篇论文与用户选择的分类可能有何关联。只能根据提供的标题与摘要；若资料不足直接说明，不补造方法或成果。"  # i18n-ok: prompt
            "这是待审阅的 AI 解读，不是资料来源证明。\n分类：" + category + "\n论文资料：" + json.dumps(source, ensure_ascii=False))  # i18n-ok: prompt
