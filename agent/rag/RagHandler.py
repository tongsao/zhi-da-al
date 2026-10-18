# -*- coding: utf-8 -*-
"""
高风险错误自动拦截器（多文档版）
================================
用途：在人工验收 / 上线运行时，自动检查 RAG 答案中的「事故级」错误。
      这类错误 LLM 裁判测不出来（它只比对事实内容，不比对出处），
      人眼扫读也容易漏过，必须靠规则硬拦。

检查五项：
  A. 伪造资料出处  —— 答案里出现的《XX规范》《XX制度》是否在白名单内
  B. 条号被书名号包裹 —— 如《第五十三条》，属格式错误
  C. 引用条号不存在 —— 引用的第X条在所有文档中查无此条
  C2. 张冠李戴（多文档新增）—— 条号存在，但不在本次检索到的文档里
  D. 条号歧义（多文档新增）—— 多文档都有该条号，答案却没写文档名
  E. 数字/期限与原文不一致 —— 答案里的数字、期限在检索原文中找不到

三种传参方式（都支持）：
    RiskGuard('a.md')                    # 单文件
    RiskGuard('data/FILE/')              # 目录，自动扫 .md / .txt
    RiskGuard(['a.md', 'b.md'])          # 文件列表
    RiskGuard.from_texts({'A':'...'})    # 内存构造，用于自测

用法：
    guard = RiskGuard('data/FILE/')
    report = guard.check(question, answer, context, context_sources)
    if report['should_block']:
        ...  # 拦截、转人工、或强制加免责标注
"""

import re
from pathlib import Path
from typing import List, Dict, Set

# ------------------------------------------------------------------
# 正则说明（关键参数都写了注释，便于自己改）
# ------------------------------------------------------------------

# 条号：匹配 **第十五条** / 第十五条 / 第356条 三种写法
ARTICLE_PAT = re.compile(r'\*\*第([一二三四五六七八九十百千零〇\d]+)条\*\*|第([一二三四五六七八九十百千零〇\d]+)条')

# 书名号内容：匹配 《……》 里的全部文字
BOOK_TITLE_PAT = re.compile(r'《([^》]+)》')

# 条号被书名号包裹：《第五十三条》—— 这种写法本身错误
ARTICLE_IN_BOOK_PAT = re.compile(r'《\s*第[一二三四五六七八九十百千零〇\d]+条\s*》')

# 期限关键词（命中后会把前面的数字一起取出来比对）
DURATION_WORDS = ['年', '个月', '日', '天', '工作日', '小时', '次', '分之一', '%', '％']

# 协议类关键词：命中则放行书名号（原文里本就有《证券交易委托代理协议》等）
AGREEMENT_KEYWORDS = ['协议', '合同', '风险揭示书', '委托书', '办法', '指引', '准则', '规定']


