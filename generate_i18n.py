#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_i18n.py — 多语言静态页面生成脚本

以根目录中文(zh)页面为模板，生成 en/fr/de/es/ja/ar 共 6 种语言的静态 HTML 版本。

功能：
1. 解析页面内嵌的 translations JS 对象，提取各语言翻译键值
2. 替换正文 data-i18n 文本、data-i18n-placeholder 占位符、data-i18n-alt/title 属性
3. 语言切换器改为静态链接（当前语言 active，其余指向 ../<lang>/<page>）
4. 更新 <html lang>/dir、canonical、hreflang 备用链接、title/meta、FAQ JSON-LD
5. 移除 IP 检测 JS（ipapi 检测与自动重定向代码块），currentLang/storedLang 固定为目标语言
6. 站内图片资源链接增加 ../ 前缀以适配子目录部署；页面导航保持相对链接指向同语言版本

用法：
    python generate_i18n.py                 # 生成全部 6 种语言
    python generate_i18n.py --langs en,ar   # 仅生成指定语言
    python generate_i18n.py --verify        # 仅校验已生成的文件，不重新生成
    python generate_i18n.py --self-test     # 运行内置自检（IP 检测移除逻辑）
"""

import argparse
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# ============ 配置 ============
BASE_URL = 'https://www.jieshengsteel.com'
LANGS = ['en', 'fr', 'de', 'es', 'ja', 'ar']          # 生成的目标语言
ALL_LANGS = ['zh'] + LANGS                            # 含中文在内的全部语言
ROOT = os.path.dirname(os.path.abspath(__file__))
PAGES = ['index.html', 'about.html', 'products.html', 'contact.html',
         'faq.html', 'market-insight.html']

FLAG_MAP = {'zh': '🇨🇳', 'en': '🇬🇧', 'fr': '🇫🇷', 'de': '🇩🇪',
            'es': '🇪🇸', 'ja': '🇯🇵', 'ar': '🇸🇦'}
LANG_NAMES = {'zh': '中文', 'en': 'English', 'fr': 'Français', 'de': 'Deutsch',
              'es': 'Español', 'ja': '日本語', 'ar': 'العربية'}
LANG_ATTR = {'zh': 'zh-CN', 'en': 'en-US', 'fr': 'fr-FR', 'de': 'de-DE',
             'es': 'es-ES', 'ja': 'ja-JP', 'ar': 'ar-SA'}
HTML_ENTITIES = {'&': '&amp;', '<': '&lt;', '>': '&gt;'}

# 键别名：页面 data-i18n 属性中使用的键名 -> translations 中实际存在的键名
KEY_ALIASES = {
    'addr_val': 'contact_addr_val',
    'detail_addr_val': 'contact_addr_val',
}

# 没有闭合标签的 void 元素（用于子标签深度统计）
VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
             'link', 'meta', 'param', 'source', 'track', 'wbr'}


# ============ HTML 文本工具 ============

def find_tag_end(html, pos):
    """从开标签 '<' 位置 pos 起，返回标签结束 '>' 的位置（引号感知）。"""
    n = len(html)
    in_dq = in_sq = False
    i = pos + 1
    while i < n:
        ch = html[i]
        if in_dq:
            if ch == '"' and html[i - 1] != '\\':
                in_dq = False
        elif in_sq:
            if ch == "'" and html[i - 1] != '\\':
                in_sq = False
        elif ch == '"':
            in_dq = True
        elif ch == "'":
            in_sq = True
        elif ch == '>':
            return i
        i += 1
    return -1


def _match_paren(s, open_pos):
    """s[open_pos]=='('，返回与之匹配的 ')' 位置；找不到返回 len(s)-1。"""
    depth = 0
    in_dq = in_sq = False
    i = open_pos
    n = len(s)
    while i < n:
        ch = s[i]
        if in_dq:
            if ch == '\\':
                i += 2
                continue
            if ch == '"':
                in_dq = False
        elif in_sq:
            if ch == '\\':
                i += 2
                continue
            if ch == "'":
                in_sq = False
        elif ch == '"':
            in_dq = True
        elif ch == "'":
            in_sq = True
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n - 1


def find_element_close(html, body_start, tag):
    """从开标签体之后 body_start 起，返回匹配的闭合 </tag> 中 '<' 的位置；
    未找到返回 -1。栈式处理同标签嵌套，自闭合/void 开标签不计深度。"""
    depth = 1
    open_re = re.compile(r'<(%s)(\s|>|/)' % re.escape(tag))
    close_re = re.compile(r'</%s\s*>' % re.escape(tag))
    n = len(html)
    i = body_start
    while i < n:
        lt = html.find('<', i)
        if lt == -1:
            return -1
        if lt + 1 < n and html[lt + 1] == '/':
            m = close_re.match(html, lt)
            if m:
                depth -= 1
                if depth == 0:
                    return lt
                i = m.end()
            else:
                i = lt + 1
        else:
            m = open_re.match(html, lt)
            if m:
                gt = find_tag_end(html, lt)
                is_self_close = gt != -1 and (html[gt - 1] == '/'
                                              or tag.lower() in VOID_TAGS)
                if gt != -1 and not is_self_close:
                    depth += 1
                i = gt + 1 if gt != -1 else lt + 1
            else:
                i = lt + 1
    return -1


def find_open_tag_start(html, pos):
    """pos 位于某属性处，返回该属性所在开标签的 '<' 位置。"""
    lt = pos
    while True:
        lt = html.rfind('<', 0, lt)
        if lt == -1:
            return -1
        if lt + 1 < len(html) and html[lt + 1] in '/!':
            continue
        gt = find_tag_end(html, lt)
        if gt == -1 or gt < pos:
            continue
        return lt


def build_inner(inner, value):
    """重建 data-i18n 元素内部：保留子标签结构，仅替换顶层文本节点为 value。"""
    if '<' not in inner:
        return value
    tokens = re.split(r'(<[^>]*>)', inner)
    depth = 0
    out = []
    inserted = False
    for tok in tokens:
        if tok.startswith('<'):
            out.append(tok)
            if tok.startswith('<!--') or tok.startswith('<!') \
                    or tok.startswith('<?'):
                continue
            if tok.startswith('</'):
                depth = max(0, depth - 1)
            else:
                name_m = re.match(r'<([a-zA-Z][a-zA-Z0-9]*)', tok)
                if not name_m:
                    continue
                if tok.rstrip().endswith('/>') \
                        or name_m.group(1).lower() in VOID_TAGS:
                    continue
                depth += 1
        else:
            if depth == 0:
                if not inserted:
                    out.append(value)
                    inserted = True
                elif tok.strip():
                    out.append('')
            else:
                out.append(tok)
    return ''.join(out)


def html_escape(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# ============ translations 解析 ============

TRANS_RE = re.compile(r'(?:const|var|let)\s+translations\s*=\s*(\{.*?\});', re.S)
LANG_BLOCK_RE = re.compile(r'^\s*(%s)\s*:\s*\{' % '|'.join(ALL_LANGS), re.M)


def find_matching_brace(s, start):
    """s[start] 指向 '{' 之后，返回与之匹配的 '}' 位置。"""
    depth = 1  # 语言块自身的 '{' 已在 start 之前被消耗
    in_dq = in_sq = False
    i = start
    n = len(s)
    while i < n:
        ch = s[i]
        if in_dq:
            if ch == '\\':
                i += 2
                continue
            if ch == '"':
                in_dq = False
        elif in_sq:
            if ch == '\\':
                i += 2
                continue
            if ch == "'":
                in_sq = False
        elif ch == '"':
            in_dq = True
        elif ch == "'":
            in_sq = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def parse_simple_keys(block):
    """解析语言块（不含外层 {}），提取顶层简单 `key: 'value'` 对。"""
    result = {}
    n = len(block)
    depths = [0] * n
    in_strs = [False] * n
    in_str = False
    str_ch = ''
    depth = 0
    i = 0
    while i < n:
        depths[i] = depth
        in_strs[i] = in_str
        ch = block[i]
        if in_str:
            if ch == '\\':
                # 转义字符：下一个字符仍在字符串内
                if i + 1 < n:
                    depths[i + 1] = depth
                    in_strs[i + 1] = True
                i += 2
                continue
            if ch == str_ch:
                in_str = False
            i += 1
            continue
        if ch in '"\'':
            in_str = True
            str_ch = ch
        elif ch in '{[':
            depth += 1
        elif ch in '}]':
            depth -= 1
        i += 1

    kv_re = re.compile(r"([A-Za-z_$][\w$]*)\s*:\s*'((?:[^'\\]|\\.)*)'")
    for m in kv_re.finditer(block):
        pos = m.start()
        if pos < n and depths[pos] == 0 and not in_strs[pos]:
            key = m.group(1)
            value = (m.group(2)
                     .replace('\\\\', '\\')
                     .replace("\\'", "'"))
            if key not in result:
                result[key] = value
    return result


def extract_translations(html):
    """从页面 JS 中提取 {lang: {key: value}}。"""
    m = TRANS_RE.search(html)
    if not m:
        return {}
    block = m.group(1)
    result = {}
    for lm in LANG_BLOCK_RE.finditer(block):
        lang = lm.group(1)
        end = find_matching_brace(block, lm.end())
        if end == -1:
            continue
        result[lang] = parse_simple_keys(block[lm.end():end])
    return result


# ============ 正文替换 ============

ATTR_I18N_RE = re.compile(r'data-i18n="([^"]+)"')


def replace_data_i18n(html, t):
    """替换所有 [data-i18n] 元素文本（保留子标签结构）。"""
    for m in reversed(list(ATTR_I18N_RE.finditer(html))):
        key = m.group(1)
        value = t.get(KEY_ALIASES.get(key, key))
        if value is None:
            continue
        lt = find_open_tag_start(html, m.start())
        if lt == -1:
            continue
        tag_m = re.match(r'<([a-zA-Z][a-zA-Z0-9]*)', html[lt:])
        if not tag_m:
            continue
        tag = tag_m.group(1)
        gt = find_tag_end(html, lt)
        if gt == -1:
            continue
        close = find_element_close(html, gt + 1, tag)
        if close == -1:
            continue
        gt_close = find_tag_end(html, close)
        if gt_close == -1:
            continue
        inner = html[gt + 1:close]
        new_inner = build_inner(inner, value)
        html = (html[:lt] + html[lt:gt + 1] + new_inner
                + html[close:gt_close + 1] + html[gt_close + 1:])
    return html


PH_RE = re.compile(r'data-i18n-placeholder="([^"]+)"')


def replace_placeholder(html, t):
    """替换 [data-i18n-placeholder] 元素的 placeholder 属性。"""
    for m in reversed(list(PH_RE.finditer(html))):
        key = m.group(1)
        value = t.get(KEY_ALIASES.get(key, key))
        if value is None:
            continue
        lt = find_open_tag_start(html, m.start())
        if lt == -1:
            continue
        gt = find_tag_end(html, lt)
        if gt == -1:
            continue
        tag_html = html[lt:gt + 1]
        new_tag = re.sub(r'placeholder="[^"]*"',
                         'placeholder="%s"' % value, tag_html, count=1)
        if new_tag == tag_html:
            new_tag = re.sub(r'(<[a-zA-Z][a-zA-Z0-9]*[^>]*?)(/?>)',
                             r'\1 placeholder="%s"\2' % value, tag_html, count=1)
        html = html[:lt] + new_tag + html[gt + 1:]
    return html


def replace_attr(html, attr_i18n, attr_target, t):
    """替换 data-i18n-{attr_i18n} 指向的元素属性 {attr_target}（如 alt/title）。"""
    regex = re.compile(r'data-%s="([^"]+)"' % attr_i18n)
    for m in reversed(list(regex.finditer(html))):
        key = m.group(1)
        value = t.get(KEY_ALIASES.get(key, key))
        if value is None:
            continue
        lt = find_open_tag_start(html, m.start())
        if lt == -1:
            continue
        gt = find_tag_end(html, lt)
        if gt == -1:
            continue
        tag_html = html[lt:gt + 1]
        new_tag = re.sub(r'%s="[^"]*"' % attr_target,
                         '%s="%s"' % (attr_target, value), tag_html, count=1)
        html = html[:lt] + new_tag + html[gt + 1:]
    return html


# ============ head 重写 ============

def path_for(lang, page):
    """语言路径（相对站点根）：'en/index.html' / 'index.html'。"""
    return '%s/%s' % (lang, page) if lang != 'zh' else page


def url_for(lang, page):
    return '%s/%s' % (BASE_URL, path_for(lang, page))


LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def rewrite_jsonld(html, t):
    """翻译 JSON-LD：FAQPage 的 Question/Answer 用 qN_title/qN_body 键；
    Organization 保留企业专有名词，仅在翻译键存在时翻译地址字段。"""
    def repl(m):
        block = m.group(1)
        try:
            data = json.loads(block)
        except Exception:
            return m.group(0)
        changed = False
        if isinstance(data, dict) and data.get('@type') == 'FAQPage':
            main = data.get('mainEntity') or []
            for i, item in enumerate(main, start=1):
                if not (isinstance(item, dict)
                        and item.get('@type') == 'Question'):
                    continue
                tk, bk = 'q%d_title' % i, 'q%d_body' % i
                if tk in t:
                    item['name'] = t[tk]
                    changed = True
                ans = item.get('acceptedAnswer')
                if bk in t and isinstance(ans, dict):
                    ans['text'] = t[bk]
                    changed = True
        elif isinstance(data, dict) and data.get('@type') == 'Organization':
            addr = data.get('address')
            if isinstance(addr, dict):
                for src, dst in (('addr_locality', 'addressLocality'),
                                 ('addr_region', 'addressRegion'),
                                 ('addr_street', 'streetAddress')):
                    if src in t and dst in addr:
                        addr[dst] = t[src]
                        changed = True
        if not changed:
            return m.group(0)
        return ('<script type="application/ld+json">\n'
                + json.dumps(data, ensure_ascii=False, indent=2)
                + '\n    </script>')
    return LD_RE.sub(repl, html)


def rewrite_head(html, lang, page, t):
    # <html lang="...">，ar 追加 dir="rtl"
    html = re.sub(r'<html\s+lang="[^"]*"', '<html lang="%s"' % LANG_ATTR[lang],
                  html, count=1)
    if lang == 'ar':
        html = re.sub(r'(<html\s+lang="[^"]*")', r'\1 dir="rtl"', html, count=1)

    # canonical
    html = re.sub(r'<link rel="canonical" href="[^"]*">',
                  '<link rel="canonical" href="%s">' % url_for(lang, page),
                  html, count=1)

    # hreflang：删除旧链后重新生成
    html = re.sub(r'[ \t]*<link rel="alternate" hreflang="[^"]*"[^>]*>\r?\n?',
                  '', html)
    links = []
    for l in ALL_LANGS:
        links.append('    <link rel="alternate" hreflang="%s" href="%s">'
                     % (l, url_for(l, page)))
    links.append('    <link rel="alternate" hreflang="x-default" href="%s">'
                 % url_for('zh', page))
    block = '\n'.join(links)
    html = re.sub(r'(<link rel="canonical" href="[^"]*">)',
                  r'\1\n' + block, html, count=1)

    # title
    if t.get('page_title'):
        html = re.sub(r'<title>[^<]*</title>',
                      '<title>%s</title>' % html_escape(t['page_title']),
                      html, count=1)

    # meta description
    desc = (t.get('meta_desc')
            or (t.get('banner_desc')
                and '%s - %s' % (t.get('banner_title', ''), t['banner_desc']))
            or t.get('page_title') or '')
    if desc:
        html = re.sub(r'<meta name="description" content="[^"]*">',
                      '<meta name="description" content="%s">'
                      % html_escape(desc), html, count=1)

    # JSON-LD
    html = rewrite_jsonld(html, t)
    return html


# ============ 语言切换器 ============

LANG_OPTION_RE = re.compile(
    r'<a\s+class="lang-option[^"]*"\s+data-lang="(\w+)"(?:\s+data-flag="([^"]*)")?\s+href="([^"]*)"([^>]*)>(.*?)</a>',
    re.S)


def rewrite_lang_switcher(html, lang, page):
    # 当前语言显示
    html = re.sub(r'<span class="lang-flag" id="currentFlag">[^<]*</span>',
                  '<span class="lang-flag" id="currentFlag">%s</span>'
                  % FLAG_MAP[lang], html, count=1)
    html = re.sub(r'<span id="currentLang">[^<]*</span>',
                  '<span id="currentLang">%s</span>' % LANG_NAMES[lang],
                  html, count=1)

    def repl(m):
        opt_lang, flag, href, rest, label = (m.group(1), m.group(2),
                                             m.group(3), m.group(4), m.group(5))
        if not flag:
            flag = FLAG_MAP.get(opt_lang, '🌐')
        if opt_lang == lang:
            href = page
        elif opt_lang == 'zh':
            href = '../' + page
        else:
            href = '../%s/%s' % (opt_lang, page)
        cls = 'lang-option active' if opt_lang == lang else 'lang-option'
        return ('<a class="%s" data-lang="%s" data-flag="%s" href="%s"%s>%s</a>'
                % (cls, opt_lang, flag, href, rest, label))

    return LANG_OPTION_RE.sub(repl, html)


# ============ JS 修正 ============

def _skip_call_chain(html, pos):
    """pos 指向 fetch 开头。返回整个 fetch(...).then(...).catch(...) 链的结束位置。"""
    op = html.find('(', pos)
    if op == -1:
        return len(html)
    end = _match_paren(html, op) + 1
    while True:
        m = re.match(r'\s*\.\s*(?:then|catch)\s*\(', html[end:])
        if not m:
            break
        op = html.find('(', end + m.start())
        end = _match_paren(html, op) + 1
    return end


IPAPI_RE = re.compile(r"fetch\s*\(\s*['\"]https?://ipapi\.co/json/['\"]")


def remove_ip_detection(html):
    """移除 IP 检测代码（ipapi 自动检测与重定向），兼容两种形态：
      1) fetch('https://ipapi.co/json/').then(...).then(...);
      2) var resp = await fetch('https://ipapi.co/json/'); var data = await resp.json(); ...
    """
    pos = 0
    while True:
        m = IPAPI_RE.search(html, pos)
        if not m:
            break
        start = m.start()
        end = _skip_call_chain(html, start)
        # 吃掉 "var x = " / "await " 前缀
        seg = html[:start]
        pm = re.search(r'(?:var\s+\w+\s*=\s*|await\s+)\s*$', seg)
        if pm:
            start = pm.start()
        # 吃掉 "; var data = await resp.json();" 后缀
        tail = html[end:end + 120]
        tm = re.match(r'\s*;\s*var\s+\w+\s*=\s*await\s+\w+\.json\(\)\s*;', tail)
        if tm:
            end = end + tm.end()
        html = html[:start] + html[end:]
        pos = start
    return html


def fix_js(html, lang):
    # currentLang / storedLang 固定为目标语言
    html = re.sub(r"((?:let|var)\s+currentLang\s*=\s*)'[a-z]{2,3}'",
                  r"\g<1>'%s'" % lang, html)
    html = re.sub(r"^(\s*)currentLang\s*=\s*'[a-z]{2,3}';",
                  r"\g<1>currentLang = '%s';" % lang, html, flags=re.M)
    html = re.sub(r"(\bvar\s+storedLang\s*=\s*)'[a-z]{2,3}'",
                  r"\g<1>'%s'" % lang, html)
    # 移除 IP 检测 JS（若模板仍包含）
    html = remove_ip_detection(html)
    return html


# ============ 相对路径 ============

def fix_relative_paths(html):
    """站内相对资源链接增加 ../ 前缀（images 等子目录资源）。

    页面导航链接 href="xxx.html" 保持相对路径：生成页面位于 <lang>/ 子目录，
    同目录下的相对链接自然解析到 <lang>/xxx.html 同语言版本；
    若加 ../ 会指向根目录的中文版（错误）。资源链接则必须加 ../ 才能
    从 <lang>/ 子目录回退到根目录的 images/。
    """
    # 图片等资源：src/href="images/..."
    html = re.sub(r'((?:src|href)=")(images/)([^"]*")',
                  r'\g<1>../images/\3', html)
    # CSS url('images/...') / url("images/...")
    html = re.sub(r"(url\(\s*['\"]?)(images/)", r'\g<1>../images/', html)
    return html


# ============ 校验 ============

def verify_page(html, lang, page):
    """对生成页面做基础校验，返回问题数。"""
    issues = 0

    def check(cond, msg):
        nonlocal issues
        if not cond:
            print('    ! %s' % msg)
            issues += 1

    check('<html lang="%s"' % LANG_ATTR[lang] in html,
          '<html lang> 未设置 %s' % LANG_ATTR[lang])
    if lang == 'ar':
        check('dir="rtl"' in html[:400], 'ar 页面缺少 dir="rtl"')
    check(url_for(lang, page) in html, 'canonical 未指向 %s' % url_for(lang, page))
    for l in ALL_LANGS + ['x-default']:
        check('hreflang="%s"' % l in html, '缺少 hreflang=%s' % l)
    check(not re.search(r'ipapi', html), '残留 ipapi 检测代码')
    check(not re.search(r"localStorage\.getItem\('js-lang'\)", html),
          '残留 localStorage 语言检测')
    check(not re.search(r'<link rel="canonical"[^>]*hreflang', html),
          'canonical/hreflang 结构异常')
    # 语言变量固定
    check(not re.search(r"(let\s+|var\s+)?currentLang\s*=\s*'[a-zA-Z]{2,3}'",
                        html.replace("'%s'" % lang, ''))
          or "'%s'" % lang in html, 'currentLang 未固定为 %s' % lang)
    # 语言切换器 active 状态
    check('lang-option active" data-lang="%s"' % lang in html,
          '语言切换器 active 不在 %s 上' % lang)
    check(not re.search(r'lang-option active" data-lang="(?!%s)' % lang, html),
          '存在多个 active 语言选项')
    # 页面导航不得指向根目录中文版（../xxx.html）；排除语言切换器
    nav_only = LANG_OPTION_RE.sub('', html)
    check(not re.search(
        r'href="\.\./(?:index|about|products|contact|faq|market-insight)'
        r'\.html(?:#|")', nav_only),
        '存在指向根目录中文版的导航链接（../xxx.html）')
    # title 残留中文（ja 日文汉字正常，跳过）
    m = re.search(r'<title>([^<]*)</title>', html)
    if lang != 'ja' and m:
        check(not re.search(r'[\u4e00-\u9fff]', m.group(1)),
              'title 残留中文: %s' % m.group(1)[:40])
    # data-i18n 元素残留 CJK（ja 跳过；地址等专有名词白名单）
    if lang != 'ja':
        whitelist = ('山东省', '聊城市', '经济技术开发区', '兴隆钢材市场',
                     '山东', '青岛', '天津', '上海', '全国', '中', '国')
        for el_m in ATTR_I18N_RE.finditer(html):
            # 简单检查该元素内部文本是否残留中文（排除白名单片段）
            lt = find_open_tag_start(html, el_m.start())
            if lt == -1:
                continue
            tag_m = re.match(r'<([a-zA-Z][a-zA-Z0-9]*)', html[lt:])
            if not tag_m:
                continue
            gt = find_tag_end(html, lt)
            close = find_element_close(html, gt + 1, tag_m.group(1))
            if close == -1:
                continue
            inner = html[gt + 1:close]
            cjk = re.findall(r'[\u4e00-\u9fff]{2,}', inner)
            cjk = [c for c in cjk if c not in whitelist]
            if cjk:
                print('    ! data-i18n "%s" 残留中文: %s'
                      % (el_m.group(1), cjk[:3]))
                issues += 1
    return issues


# ============ 生成流程 ============

def generate_language(lang, src_dir=None, out_dir=None, silent=False):
    src_dir = src_dir or ROOT
    out_dir = out_dir or ROOT
    lang_dir = os.path.join(out_dir, lang)
    os.makedirs(lang_dir, exist_ok=True)
    total_issues = 0
    for page in PAGES:
        path = os.path.join(src_dir, page)
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8') as f:
            html = f.read()
        translations = extract_translations(html)
        t = translations.get(lang)
        if not t:
            print('[SKIP] %s: 未找到 %s 语言翻译' % (page, lang))
            continue
        # 1) 正文文本替换
        html = replace_data_i18n(html, t)
        html = replace_placeholder(html, t)
        html = replace_attr(html, 'i18n-alt', 'alt', t)
        html = replace_attr(html, 'i18n-title', 'title', t)
        # 2) 相对路径 + 语言切换器（切换器最后处理以覆盖路径）
        html = fix_relative_paths(html)
        html = rewrite_lang_switcher(html, lang, page)
        # 3) head 元数据
        html = rewrite_head(html, lang, page, t)
        # 4) JS 语言变量固定 + 移除 IP 检测
        html = fix_js(html, lang)
        # 写出
        out_path = os.path.join(lang_dir, page)
        with open(out_path, 'w', encoding='utf-8', newline='') as f:
            f.write(html)
        issues = verify_page(html, lang, page)
        total_issues += issues
        if not silent:
            print('  %-16s %-3s  issues=%d' % (page, lang, issues))
    return total_issues


def verify_existing(lang):
    lang_dir = os.path.join(ROOT, lang)
    total = 0
    for page in PAGES:
        path = os.path.join(lang_dir, page)
        if not os.path.exists(path):
            print('  [缺失] %s/%s' % (lang, page))
            total += 1
            continue
        with open(path, encoding='utf-8') as f:
            html = f.read()
        issues = verify_page(html, lang, page)
        total += issues
        print('  %-16s %-3s  issues=%d' % (page, lang, issues))
    return total


# ============ 自检 ============

def run_self_test():
    print('== 自检：IP 检测移除 ==')
    samples = [
        # 形态1：fetch(...).then 链
        ("<script>var saved=localStorage.getItem('js-lang');"
         "if(saved){applyLanguage(saved);}else{"
         "fetch('https://ipapi.co/json/')"
         ".then(function(r){return r.json();})"
         ".then(function(d){var c=(d.country_code||'').toLowerCase();"
         "if(c==='de')applyLanguage('de');});"
         "}</script>", '形态1 fetch().then 链'),
        # 形态2：await fetch + resp.json
        ("<script>(async function(){"
         "var resp=await fetch('https://ipapi.co/json/');"
         "var data=await resp.json();"
         "var c=(data.country_code||'').toUpperCase();"
         "if(['DE','FR','ES','JA','AR'].indexOf(c)>-1)"
         "{setLanguage(c.toLowerCase());}"
         "})();</script>", '形态2 await fetch'),
        # 不应误删的正常代码
        ("<script>fetch('/api/contact').then(function(r){return r.json();});"
         "</script>", '保留正常 fetch'),
    ]
    ok = True
    for html, name in samples:
        out = remove_ip_detection(html)
        if 'ipapi' in out:
            print('  [FAIL] %s 仍含 ipapi' % name)
            ok = False
        else:
            print('  [PASS] %s' % name)
    print('== 自检完成 ==')
    sys.exit(0 if ok else 1)


# ============ 主入口 ============

def main():
    ap = argparse.ArgumentParser(description='多语言静态页面生成脚本')
    ap.add_argument('--langs', default=None,
                    help='逗号分隔的目标语言，默认全部: ' + ','.join(LANGS))
    ap.add_argument('--verify', action='store_true',
                    help='仅校验已生成文件，不重新生成')
    ap.add_argument('--self-test', action='store_true',
                    help='运行内置自检后退出')
    args = ap.parse_args()

    if args.self_test:
        run_self_test()
        return

    langs = ([l.strip() for l in args.langs.split(',') if l.strip()]
             if args.langs else list(LANGS))
    langs = [l for l in langs if l in LANGS]

    if args.verify:
        print('== 校验已生成的语言版本 ==')
        for lang in langs:
            issues = verify_existing(lang)
            print('  %s: %d issues' % (lang, issues))
        return

    print('== 生成多语言静态页面 ==')
    for lang in langs:
        issues = generate_language(lang)
        print('  [%s] 完成，issues=%d' % (lang, issues))


if __name__ == '__main__':
    main()
