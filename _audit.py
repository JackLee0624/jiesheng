#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全站 HTML 审查：
1. HTML 语法错误
2. hreflang 多语言标注
3. title / meta description
4. Schema JSON-LD 语法
5. 图片 alt 属性
6. 广告法违禁词
7. 各语言版本翻译完整性
"""
import os
import re
import json
import sys
import io
from html.parser import HTMLParser

ROOT = r'c:\Users\westt\CodeBuddy\20260704160458'
LANGS = ['zh', 'en', 'fr', 'de', 'es', 'ja', 'ar']
LANG_DIR = {'zh': '', 'en': 'en/', 'fr': 'fr/', 'de': 'de/', 'es': 'es/', 'ja': 'ja/', 'ar': 'ar/'}
PAGES = ['index.html', 'about.html', 'products.html', 'contact.html', 'faq.html', 'market-insight.html']
BASE = 'https://www.jieshengsteel.com'

# ---------------- 违禁词（广告法 / 绝对化用语） ----------------
# (词, 风险等级)  high=明确违规  mid=需结合上下文判断
BANNED = [
    # 国家级 / 权威类
    ('国家级', 'high'), ('世界级', 'high'), ('国家领导人', 'high'), ('中国驰名商标', 'high'),
    ('驰名商标', 'high'), ('中国名牌', 'high'), ('国家免检', 'high'), ('免检产品', 'high'),
    ('国家权威', 'high'), ('政府认证', 'high'),
    # 绝对化 / 极限用语
    ('最高级', 'high'), ('最佳', 'high'), ('最好', 'high'), ('最优', 'high'), ('最具', 'high'),
    ('最爱', 'high'), ('最赚', 'high'), ('最便宜', 'high'), ('最流行', 'high'), ('最时尚', 'high'),
    ('最舒适', 'high'), ('最先', 'high'), ('最先进', 'high'), ('最畅销', 'high'), ('最省', 'high'),
    ('最强', 'high'), ('最快', 'high'), ('最耐用', 'high'), ('最安全', 'high'), ('最稳定', 'high'),
    ('最低价', 'high'), ('最高价', 'high'), ('最专业', 'high'), ('最优质', 'high'), ('最完美', 'high'),
    ('第一品牌', 'high'), ('全国第一', 'high'), ('全网第一', 'high'), ('销量第一', 'high'),
    ('排名第一', 'high'), ('中国第一', 'high'), ('世界第一', 'high'), ('行业第一', 'high'),
    ('顶尖', 'high'), ('顶级', 'high'), ('极品', 'high'), ('极佳', 'high'), ('绝佳', 'high'),
    ('绝对', 'high'), ('万能', 'high'), ('永久', 'high'), ('王牌', 'high'), ('领袖', 'high'),
    ('首创', 'high'), ('独家', 'high'), ('唯一', 'high'), ('独一无二', 'high'), ('绝无仅有', 'high'),
    ('史无前例', 'high'), ('前无古人', 'high'), ('遥遥领先', 'high'), ('行业领先', 'high'),
    ('国际领先', 'high'), ('领先水平', 'high'), ('填补国内空白', 'high'), ('空前', 'high'),
    ('NO.1', 'high'), ('No.1', 'high'), ('no.1', 'high'), ('TOP1', 'high'), ('Top1', 'high'),
    # 虚假 / 夸大功效
    ('特效', 'high'), ('根治', 'high'), ('包治百病', 'high'), ('永不反弹', 'high'),
    ('祖传', 'high'), ('神效', 'high'), ('奇效', 'high'), ('纯天然', 'high'),
    ('百分百', 'high'), ('100%满意', 'high'), ('零风险', 'high'), ('无风险', 'high'),
    # 需上下文判断（可能是技术参数，如"最大外径"）
    ('最大', 'mid'), ('最小', 'mid'), ('最高', 'mid'), ('最低', 'mid'), ('最新', 'mid'),
    ('领先', 'mid'), ('率先', 'mid'), ('首选', 'high'),
]

# 技术参数语境（出现这些词时，mid 级词多为合法技术描述，降级为 info）
TECH_CONTEXT = ['外径', '壁厚', '长度', '直径', '口径', '公差', '温度', '压力', 'MPa', 'mm',
               '规格', '范围', '型号', '标准', '含量', '硬度', '强度', '≤', '≥', '°C', '%',
               '起订量', 'MOQ', '注文数量', '数量', 'ライン', '生産']


# ---------------- 1. HTML 语法检查 ----------------
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
        'meta', 'param', 'source', 'track', 'wbr'}
OPTIONAL_END = {'li', 'p', 'td', 'tr', 'th', 'option', 'dt', 'dd', 'thead',
                'tbody', 'tfoot', 'colgroup', 'caption', 'rp', 'rt'}


class HTMLChecker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []
        self.imgs = []
        self.dup_attrs = []

    def handle_starttag(self, tag, attrs):
        names = [a[0] for a in attrs if a[0]]
        seen = set()
        for n in names:
            if n in seen:
                self.dup_attrs.append((tag, n, self.getpos()[0]))
            seen.add(n)
        if tag == 'img':
            self.imgs.append((dict(attrs), self.getpos()[0]))
        if tag not in VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_startendtag(self, tag, attrs):
        if tag == 'img':
            self.imgs.append((dict(attrs), self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        while self.stack and self.stack[-1][0] != tag and self.stack[-1][0] in OPTIONAL_END:
            self.stack.pop()
        if not self.stack:
            self.errors.append((self.getpos()[0], '多余的闭合标签 </%s>' % tag))
            return
        if self.stack[-1][0] == tag:
            self.stack.pop()
            return
        idx = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                idx = i
                break
        if idx is None:
            self.errors.append((self.getpos()[0], '多余的闭合标签 </%s>' % tag))
        else:
            unclosed = ['<%s>@%d' % (t, p) for t, p in self.stack[idx + 1:]]
            self.errors.append((self.getpos()[0],
                                '</%s> 之前存在未闭合标签: %s' % (tag, ', '.join(unclosed))))
            del self.stack[idx:]

    def finalize(self):
        for t, p in self.stack:
            if t not in OPTIONAL_END:
                self.errors.append((p, '标签 <%s> 未闭合' % t))


# ---------------- 7. 翻译对象提取 ----------------
def _match_brace(text, start):
    """返回与 text[start]=='{' 匹配的 '}' 下标"""
    depth = 0
    i = start
    in_str = None
    esc = False
    n = len(text)
    while i < n:
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in '"\'':
            in_str = ch
        elif ch == '/' and i + 1 < n and text[i + 1] == '/':
            j = text.find('\n', i)
            i = (j if j > 0 else n)
            continue
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _top_level_keys(block_text):
    """提取对象块内的一级键"""
    keys = []
    depth = 0
    i = 0
    in_str = None
    esc = False
    n = len(block_text)
    while i < n:
        ch = block_text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in '"\'':
            in_str = ch
            i += 1
            continue
        if ch == '{':
            depth += 1
            i += 1
            continue
        if ch == '}':
            depth -= 1
            i += 1
            continue
        if depth == 0:
            m = re.match(r'([A-Za-z_][A-Za-z0-9_]*)\s*:', block_text[i:])
            if m:
                keys.append(m.group(1))
                i += m.end()
                continue
        i += 1
    return keys


def extract_translations(html):
    """返回 {lang: [keys]} 或 None"""
    m = re.search(r'(?:var|const|let)\s+translations\s*=\s*\{', html)
    if not m:
        return None
    open_idx = m.end() - 1
    close_idx = _match_brace(html, open_idx)
    if close_idx < 0:
        return None
    body = html[open_idx + 1:close_idx]
    result = {}
    for lm in re.finditer(r'(?m)^\s*(zh|en|fr|de|es|ja|ar)\s*:\s*\{', body):
        lang = lm.group(1)
        lb = lm.end() - 1
        le = _match_brace(body, lb)
        if le < 0:
            continue
        result[lang] = _top_level_keys(body[lb + 1:le])
    return result or None


def line_of(text, idx):
    return text.count('\n', 0, idx) + 1


# ---------------- 主审查 ----------------
def audit(relpath):
    path = os.path.join(ROOT, relpath)
    with open(path, encoding='utf-8') as f:
        html = f.read()

    issues = []  # (category, line, message)

    m = re.match(r'(?:(\w\w)/)?([\w-]+\.html)$', relpath.replace('\\', '/'))
    cur_lang = m.group(1) or 'zh'
    page = m.group(2)

    # --- 1. HTML 语法 ---
    c = HTMLChecker()
    try:
        c.feed(html)
        c.close()
    except Exception as e:
        issues.append(('HTML语法', 0, '解析异常: %s' % e))
    for ln, msg in c.errors:
        issues.append(('HTML语法', ln, msg))
    for tag, attr, ln in c.dup_attrs:
        issues.append(('HTML语法', ln, '<%s> 属性重复: %s' % (tag, attr)))

    # --- 5. 图片 alt ---
    for attrs, ln in c.imgs:
        src = attrs.get('src', '')
        if 'alt' not in attrs:
            issues.append(('图片alt', ln, '<img> 缺少 alt 属性 | src=%s' % src[:70]))
        elif not attrs['alt'].strip():
            issues.append(('图片alt', ln, '<img> alt 为空 | src=%s' % src[:70]))

    # --- 2. hreflang ---
    found = {}
    for lm in re.finditer(r'<link\b[^>]*>', html):
        tag = lm.group(0)
        if 'rel="alternate"' not in tag or 'hreflang=' not in tag:
            continue
        hl = re.search(r'hreflang="([^"]+)"', tag)
        hr = re.search(r'href="([^"]+)"', tag)
        if hl and hr:
            found[hl.group(1)] = hr.group(1)
    if not found:
        issues.append(('hreflang', 0, '未找到任何 hreflang 标注'))
    else:
        for lang in LANGS:
            if lang not in found:
                issues.append(('hreflang', 0, '缺少 hreflang="%s"' % lang))
            else:
                expect = '%s/%s%s' % (BASE, LANG_DIR[lang], page)
                if found[lang] != expect:
                    issues.append(('hreflang', 0,
                                   'hreflang="%s" 指向 %s，应为 %s' % (lang, found[lang], expect)))
        if 'x-default' not in found:
            issues.append(('hreflang', 0, '缺少 hreflang="x-default"'))

    # canonical
    cm = re.search(r'<link\s+rel="canonical"\s+href="([^"]+)"', html)
    if not cm:
        issues.append(('hreflang', 0, '缺少 canonical'))
    else:
        expect = '%s/%s%s' % (BASE, LANG_DIR.get(cur_lang, ''), page)
        if cm.group(1) != expect:
            issues.append(('hreflang', 0,
                           'canonical 指向 %s，应为 %s' % (cm.group(1), expect)))

    # html lang / dir
    hm = re.search(r'<html\s+lang="([^"]+)"', html)
    expect_lang = {'zh': 'zh-CN', 'en': 'en', 'fr': 'fr', 'de': 'de',
                   'es': 'es', 'ja': 'ja', 'ar': 'ar'}[cur_lang]
    if not hm:
        issues.append(('hreflang', 0, '<html> 缺少 lang 属性'))
    elif hm.group(1) != expect_lang:
        issues.append(('hreflang', 0, '<html lang="%s">，应为 "%s"' % (hm.group(1), expect_lang)))
    if cur_lang == 'ar' and 'dir="rtl"' not in html[:600]:
        issues.append(('hreflang', 0, '阿拉伯语页面缺少 dir="rtl"'))

    # --- 3. title / meta description ---
    tm = re.search(r'<title>(.*?)</title>', html, re.S)
    if not tm:
        issues.append(('Title', 0, '缺少 <title>'))
    else:
        t = tm.group(1).strip()
        if len(t) < 10:
            issues.append(('Title', line_of(html, tm.start()), 'title 过短(%d字符): %s' % (len(t), t[:60])))
        elif len(t) > 70:
            issues.append(('Title', line_of(html, tm.start()), 'title 过长(%d字符): %s' % (len(t), t[:60])))
    dm = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html)
    if not dm:
        issues.append(('Meta', 0, '缺少 meta description'))
    else:
        d = dm.group(1).strip()
        if len(d) < 50:
            issues.append(('Meta', line_of(html, dm.start()), 'description 过短(%d字符): %s' % (len(d), d[:60])))
        elif len(d) > 160:
            issues.append(('Meta', line_of(html, dm.start()), 'description 过长(%d字符，建议≤160)' % len(d)))

    # --- 4. JSON-LD ---
    ld_count = 0
    for lm in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        ld_count += 1
        raw = lm.group(1).strip()
        ln = line_of(html, lm.start())
        try:
            data = json.loads(raw)
        except Exception as e:
            issues.append(('JSON-LD', ln, 'JSON 解析失败: %s' % e))
            continue
        # 基本字段检查（支持 @graph 嵌套结构，@context 可继承）
        def check_node(node, has_ctx=False):
            if not isinstance(node, dict):
                return
            if '@graph' in node:
                ctx = has_ctx or '@context' in node
                for g in node['@graph']:
                    check_node(g, ctx)
                return
            if not has_ctx and '@context' not in node:
                issues.append(('JSON-LD', ln, '缺少 @context'))
            if '@type' not in node:
                issues.append(('JSON-LD', ln, '缺少 @type'))
            if node.get('@type') == 'FAQPage' and not node.get('mainEntity'):
                issues.append(('JSON-LD', ln, 'FAQPage 缺少 mainEntity'))

        check_node(data)
    if ld_count == 0:
        issues.append(('JSON-LD', 0, '未包含任何 Schema JSON-LD 结构化数据'))

    # --- 6. 违禁词 ---
    text = re.sub(r'<script\b.*?</script>', ' ', html, flags=re.S | re.I)
    text = re.sub(r'<style\b.*?</style>', ' ', text, flags=re.S | re.I)
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.S)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    for word, level in BANNED:
        for m2 in re.finditer(re.escape(word), text):
            ctx = text[max(0, m2.start() - 22):m2.end() + 22].strip()
            if level == 'mid':
                # 技术参数语境下调为提示
                if any(k in ctx for k in TECH_CONTEXT):
                    continue
                level_out = 'mid'
            else:
                level_out = level
            issues.append(('违禁词', 0, '[%s] "%s" 上下文: …%s…' % (level_out, word, ctx)))

    # --- 7. 翻译完整性 ---
    trans = extract_translations(html)
    if trans is None:
        if cur_lang == 'zh':
            issues.append(('翻译完整性', 0, '未找到 translations 对象'))
    else:
        base_lang = 'en' if 'en' in trans else (sorted(trans.keys())[0] if trans else None)
        if base_lang:
            base_keys = set(trans[base_lang])
            for lang in LANGS:
                if lang not in trans:
                    issues.append(('翻译完整性', 0, 'translations 缺少语言块: %s' % lang))
                    continue
                missing = base_keys - set(trans[lang])
                extra = set(trans[lang]) - base_keys
                if missing:
                    issues.append(('翻译完整性', 0,
                                   '%s 缺少 %d 个翻译键 (相对 %s): %s' %
                                   (lang, len(missing), base_lang, sorted(missing)[:12])))
                if extra:
                    issues.append(('翻译完整性', 0,
                                   '%s 多出 %d 个键 (相对 %s): %s' %
                                   (lang, len(extra), base_lang, sorted(extra)[:8])))
        # data-i18n 覆盖
        i18n_keys = set(re.findall(r'data-i18n="([^"]+)"', html))
        if i18n_keys:
            for lang in LANGS:
                if lang in trans:
                    miss = i18n_keys - set(trans[lang])
                    if miss:
                        issues.append(('翻译完整性', 0,
                                       '%s 未覆盖 %d 个 data-i18n 键: %s' %
                                       (lang, len(miss), sorted(miss)[:12])))

    return issues


def main():
    files = []
    for base, dirs, fns in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ('.codebuddy', 'images', 'node_modules')]
        for fn in fns:
            if fn.endswith('.html'):
                files.append(os.path.relpath(os.path.join(base, fn), ROOT))
    files.sort()

    all_issues = {}
    for f in files:
        try:
            all_issues[f] = audit(f)
        except Exception as e:
            all_issues[f] = [('异常', 0, str(e))]

    # 汇总
    out = io.StringIO()
    total = 0
    by_cat = {}
    for f, issues in all_issues.items():
        for cat, ln, msg in issues:
            total += 1
            by_cat.setdefault(cat, 0)
            by_cat[cat] += 1

    out.write('=' * 70 + '\n')
    out.write('全站 HTML 审查报告\n')
    out.write('=' * 70 + '\n')
    out.write('审查文件数: %d\n' % len(files))
    out.write('问题总数: %d\n\n' % total)
    out.write('--- 按类别汇总 ---\n')
    for cat in sorted(by_cat, key=lambda k: -by_cat[k]):
        out.write('  %-12s %d\n' % (cat, by_cat[cat]))
    out.write('\n')

    out.write('=' * 70 + '\n')
    out.write('详细清单\n')
    out.write('=' * 70 + '\n')
    for f in files:
        issues = all_issues[f]
        if not issues:
            continue
        out.write('\n' + '-' * 70 + '\n')
        out.write('文件: %s  (共 %d 个问题)\n' % (f, len(issues)))
        out.write('-' * 70 + '\n')
        byc = {}
        for cat, ln, msg in issues:
            byc.setdefault(cat, []).append((ln, msg))
        for cat in sorted(byc):
            out.write('\n  【%s】%d 项\n' % (cat, len(byc[cat])))
            for ln, msg in byc[cat][:40]:
                loc = ('行%s: ' % ln) if ln else ''
                out.write('    - %s%s\n' % (loc, msg))
            if len(byc[cat]) > 40:
                out.write('    ... 另有 %d 项未列出\n' % (len(byc[cat]) - 40))

    report = out.getvalue()
    with open(os.path.join(ROOT, '_audit_report.txt'), 'w', encoding='utf-8') as f:
        f.write(report)
    print(report)


if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    main()