class RiskGuard:
    def  __init__(self, doc_paths, allowed_source_names: List[str] = None):
        """
        :param doc_paths: 单文件路径 / 目录路径 / 文件路径列表
        :param allowed_source_names: 额外允许的资料名（可选，一般不用传）
        """
        self.docs = self._load_docs(doc_paths)      # {文件名: 全文}
        self._build_index()
        self.allowed_source_names = self._derive_allowed_names(allowed_source_names)

    # ---------------- 新增：内存构造（自测用，不依赖真实文件） ----------------
    @classmethod
    def from_texts(cls, docs: Dict[str, str], allowed_source_names=None):
        """直接用 {'文档名': '正文'} 构造，用于自测或单元测试"""
        guard = cls.__new__(cls)
        guard.docs = docs
        guard._build_index()
        guard.allowed_source_names = guard._derive_allowed_names(allowed_source_names)
        return guard

    # ---------------- 新增：统一加载入口 ----------------
    def _load_docs(self, doc_paths) -> Dict[str, str]:
        """支持 单文件 / 目录 / 文件列表 三种输入"""
        if isinstance(doc_paths, str):
            p = Path(doc_paths)
            if p.is_dir():
                # 目录：自动扫 md 和 txt，排序保证顺序稳定
                files = sorted(p.glob('*.md')) + sorted(p.glob('*.txt'))
            else:
                files = [p]
        else:
            files = [Path(x) for x in doc_paths]

        docs = {}
        for f in files:
            with open(f, encoding='utf-8') as fh:
                docs[f.stem] = fh.read()   # 用文件名（不含扩展名）做 key
        if not docs:
            raise ValueError(f'未在 {doc_paths} 下找到任何 .md / .txt 文档')
        return docs

    # ---------------- 新增：条号按文档分桶 ----------------
    def _build_index(self):
        self.doc_articles: Dict[str, Set[str]] = {}   # {'制度汇编': {'十五','十六'}}
        article_to_docs: Dict[str, Set[str]] = {}     # {'十五': {'制度汇编','反洗钱'}}

        for name, text in self.docs.items():
            arts = set()
            for m in ARTICLE_PAT.finditer(text):
                num = m.group(1) or m.group(2)
                if num:
                    arts.add(num)
                    article_to_docs.setdefault(num, set()).add(name)
            self.doc_articles[name] = arts

        self.valid_articles = set(article_to_docs.keys())        # 全局并集（向后兼容）
        # 出现在 ≥2 个文档里的条号 = 歧义条号，答案必须写明文档名
        self.ambiguous_articles = {a for a, ds in article_to_docs.items() if len(ds) > 1}

    # ---------------- 新增：白名单自动从文件名推导 ----------------
    def _derive_allowed_names(self, extra) -> Set[str]:
        names = set()
        for name in self.docs:
            names.add(name)                                  # 完整文件名
            names.add(name.replace('证券公司', ''))           # 去前缀的简称
        names |= {'资料', '制度汇编'}                          # 泛称保底（兼容单文档写法）
        names |= set(extra or [])
        return names

    # ---------------- A. 伪造资料出处 ----------------
    def _check_source_names(self, answer: str) -> List[Dict]:
        issues = []
        for title in BOOK_TITLE_PAT.findall(answer):
            if any(k in title for k in AGREEMENT_KEYWORDS):
                continue                      # 协议类放行
            if title in self.allowed_source_names:
                continue                      # 白名单内的资料名放行
            issues.append({
                'type': '伪造资料出处',
                'detail': f'答案中出现《{title}》，但该名称不在白名单内',
                'severity': 'high',           # 合规场景＝事故级
            })
        return issues

    # ---------------- B. 条号被书名号包裹 ----------------
    def _check_article_format(self, answer: str) -> List[Dict]:
        issues = []
        for m in ARTICLE_IN_BOOK_PAT.finditer(answer):
            issues.append({
                'type': '条号格式错误',
                'detail': f'条号不应加书名号：{m.group(0)}，应写为「第X条」',
                'severity': 'medium',
            })
        return issues

    # ---------------- C + C2 + D. 条号相关 ----------------
    def _check_articles(self, answer: str, context_sources=None) -> List[Dict]:
        issues = []
        seen = set()

        # 答案里是否写了文档名（用于判断歧义条号能否溯源）
        mentioned_titles = set(BOOK_TITLE_PAT.findall(answer))
        has_doc_name = any(t in self.allowed_source_names for t in mentioned_titles)

        for m in ARTICLE_PAT.finditer(answer):
            num = m.group(1) or m.group(2)
            if not num or num in seen:
                continue
            seen.add(num)

            # C. 全库都不存在 → 编造条号
            if num not in self.valid_articles:
                issues.append({
                    'type': '引用条号不存在',
                    'detail': f'答案引用了「第{num}条」，但所有文档中都不存在该条',
                    'severity': 'high',
                })
                continue

            # C2. 条号存在，但不在本次检索到的文档里 → 张冠李戴
            if context_sources:
                allowed = set()
                for s in context_sources:
                    allowed |= self.doc_articles.get(s, set())
                if num not in allowed:
                    issues.append({
                        'type': '张冠李戴',
                        'detail': f'答案引用了「第{num}条」，但该条不在本次检索到的文档中'
                                  f'（本次来源：{context_sources}）',
                        'severity': 'high',
                    })
                    continue

            # D. 歧义条号且没写文档名 → 无法溯源（只提示，不拦截）
            if num in self.ambiguous_articles and not has_doc_name:
                issues.append({
                    'type': '条号歧义',
                    'detail': f'「第{num}条」在多个文档中都存在，答案未写明是哪个文档，无法溯源',
                    'severity': 'low',
                })

        return issues

    # ---------------- E. 数字/期限与原文不一致 ----------------
    def _check_numbers(self, answer: str, context: str) -> List[Dict]:
        """
        抓出答案里的「数字+期限单位」组合，逐个到检索原文 context 里找。
        找不到就标记为待人工确认。
        注意：这是「提示」不是「判定」——中文数字写法多样（10 / 十 / 十个工作日），
              会有误报，所以 severity 设为 low，只提醒人工核，不直接拦截。
        """
        issues = []
        if not context:
            return issues

        checked = set()
        for w in DURATION_WORDS:
            pat = re.compile(r'([0-9０-９一二三四五六七八九十百千]+)\s*' + w)
            for m in pat.finditer(answer):
                frag = m.group(0)
                if frag in checked:
                    continue
                checked.add(frag)
                if frag not in context:
                    issues.append({
                        'type': '数字/期限待核对',
                        'detail': f'答案中的「{frag}」在检索原文中未原样出现，请人工核对',
                        'severity': 'low',
                    })
        return issues

    # ---------------- 主入口 ----------------
    def check(self, question: str, answer: str, context: str = None,
              context_sources: List[str] = None) -> Dict:
        """
        :param context:         检索到的原文（E 检查需要）
        :param context_sources: 本次检索涉及的文档名列表（C2 张冠李戴检查需要）
                                从 retriever 返回的 metadata['source'] 去重得到
        """
        issues = []
        issues += self._check_source_names(answer)
        issues += self._check_article_format(answer)
        issues += self._check_articles(answer, context_sources)
        issues += self._check_numbers(answer, context)

        if any(i['severity'] == 'high' for i in issues):
            level = 'high'
        elif any(i['severity'] == 'medium' for i in issues):
            level = 'medium'
        elif issues:
            level = 'low'
        else:
            level = 'none'

        return {
            'question': question,
            'risk_level': level,               # high / medium / low / none
            'should_block': level == 'high',   # high 直接拦截，不给用户看
            'issues': issues,
        }


# ------------------------------------------------------------------
# 自测：用内存构造的假文档验证，不依赖任何真实文件路径
# ------------------------------------------------------------------
if __name__ == '__main__':
    fake_docs = {
        '证券公司管理制度汇编': '**第十五条**董事会由七至十三名董事组成。\n'
                          '**第五十三条**公司实行回避制度。员工的配偶、直系血亲……',
        '反洗钱制度': '**第十五条**客户身份识别应当在建立业务关系时完成。\n'
                  '**第三条**应当保存客户身份资料不少于五年。',
    }
    guard = RiskGuard.from_texts(fake_docs)
    print(f'文档数：{len(guard.docs)}')
    print(f'真实条号：{sorted(guard.valid_articles)}')
    print(f'歧义条号：{sorted(guard.ambiguous_articles)}')
    print(f'资料名白名单：{sorted(guard.allowed_source_names)}\n')

    cases = [
        {
            'name': '【单文档·正常】修复后的写法',
            'answer': '根据资料第五十三条，员工的配偶、直系血亲不得在同一部门任职。',
            'ctx': '第五十三条　公司实行回避制度。员工的配偶……',
            'src': ['证券公司管理制度汇编'],
        },
        {
            'name': '【多文档·正常】写明文档名',
            'answer': '根据《反洗钱制度》第十五条，客户身份识别应当在建立业务关系时完成。',
            'ctx': '第十五条　客户身份识别应当在建立业务关系时完成。',
            'src': ['反洗钱制度'],
        },
        {
            'name': '【多文档·歧义】不写文档名',
            'answer': '根据资料第十五条，应当完成客户身份识别。',
            'ctx': '第十五条　客户身份识别应当在建立业务关系时完成。',
            'src': ['反洗钱制度'],
        },
        {
            'name': '【多文档·张冠李戴】检索A却引B的条号',
            'answer': '根据资料第三条，应当保存客户身份资料不少于五年。',
            'ctx': '第十五条　董事会由七至十三名董事组成。',
            'src': ['证券公司管理制度汇编'],   # 本次只检索了制度汇编，但第三条在反洗钱制度里
        },
        {
            'name': '【伪造出处】白名单外',
            'answer': '根据《证券公司合规管理规范》第五十二条的规定……',
            'ctx': '',
            'src': ['证券公司管理制度汇编'],
        },
        {
            'name': '【协议名】应放行',
            'answer': '应当与客户签署《证券交易委托代理协议》《风险揭示书》。',
            'ctx': '（四）签署协议。与客户签署《证券交易委托代理协议》《风险揭示书》。',
            'src': ['证券公司管理制度汇编'],
        },
    ]

    for c in cases:
        r = guard.check('测试问题', c['answer'], c['ctx'], c['src'])
        print(f"{c['name']}\n  → 等级：{r['risk_level']}  拦截：{r['should_block']}")
        for i in r['issues']:
            print(f"     [{i['severity']}] {i['type']}：{i['detail']}")
        print()
