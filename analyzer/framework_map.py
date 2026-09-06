#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
framework_map.py — Spring Boot + MyBatis(-Plus) 框架调用链提取器（阶段0 增强版）

零依赖、纯正则。扫描 src/main/java 下的 Java 源码，把框架的“隐式约定”
变成显式的调用链：
    HTTP 路由 -> Controller 方法 -> Service 实现 -> Mapper 方法 -> 注解 SQL

增强能力：
  1. 事务影响面：@Transactional 闭包（事务边界传播）+ 事务内数据库写操作清单
  2. 实体↔表↔SQL 联动：改实体字段会影响哪些 SQL / 哪些链路
  3. 逆向索引：Mapper 方法 / SQL 反查上游调用路由
  4. JSON 结构化输出：为阶段1 MCP Server 准备机器可读数据

用法:
    python framework_map.py <项目根目录> [输出文件.md]

注意：MVP 用正则级解析，不追求 100% 语法正确，目标是“地图够准、够用”。
"""
import os
import re
import sys
import json
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(SCRIPT_DIR, "framework_map.md")
OUT_JSON = os.path.splitext(OUT)[0] + ".json"
JAVA_SRC = os.path.join(ROOT, "src", "main", "java")
RESOURCES = os.path.join(ROOT, "src", "main", "resources")
# 跟 application.yml 里 mybatis-plus.mapper-locations: classpath*:mapper/**/*.xml 对齐
XML_MAPPER_DIRS = [os.path.join(RESOURCES, "mapper")]

# 路由注解 -> HTTP 方法
MAPPING_ANN = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
    "RequestMapping": "ANY",
}
# 没有 HTTP 入口、但会被框架“悄悄调用”的隐藏入口
HIDDEN_ANN = ["Scheduled", "KafkaListener", "RabbitListener", "RocketMQMessageListener",
              "EventListener", "PostConstruct", "Around", "Before", "After", "AfterReturning"]
# MyBatis-Plus BaseMapper / IService 的内置方法（不需要写 SQL 的那种）
MP_BUILTIN = {
    "insert", "deleteById", "deleteByIds", "deleteByMap", "delete", "updateById", "update",
    "selectById", "selectBatchIds", "selectByMap", "selectOne", "selectCount", "selectList",
    "selectPage", "selectMaps", "selectObjs", "selectMapsPage", "exists",
    "save", "saveBatch", "saveOrUpdate", "saveOrUpdateBatch", "updateBatchById",
    "removeById", "removeByIds", "removeByMap", "remove", "getById", "getOne",
    "list", "page", "count", "listByIds", "lambdaQuery", "lambdaUpdate",
}
MP_WRITE = {
    "insert", "deleteById", "deleteByIds", "deleteByMap", "delete", "updateById", "update",
    "save", "saveBatch", "saveOrUpdate", "saveOrUpdateBatch", "updateBatchById",
    "removeById", "removeByIds", "removeByMap", "remove",
}
SQL_ANN = {"Select": "SELECT", "Update": "UPDATE", "Insert": "INSERT", "Delete": "DELETE"}


# ---------------------------------------------------------------- 基础工具

def strip_code(src):
    """把注释和字符串字面量原地替换成等长空白。
    替换后位置和原文一一对应，方便“干净文本定位、原始文本取内容”。"""
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        two = src[i:i + 2]
        three = src[i:i + 3]
        if three == '"""':  # 文本块
            out[i] = out[i + 1] = out[i + 2] = " "
            i += 3
            while i < n and src[i:i + 3] != '"""':
                i += 1
            if i < n:
                out[i] = out[i + 1] = out[i + 2] = " "
                i += 3
            continue
        if two == "//":
            while i < n and src[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if two == "/*":
            out[i] = out[i + 1] = " "
            i += 2
            while i < n and src[i:i + 2] != "*/":
                if src[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = out[i + 1] = " "
                i += 2
            continue
        if src[i] == '"':
            out[i] = " "
            i += 1
            while i < n and src[i] != '"':
                if src[i] == "\\":
                    out[i] = " "
                    if i + 1 < n:
                        out[i + 1] = " "
                    i += 2
                    continue
                if src[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = " "
                i += 1
            continue
        if src[i] == "'":
            out[i] = " "
            i += 1
            while i < n and src[i] != "'":
                if src[i] == "\\":
                    i += 2
                    continue
                i += 1
            if i < n:
                out[i] = " "
                i += 1
            continue
        i += 1
    return "".join(out)


def match_brace(text, open_idx):
    """从 text[open_idx] == '{' 开始，返回配对 '}' 的下标。"""
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def first_string(text):
    """取注解参数里第一个字符串字面量的内容。"""
    m = re.search(r'"((?:[^"\\]|\\.)*)"', text)
    return m.group(1) if m else ""


def ann_args(raw_text, ann_name):
    """从原始文本里抠出 @Ann(...) 的括号内容（做括号配对，支持嵌套）。"""
    m = re.search(r"@" + ann_name + r"\s*\(", raw_text)
    if not m:
        return None
    start = raw_text.index("(", m.start())
    depth = 0
    for i in range(start, len(raw_text)):
        if raw_text[i] == "(":
            depth += 1
        elif raw_text[i] == ")":
            depth -= 1
            if depth == 0:
                return raw_text[start + 1:i]
    return None


def extract_sql(ann_raw):
    """从方法注解原文里提取 @Select/@Update/... 的 SQL（处理字符串拼接）。"""
    for name, kw in SQL_ANN.items():
        m = re.search(r"@" + name + r"\s*\(", ann_raw)
        if not m:
            continue
        start = ann_raw.index("(", m.start())
        depth = 0
        end = start
        for i in range(start, len(ann_raw)):
            if ann_raw[i] == "(":
                depth += 1
            elif ann_raw[i] == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        args = ann_raw[start + 1:end]
        parts = re.findall(r'"((?:[^"\\]|\\.)*)"', args)
        if parts:
            sql = " ".join(p.strip() for p in parts)
            sql = re.sub(r"\s+", " ", sql)
            return kw, sql
    return None


def camel_to_snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def mp_builtin_sql_record(method_name, entity):
    """给 MyBatis-Plus 内置方法造一份"合成 sql 记录"。
    selectById 底层就是 SELECT *，insert/updateById 是全表写——都触碰实体的所有列。
    有了它，impact 字段级查询就能正确判定这些方法碰了哪个列，不再报"列未知"。
    实体没解析出列（无 @TableName / entity_columns 为 None）→ 返回 None，保留旧语义，不崩。"""
    if not entity or not entity.get("entity_columns"):
        return None
    table = entity["table_name"]
    if method_name in MP_WRITE:
        # 注意判断顺序：saveOrUpdate* 要先于 save*；delete/remove 走 DELETE
        if method_name.startswith("saveOrUpdate"):
            kind = "UPDATE"
        elif method_name.startswith("save") or method_name == "insert":
            kind = "INSERT"
        elif method_name.startswith("delete") or method_name.startswith("remove"):
            kind = "DELETE"
        else:
            kind = "UPDATE"
        text = f"(MyBatis-Plus 内置 {kind} 全表写)"
    else:
        # 读方法：selectById/selectList/selectOne/selectCount/selectBatchIds/...
        #       getById/getOne/list/listByIds/count/exists/selectMaps/selectObjs/
        #       selectPage/selectMapsPage/lambdaQuery/page 等
        kind = "SELECT"
        text = "(MyBatis-Plus 内置 SELECT *)"
    cols = [f"{table}.{col} ({entity['name']}.{fname})"
            for fname, col in entity["entity_columns"].items()]
    return {
        "kind": kind,
        "text": text,
        "tables": [table],
        "columns": sorted(cols),
        "mp_builtin": True,
    }


def parse_xml_mappers(resources_dir, table_to_entity, entity_by_simple):
    """扫描 src/main/resources/mapper/**/*.xml，解析 <resultMap>/<sql> 片段、
    做 <include refid> 替换，给 <select>/<insert>/<update>/<delete> 补一份 sql 记录。
    返回 {f"{MapperClass}#{methodId}": sql_record}；没 XML 文件就返回 {}。
    只用 stdlib ElementTree，不引入外部依赖。"""
    mapper_dir = os.path.join(resources_dir, "mapper")
    if not os.path.isdir(mapper_dir):
        return {}
    import xml.etree.ElementTree as ET
    out = {}
    for dirpath, _dn, filenames in os.walk(mapper_dir):
        for fn in filenames:
            if not fn.endswith(".xml"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                tree = ET.parse(path)
            except ET.ParseError:
                # 损坏的 XML 文件直接跳过，不中断整体扫描
                continue
            root = tree.getroot()
            ns = root.get("namespace", "")
            # com.xxx.SysUserMapper → SysUserMapper；空 namespace 没法匹配 Java 接口，等同跳过
            mapper_class = ns.rsplit(".", 1)[-1] if ns else ""
            if not mapper_class:
                continue
            # 第一遍：收集 <sql id> 片段
            fragments = {}
            for sf in root.findall("sql"):
                fid = sf.get("id")
                if fid:
                    fragments[fid] = " ".join(sf.itertext()).strip()
            # 第二遍：收集 <resultMap>（column → property 映射 + 关联实体）
            result_maps = {}
            for rm in root.findall("resultMap"):
                rid = rm.get("id")
                if not rid:
                    continue
                rtype = (rm.get("type") or "").rsplit(".", 1)[-1]
                col_prop = {}
                for r in rm.findall("result"):
                    c = r.get("column")
                    p = r.get("property")
                    if c and p:
                        col_prop[c] = p
                for r in rm.findall("id"):  # <id column="..." property="..."/>
                    c = r.get("column")
                    p = r.get("property")
                    if c and p:
                        col_prop[c] = p
                result_maps[rid] = (rtype, col_prop)
            # 第三遍：四类语句
            for tag, kind in (("select", "SELECT"), ("insert", "INSERT"),
                              ("update", "UPDATE"), ("delete", "DELETE")):
                for stmt in root.findall(tag):
                    mid = stmt.get("id")
                    if not mid:
                        continue
                    # <include refid="..."/> 替换为片段文本
                    body_parts = []
                    for el in stmt.iter():
                        if el.tag == "include":
                            ref = el.get("refid")
                            if ref and ref in fragments:
                                body_parts.append(fragments[ref])
                                continue
                        # 只取文本节点（itertext 会拼所有文本，include 已手动处理）
                    # 先做 include 替换再拼文本
                    raw_xml = ET.tostring(stmt, encoding="unicode")
                    # 简单做：用正则把 <include refid="x"/> 换成片段文本
                    def _inc(m):
                        r = m.group(1)
                        return fragments.get(r, m.group(0))
                    raw_xml = re.sub(r'<include\s+refid="([^"]+)"\s*/>', _inc, raw_xml)
                    # 去标签，只留文本
                    sql_text = re.sub(r"<[^>]+>", " ", raw_xml)
                    sql_text = re.sub(r"\s+", " ", sql_text).strip()
                    if not sql_text:
                        body_parts.clear()
                        sql_text = " ".join(stmt.itertext())
                        sql_text = re.sub(r"\s+", " ", sql_text).strip()
                    tables = list(dict.fromkeys(t.lower() for t in SQL_TABLE_RE.findall(sql_text)))
                    cols = []
                    rm_attr = stmt.get("resultMap")
                    primary_table = tables[0] if tables else None
                    ent = table_to_entity.get(primary_table) if primary_table else None
                    if rm_attr and rm_attr in result_maps:
                        # 有 resultMap：用它的 column 列表拼触碰列
                        _rtype, col_prop = result_maps[rm_attr]
                        target_ent = entity_by_simple.get(_rtype) or ent
                        if target_ent and target_ent.get("entity_columns"):
                            inv = {col: prop for prop, col in target_ent["entity_columns"].items()}
                            tname = target_ent["table_name"]
                            for c in col_prop:
                                fname = inv.get(c)
                                if fname:
                                    cols.append(f"{tname}.{c} ({target_ent['name']}.{fname})")
                        else:
                            t = primary_table or ""
                            for c in col_prop:
                                cols.append(f"{t}.{c} ({_rtype}.{col_prop[c]})")
                    else:
                        # 无 resultMap：走统一列解析（字面列名 + SELECT * / 别名星号展开）
                        cols.extend(resolve_sql_columns(sql_text, tables, table_to_entity))
                    out[f"{mapper_class}#{mid}"] = {
                        "kind": kind,
                        "text": sql_text,
                        "tables": tables,
                        "columns": sorted(set(cols)),
                        "mp_builtin": False,
                    }
    return out


# SQL 里 FROM/JOIN 后面紧跟的词如果是这些关键字，说明那张表没起别名
_SQL_KEYWORDS = {"where", "order", "group", "left", "right", "inner", "outer",
                 "cross", "join", "on", "limit", "set", "values", "having",
                 "by", "asc", "desc", "and", "or", "as", "distinct", "union"}


def resolve_sql_columns(sql, tables, table_to_entity):
    """解析一条 SQL 触碰了哪些实体列，返回 ["table.col (Entity.field)", ...]。
    三种来源叠加（去重）：
      1. 列名在 SQL 文本里字面出现（WHERE/JOIN ON/SELECT 列名）；
      2. 裸 SELECT *：多表 JOIN 时对所有表都展开为该表实体全列；
      3. 别名星号 g.* / o.* / j.*：先建 FROM/JOIN 的 别名→表名 映射，再展开对应表全列。
    COUNT(*) 不碰业务列（正则要求星号前是 SELECT 或 别名.，不会误判）。"""
    sql_for_cols = re.sub(r"\bAS\s+\w+", "", sql, flags=re.IGNORECASE)
    # 别名 -> 表名：FROM tab [AS] x / JOIN tab [AS] x
    alias_map = {}
    for tm in re.finditer(r"\b(?:from|join)\s+([a-zA-Z_]\w*)(?:\s+(?:as\s+)?([a-zA-Z_]\w*))?",
                         sql_for_cols, flags=re.IGNORECASE):
        tname = tm.group(1).lower()
        alias = tm.group(2)
        if alias and alias.lower() not in _SQL_KEYWORDS:
            alias_map[alias.lower()] = tname
    star_aliases = {a.lower() for a in re.findall(r"(\w+)\.\*", sql_for_cols)}
    bare_star = bool(re.search(r"\bSELECT\s+\*", sql_for_cols, re.IGNORECASE))
    cols = []
    for t in tables:
        ent = table_to_entity.get(t)
        if not ent or not ent.get("entity_columns"):
            continue
        # 这张表是否被星号覆盖：裸 * 或它的别名出现在 x.* 里
        star = bare_star or any(alias_map.get(a) == t for a in star_aliases)
        for fname, col in ent["entity_columns"].items():
            if star or re.search(r"\b" + re.escape(col) + r"\b", sql_for_cols):
                cols.append(f"{t}.{col} ({ent['name']}.{fname})")
    return sorted(set(cols))


def collapse_ann_args(text):
    """把 @Ann(...) 连括号一起等长抹成空白（保留位置）。
    目的：让 METHOD_RE 的参数组可以用线性匹配 [^()]*，杜绝灾难性回溯；
    同时参数内的注解（如 @RequestParam(value="x")）不再残留括号，路由方法不丢。
    基于已 strip_code 的文本（字符串字面量已是空白），括号配对扫描是安全的。"""
    out = list(text)
    for m in re.finditer(r"@\w[\w.]*\s*\(", text):
        open_idx = m.end() - 1  # '(' 的位置
        start = m.end()         # '(' 之后
        depth = 1
        i = start
        while i < len(text) and depth > 0:
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    out[open_idx] = " "  # 连括号一起抹掉
                    out[i] = " "
                    break
            if depth > 0 and ch != "\n":
                out[i] = " "
            i += 1
    return "".join(out)


def scan_methods(text, class_name):
    """线性扫描方法/构造器声明。text 为注解参数已折叠的类体副本。

    返回 [{"ann_start", "name", "name_start", "open", "close", "end_char", "term"}]，
    偏移均相对 text；term 是 '{' 或 ';' 的下标。
    全程线性：候选定位（finditer）→ 向前配对括号 → 向后回吞头部验证。
    """
    out = []
    n = len(text)
    for m in CANDIDATE.finditer(text):
        name = m.group(1)
        if name in NAME_REJECT:
            continue
        name_start = m.start(1)
        open_p = m.end() - 1                     # '(' 下标
        # 向前配对括号
        depth = 1
        i = open_p + 1
        while i < n and depth > 0:
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        if depth != 0:
            continue                             # 括号不闭合，跳过
        close_p = i - 1                          # ')' 下标
        # ')' 之后：可选 throws 子句，然后必须是 '{' 或 ';'
        j = i
        while j < n and text[j] in " \t\r\n":
            j += 1
        if text[j:j + 6] == "throws" and (j + 6 >= n or text[j + 6] in " \t\r\n"):
            j += 6
            while j < n and text[j] not in "{;":
                j += 1
        if j >= n or text[j] not in "{;":
            continue
        # 头部回吞：修饰符/注解/返回类型（遇语句边界或非法字符停）
        hs = name_start
        while hs > 0 and text[hs - 1] in HEADER_CHARS:
            hs -= 1
        header = text[hs:name_start].strip()
        if header and not re.fullmatch(r"[\w<>\[\],.?&@\s]+", header):
            continue                             # 头部含非法字符（=> 等号/点号/箭头等，是调用）
        words = header.split()
        last = words[-1] if words else ""
        if last in RET_KEYWORDS or last in NAME_REJECT:
            continue                             # return foo(...) / throw new X(...) 等调用语句
        if not header and name != class_name:
            continue                             # 空头部仅允许构造器
        out.append({
            "ann_start": hs,
            "name": name,
            "name_start": name_start,
            "open": open_p,
            "close": close_p,
            "end_char": text[j],
            "term": j,
        })
    return out


# ---------------------------------------------------------------- 解析 Java 文件

CLASS_RE = re.compile(
    r"(?:public\s+|abstract\s+|final\s+|static\s+)*"
    r"(class|interface|enum)\s+(\w+)"
    r"(?:\s+extends\s+([\w<>,\s.&]+?))?"
    r"(?:\s+implements\s+([\w<>,\s.&]+?))?"
    r"\s*\{"
)
# 方法声明扫描：不再用巨型正则（DOTALL + 嵌套量词在大类体上会灾难性回溯），
# 改为“找 name( 候选 → 向前配对括号 → 向后回吞头部验证”，全程线性
CANDIDATE = re.compile(r"(?<![\w.$])([A-Za-z_]\w*)\s*\(")
NAME_REJECT = {"if", "for", "while", "switch", "catch", "do", "return", "new",
               "throw", "assert", "synchronized", "super", "this", "class",
               "interface", "enum", "record", "case", "yield", "break", "continue"}
# 允许出现在签名头部（修饰符/注解/泛型返回类型）里的字符；故意不含 ()=.-
HEADER_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                   "0123456789_<>,.?&@ \t\r\n")
# 语句关键字：出现在"返回类型"位置说明这是 return/throw new 等调用语句，不是方法声明
RET_KEYWORDS = {"return", "new", "throw", "case", "assert", "else", "do", "switch",
                "default", "yield", "break", "continue", "try", "catch", "finally"}
# 类型片段：支持全限定名(java.math.BigDecimal)、原生类型(int/boolean)、泛型(List<Foo>)、数组(byte[])
_TYPE = r"[A-Za-z_][\w.]*(?:\s*<[^<>]*(?:<[^<>]*>[^<>]*)*>)?(?:\s*\[\s*\])*"
# 字段：private/protected/public [static|final] Type name;
FIELD_RE = re.compile(
    r"(?:private|protected|public)\s+"
    r"(?:static\s+|final\s+)*"
    rf"({_TYPE})\s+(\w+)\s*;"
)
# @TableField("显式列名") private Type field;
TABLE_FIELD_RE = re.compile(
    r'@TableField\(\s*(?:value\s*=\s*)?"([^"]+)"\s*\)\s*'
    rf"(?:private|protected|public)\s+{_TYPE}\s+(\w+)\s*;"
)
# 方法体里的 field.method( 调用
CALL_RE = re.compile(r"(?<![\w.])([a-z]\w*)\.([a-z]\w*)\s*\(")
# 方法体里的裸调用（本类 private 方法委托），前面不能是 . 或单词字符
BARE_CALL_RE = re.compile(r"(?<![\w.])([a-z]\w*)\s*\(")
BARE_SKIP = {"if", "for", "while", "switch", "catch", "return", "new", "synchronized",
             "super", "this", "assert", "try", "do", "else", "yield", "record"}
# 方法引用：this::loadGlobalStats / withCache(key, this::xxx)
METHOD_REF_RE = re.compile(r"(\w+)\s*::\s*(\w+)")
# SQL 里提取表名：FROM/JOIN/INTO/UPDATE 后面跟的标识符
SQL_TABLE_RE = re.compile(r"\b(?:from|join|into|update)\s+([a-zA-Z_][\w]*)", re.IGNORECASE)


def simple_type(t):
    """类型归一化：java.util.List<Foo>[] -> List"""
    return t.split("<")[0].strip().split(".")[-1]


def parse_java(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    clean = strip_code(raw)

    pkg_m = re.search(r"package\s+([\w.]+)\s*;", clean)
    pkg = pkg_m.group(1) if pkg_m else ""

    cm = CLASS_RE.search(clean)
    if not cm:
        return None
    kind, cname = cm.group(1), cm.group(2)
    extends = (cm.group(3) or "").strip()
    implements = re.split(r"[,\s]+", (cm.group(4) or "").strip())
    implements = [i for i in implements if i]

    fqn = pkg + "." + cname if pkg else cname

    # 类注解：类声明 { 往前一小段原文
    decl_brace = clean.index("{", cm.start())
    head_raw = raw[max(0, cm.start() - 600):cm.start()]
    class_ann = " ".join(re.findall(r"@\w[\w.]*", head_raw))

    body_start = decl_brace
    body_end = match_brace(clean, body_start)
    body_clean = clean[body_start:body_end + 1]
    body_raw = raw[body_start:body_end + 1]

    # 字段：字段名 -> 类型简单名（全限定名/泛型/数组归一化，如 java.math.BigDecimal -> BigDecimal）
    fields = {}
    for fm in FIELD_RE.finditer(body_clean):
        fields[fm.group(2)] = simple_type(fm.group(1))

    # 实体信息：@TableName + 字段 -> 列名（MP 驼峰转下划线，@TableField 显式覆盖）
    table_name = None
    tm = re.search(r'@TableName\(\s*(?:value\s*=\s*)?"([^"]+)"', head_raw)
    if tm:
        table_name = tm.group(1)
    entity_columns = None
    if table_name and kind == "class":
        cols = {}
        explicit = {fm.group(2): fm.group(1) for fm in TABLE_FIELD_RE.finditer(body_clean)}
        for fname, ftype in fields.items():
            cols[fname] = explicit.get(fname, camel_to_snake(fname))
        entity_columns = cols

    # Mapper 泛型实体：extends BaseMapper<BizOrder>
    base_entity = None
    bm = re.search(r"BaseMapper<(\w+)>", extends)
    if bm:
        base_entity = bm.group(1)

    # 方法：线性扫描（折叠副本上找候选，raw/clean 文本上取注解/参数原文）
    body_scan = collapse_ann_args(body_clean)
    methods = []
    for mi in scan_methods(body_scan, cname):
        mname = mi["name"]
        end_char = mi["end_char"]
        params = clean[body_start + mi["open"] + 1: body_start + mi["close"]]
        if end_char == "{":
            brace_idx = body_start + mi["term"]  # '{' 的位置
            mb_end = match_brace(clean, brace_idx)
            if mb_end < 0:
                continue
            m_body_clean = clean[brace_idx:mb_end + 1]
        else:
            # 接口方法（分号结尾），没有方法体
            m_body_clean = ""
        # 注解原文：从 raw 文本按等长偏移切（折叠只发生在副本上，raw 完好）
        m_ann_raw = raw[body_start + mi["ann_start"]: body_start + mi["name_start"]]
        # 路由
        http = None
        for ann, verb in MAPPING_ANN.items():
            if re.search(r"@" + ann + r"\b", m_ann_raw):
                args = ann_args(m_ann_raw, ann)
                route_path = first_string(args) if args else ""
                http = (verb, route_path)
                break
        sql = extract_sql(m_ann_raw)
        hidden = [a for a in HIDDEN_ANN if re.search(r"@" + a + r"\b", m_ann_raw)]
        calls = [(c.group(1), c.group(2)) for c in CALL_RE.finditer(m_body_clean)]
        bare_calls = [c.group(1) for c in BARE_CALL_RE.finditer(m_body_clean)
                      if c.group(1) not in BARE_SKIP]
        method_refs = [(c.group(1), c.group(2)) for c in METHOD_REF_RE.finditer(m_body_clean)]
        methods.append({
            "name": mname,
            "params": params,
            "ann_raw": m_ann_raw,
            "http": http,
            "sql": sql,
            "hidden": hidden,
            "calls": calls,
            "bare_calls": bare_calls,
            "method_refs": method_refs,
            "transactional": "@Transactional" in m_ann_raw,
        })

    return {
        "fqn": fqn,
        "name": cname,
        "pkg": pkg,
        "kind": kind,
        "extends": extends,
        "implements": implements,
        "fields": fields,
        "methods": methods,
        "class_ann": class_ann,
        "file": path,
        "table_name": table_name,
        "entity_columns": entity_columns,
        "base_entity": base_entity,
        "is_controller": "RestController" in class_ann or "Controller" in class_ann and kind == "class",
        "is_mapper": cname.endswith("Mapper") or "@Mapper" in class_ann,
        "is_service_impl": cname.endswith("Impl") or "@Service" in class_ann,
        "is_entity": table_name is not None,
    }


# ---------------------------------------------------------------- 调用图构建

def resolve_callees(target, mname, by_simple, impl_of):
    """解析 target 类的 mname 方法的下游调用。
    返回 [(kind, callee_class_simple, callee_method, mapper_write)]，
    kind ∈ {"self", "service", "mapper", "component"}。
    visit() 渲染和调用图构建共用这套逻辑，避免两处实现分叉。"""
    method = None
    for m in target["methods"]:
        if m["name"] == mname:
            method = m
            break
    if method is None:
        return []

    own_names = {m["name"] for m in target["methods"]}
    out = []

    # 本类方法委托（this.xxx() / 裸 xxx() / this::xxx）
    self_calls = set()
    for field, cmethod in method["calls"]:
        if field == "this" and cmethod in own_names and cmethod != mname:
            self_calls.add(cmethod)
    for bc in method.get("bare_calls", []):
        if bc in own_names and bc != mname:
            self_calls.add(bc)
    for _recv, ref_m in method.get("method_refs", []):
        if ref_m in own_names and ref_m != mname:
            self_calls.add(ref_m)
    for sc in sorted(self_calls):
        out.append(("self", target["name"], sc, False))

    for field, cmethod in method["calls"]:
        if field == "this":
            continue
        ftype = target["fields"].get(field)
        if not ftype:
            continue  # 局部变量/静态调用，MVP 不追
        fcls = by_simple.get(ftype)
        if fcls and fcls["is_mapper"]:
            is_write = cmethod in MP_WRITE or (fcls is not None and _sql_kind(by_simple, ftype, cmethod) in ("UPDATE", "INSERT", "DELETE"))
            out.append(("mapper", ftype, cmethod, is_write))
        elif fcls and (fcls["kind"] == "interface" or fcls["is_service_impl"]) and (ftype.endswith("Service") or _impl_of(ftype, impl_of)):
            # 归一化到实现类：图节点只建在 class 上，接口会导致逆向 BFS 断链
            impl_name = impl_of.get(ftype) or ftype
            out.append(("service", impl_name, cmethod, False))
        else:
            out.append(("component", ftype, cmethod, False))
    return out


def _impl_of(type_simple, impl_of):
    return impl_of.get(type_simple)


def _sql_kind(by_simple, mapper_name, method_name):
    cls = by_simple.get(mapper_name)
    if not cls:
        return None
    for m in cls["methods"]:
        if m["name"] == method_name and m["sql"]:
            return m["sql"][0]
    return None


def build_call_graph(classes, by_simple, impl_of):
    """全量调用图：key = (class, method)，value = [(kind, class, method, is_db_write)]"""
    graph = {}
    for c in classes.values():
        if c["kind"] != "class":
            # 接口方法落到实现类再建边
            impl = by_simple.get(impl_of.get(c["name"], ""), None)
            if impl is None:
                continue
            continue
        for m in c["methods"]:
            callees = resolve_callees(c, m["name"], by_simple, impl_of)
            if callees:
                graph[(c["name"], m["name"])] = callees
    return graph


def tx_closure(graph, by_simple):
    """事务闭包：@Transactional 方法 + 它们在同一事务里能触达的所有下游调用。
    语义依据 Spring REQUIRED 传播：事务内调用的下游代码也在事务里。"""
    seeds = set()
    for c in by_simple.values():
        if c["kind"] != "class":
            continue
        for m in c["methods"]:
            if m["transactional"]:
                seeds.add((c["name"], m["name"]))
    inside = set(seeds)
    stack = list(seeds)
    while stack:
        key = stack.pop()
        for _kind, cc, cm, _w in graph.get(key, []):
            nxt = (cc, cm)
            if nxt not in inside:
                inside.add(nxt)
                stack.append(nxt)
    return seeds, inside


def reverse_index(graph, routes):
    """逆向索引：mapper 方法 -> 直接调用者 + 可达路由。
    graph 边: caller -> [(kind, callee_cls, callee_m, ...)]，翻转后从 mapper 往上 BFS。"""
    rev = {}
    for (cc, cm), callees in graph.items():
        for _kind, dcls, dm, _w in callees:
            rev.setdefault((dcls, dm), []).append((cc, cm))

    route_entries = {(r["controller"], r["handler"]) for r in routes}
    index = {}
    for (dcls, dm) in list(rev.keys()):
        direct = rev.get((dcls, dm), [])
        # BFS 向上收集所有祖先
        ancestors = set()
        stack = list(direct)
        seen = {(dcls, dm)}
        while stack:
            node = stack.pop()
            if node in ancestors:
                continue
            ancestors.add(node)
            for up in rev.get(node, []):
                if up not in seen:
                    seen.add(up)
                    stack.append(up)
        hit_routes = [r for r in routes if (r["controller"], r["handler"]) in ancestors]
        index[f"{dcls}#{dm}"] = {
            "direct_callers": [f"{c}#{m}" for c, m in sorted(set(direct))],
            "routes": [{"method": r["method"], "path": r["path"]} for r in hit_routes],
        }
    return index


# ---------------------------------------------------------------- 主流程

def main():
    classes = {}
    by_simple = {}
    java_files = []
    for dirpath, dirnames, filenames in os.walk(JAVA_SRC):
        if os.sep + "target" + os.sep in dirpath + os.sep:
            continue
        for fn in filenames:
            if fn.endswith(".java"):
                java_files.append(os.path.join(dirpath, fn))

    for jf in java_files:
        info = parse_java(jf)
        if info:
            classes[info["fqn"]] = info
            by_simple[info["name"]] = info

    # 接口简单名 -> 实现类
    impl_of = {}
    for c in classes.values():
        for impl_name in c["implements"]:
            base = impl_name.split("<")[0].split(".")[-1]
            if base in by_simple and by_simple[base]["kind"] == "interface":
                impl_of[base] = c["name"]

    def resolve_impl(type_simple):
        impl_name = impl_of.get(type_simple)
        return by_simple.get(impl_name) if impl_name else None

    def find_method(cls, mname):
        for m in cls["methods"]:
            if m["name"] == mname:
                return m
        return None

    # 收集路由
    controllers = [c for c in classes.values() if c["is_controller"]]
    mappers = [c for c in classes.values() if c["is_mapper"]]
    routes = []
    for c in controllers:
        cls_path = ""
        m = re.search(r"@RequestMapping\b", c["class_ann"])
        if m:
            args = ann_args(_head_raw(c), "RequestMapping")
            cls_path = first_string(args) if args else ""
        for meth in c["methods"]:
            if meth["http"]:
                verb, path = meth["http"]
                full = (cls_path.rstrip("/") + "/" + path.lstrip("/")).rstrip("/") or "/"
                routes.append({"method": verb, "path": full, "controller": c["name"],
                               "handler": meth["name"]})
    routes.sort(key=lambda r: (r["path"], r["method"]))

    # 调用图 + 事务闭包
    graph = build_call_graph(classes, by_simple, impl_of)
    tx_seeds, tx_inside = tx_closure(graph, by_simple)

    # 实体 -> 表 -> SQL 联动
    entities = [c for c in classes.values() if c["is_entity"]]
    # mapper -> 实体
    mapper_entity = {}
    for mp in mappers:
        if mp["base_entity"]:
            mapper_entity[mp["name"]] = mp["base_entity"]
    # service impl -> 实体（ServiceImpl<M, T> 模式）
    for c in classes.values():
        sm = re.search(r"ServiceImpl<(\w+)\s*,\s*(\w+)>", c["extends"])
        if sm:
            mapper_entity[sm.group(1)] = sm.group(2)

    # 每条自定义 SQL：涉及哪些表、哪些列
    sql_tables = {}
    sql_columns = {}
    table_to_entity = {c["table_name"]: c for c in entities}
    for mp in mappers:
        for meth in mp["methods"]:
            if not meth["sql"]:
                continue
            kw, sql = meth["sql"]
            tables = list(dict.fromkeys(t.lower() for t in SQL_TABLE_RE.findall(sql)))
            sql_tables[f"{mp['name']}#{meth['name']}"] = tables
            # 列触碰：字面列名 + SELECT * / 别名星号 x.* 展开
            sql_columns[f"{mp['name']}#{meth['name']}"] = resolve_sql_columns(
                sql, tables, table_to_entity)

    # XML mapper 解析（campus-job 零 XML → 这里返回 {}，下游一切照旧）
    table_to_entity_for_xml = {c["table_name"]: c for c in entities}
    xml_stmts = parse_xml_mappers(RESOURCES, table_to_entity_for_xml, by_simple)

    # 逆向索引
    rindex = reverse_index(graph, routes)

    # ---------------------------------------------------------------- 渲染 markdown
    lines = []

    def visit(cls_name, mname, depth, seen):
        """递归追链，向 lines 输出树形文本。"""
        cls = by_simple.get(cls_name)
        if cls is None:
            lines.append(f"{'   ' * depth}└─ {cls_name}#{mname}  ⚠️ 类型不在本项目（外部依赖）")
            return
        key = (cls["name"], mname)
        if key in seen:
            lines.append(f"{'   ' * depth}└─ {cls['name']}#{mname}  ↩ 循环引用，截断")
            return
        seen = seen | {key}

        target = cls
        if cls["kind"] == "interface":
            impl = resolve_impl(cls["name"])
            if impl:
                target = impl

        method = find_method(target, mname) or find_method(cls, mname)
        tag = ""
        if (target["name"], mname) in tx_inside:
            tag = "  [在事务内]" if (target["name"], mname) not in tx_seeds else "  [@Transactional]"
        if method and method["hidden"]:
            tag += f"  [隐藏入口: {'/'.join(method['hidden'])}]"

        prefix = "   " * depth
        if depth == 0:
            lines.append(f"**{target['name']}#{mname}**{tag}")
        else:
            lines.append(f"{prefix}└─ {target['name']}#{mname}{tag}")

        if method is None:
            if target["is_mapper"] or cls["is_mapper"] or target["name"].endswith("Mapper"):
                mp = "（MP 内置）" if mname in MP_BUILTIN else ""
                if depth > 0:
                    lines[-1] = lines[-1] + f"  → Mapper 方法{mp}"
            return

        callees = resolve_callees(target, mname, by_simple, impl_of)
        child_prefix = prefix + "   "
        seen_service = set()
        for kind, ctype, cmethod, is_write in callees:
            if kind == "self":
                visit(target["name"], cmethod, depth + 1, seen)
                continue
            if kind == "mapper":
                mm = find_method(by_simple.get(ctype, {"methods": []}), cmethod) if ctype in by_simple else None
                msql = mm["sql"] if mm else None
                wtag = " ✍️写" if is_write else ""
                if msql:
                    kw, sql = msql
                    short_sql = sql if len(sql) <= 100 else sql[:97] + "..."
                    lines.append(f"{child_prefix}├─ {ctype}#{cmethod}  → @{kw} 自定义SQL{wtag}")
                    lines.append(f"{child_prefix}│     `{short_sql}`")
                else:
                    mp_tag = "（MP 内置）" if cmethod in MP_BUILTIN else "（Mapper 方法，SQL 未找到）"
                    lines.append(f"{child_prefix}├─ {ctype}#{cmethod}  {mp_tag}{wtag}")
            elif kind == "service":
                if (ctype, cmethod) in seen_service:
                    continue
                seen_service.add((ctype, cmethod))
                visit(ctype, cmethod, depth + 1, seen)
            else:
                lines.append(f"{child_prefix}├─ {ctype}#{cmethod}  （组件/工具）")

    out = []
    out.append("# 框架调用链地图（阶段0 增强版）")
    out.append("")
    out.append(f"- 项目: `{os.path.basename(ROOT)}`")
    out.append(f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    out.append(f"- 扫描类: {len(classes)} 个 | Controller: {len(controllers)} 个 | "
               f"Mapper: {len(mappers)} 个 | 实体: {len(entities)} 个 | "
               f"HTTP 路由: {len(routes)} 条 | 调用图边: {len(graph)} 个方法")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## 一、HTTP 路由调用链")
    out.append("")

    for r in routes:
        out.append(f"### `{r['method']} {r['path']}`")
        lines = []
        visit(r["controller"], r["handler"], 0, set())
        out.extend(lines)
        out.append("")

    # 自定义 SQL 汇总
    out.append("---")
    out.append("")
    out.append("## 二、Mapper 自定义 SQL（注解方式）")
    out.append("")
    any_sql = False
    for mp in sorted(mappers, key=lambda x: x["name"]):
        for meth in mp["methods"]:
            if meth["sql"]:
                any_sql = True
                kw, sql = meth["sql"]
                key = f"{mp['name']}#{meth['name']}"
                out.append(f"- **{key}** — @{kw}")
                out.append(f"  - SQL: `{sql}`")
                tables = sql_tables.get(key, [])
                if tables:
                    out.append(f"  - 涉及表: {', '.join('`' + t + '`' for t in tables)}")
                cols = sql_columns.get(key, [])
                if cols:
                    out.append(f"  - 触碰列: {', '.join('`' + c + '`' for c in cols)}")
                ri = rindex.get(key)
                if ri and ri["routes"]:
                    rs = ", ".join(f"`{x['method']} {x['path']}`" for x in ri["routes"])
                    out.append(f"  - ↑ 上游路由: {rs}")
    if not any_sql:
        out.append("（没有注解 SQL，全部走 MyBatis-Plus 内置方法）")
    out.append("")

    # 事务影响面
    out.append("---")
    out.append("")
    out.append("## 三、事务边界影响面（@Transactional）")
    out.append("")
    out.append("### 事务入口（声明处）")
    out.append("")
    if tx_seeds:
        for (cc, cm) in sorted(tx_seeds):
            c = by_simple.get(cc)
            rel = os.path.relpath(c["file"], ROOT) if c else "?"
            out.append(f"- `{cc}#{cm}`  (`{rel}`)")
    else:
        out.append("（未发现）")
    out.append("")
    out.append("### 事务闭包内的方法（在同一事务里执行，出错会一起回滚）")
    out.append("")
    non_seed = sorted(tx_inside - tx_seeds)
    if non_seed:
        out.append("```")
        for (cc, cm) in non_seed:
            out.append(f"{cc}#{cm}")
        out.append("```")
    else:
        out.append("（无）")
    out.append("")
    out.append("### 事务内的数据库写操作（✍️ 出错回滚的关键路径）")
    out.append("")
    tx_writes = []
    for (cc, cm) in sorted(tx_inside):
        for kind, dcls, dm, is_write in graph.get((cc, cm), []):
            if kind == "mapper" and is_write:
                tx_writes.append((cc, cm, dcls, dm))
    if tx_writes:
        for cc, cm, dcls, dm in sorted(set(tx_writes)):
            out.append(f"- `{cc}#{cm}` → `{dcls}#{dm}` ✍️")
    else:
        out.append("（事务内未发现 Mapper 写调用，或写操作经由 MP IService 未被解析）")
    out.append("")

    # 实体联动
    out.append("---")
    out.append("")
    out.append("## 四、实体 ↔ 表 ↔ SQL 联动（改实体字段的波及面）")
    out.append("")
    out.append("> 给实体加/删字段前，先看这一节：哪些 SQL 会受影响、哪些路由会变化。")
    out.append("")
    for ent in sorted(entities, key=lambda x: x["name"]):
        table = ent["table_name"]
        nfields = len(ent["entity_columns"] or {})
        out.append(f"### {ent['name']} → 表 `{table}`（{nfields} 个字段）")
        out.append("")
        # 字段列表
        cols = ent["entity_columns"] or {}
        field_strs = [f"`{f}`→`{c}`" for f, c in list(cols.items())[:20]]
        out.append("- 字段: " + ", ".join(field_strs) + (" ..." if nfields > 20 else ""))
        # 哪些 mapper 以它为 BaseMapper
        mps_of = [m for m, e in mapper_entity.items() if e == ent["name"]]
        if mps_of:
            out.append(f"- 专属 Mapper: {', '.join('`' + m + '`' for m in sorted(mps_of))}")
        # 哪些自定义 SQL 碰了这张表
        touching = [(k, v) for k, v in sql_tables.items() if table in v]
        if touching:
            out.append(f"- 被自定义 SQL 触碰: {len(touching)} 处")
            for k, v in touching:
                ri = rindex.get(k, {})
                nroutes = len(ri.get("routes", []))
                out.append(f"  - `{k}`（波及 {nroutes} 条路由）")
        else:
            out.append("- 被自定义 SQL 触碰: 无（全部走 MP 内置 CRUD）")
        out.append("")

    # 逆向索引
    out.append("---")
    out.append("")
    out.append("## 五、逆向索引（这条 SQL / Mapper 方法，谁在用？）")
    out.append("")
    out.append("> 改 SQL 前必查：上游有多少路由依赖它，动了会炸几个接口。")
    out.append("")
    hot = []
    for mp in sorted(mappers, key=lambda x: x["name"]):
        for meth in mp["methods"]:
            key = f"{mp['name']}#{meth['name']}"
            ri = rindex.get(key)
            if not ri:
                continue
            nroutes = len(ri["routes"])
            hot.append((nroutes, key, ri))
    hot.sort(reverse=True)
    if hot:
        for nroutes, key, ri in hot:
            flag = "🔥" if nroutes >= 3 else ("⚠️" if nroutes == 2 else "")
            out.append(f"- **{key}** ← {nroutes} 条路由 {flag}")
            out.append(f"  - 直接调用者: {', '.join('`' + c + '`' for c in ri['direct_callers']) or '无'}")
            for r in ri["routes"]:
                out.append(f"  - `{r['method']} {r['path']}`")
    else:
        out.append("（未收集到调用关系）")
    out.append("")

    # 隐藏入口
    out.append("---")
    out.append("")
    out.append("## 六、隐藏入口（没有 HTTP 路由但会被框架触发）")
    out.append("")
    found_hidden = False
    for c in sorted(classes.values(), key=lambda x: x["name"]):
        for meth in c["methods"]:
            if meth["hidden"]:
                found_hidden = True
                rel = os.path.relpath(c["file"], ROOT)
                out.append(f"- `{'/'.join(meth['hidden'])}` → {c['name']}#{meth['name']}  (`{rel}`)")
    for c in sorted(classes.values(), key=lambda x: x["name"]):
        rel = os.path.relpath(c["file"], ROOT)
        if c["name"].endswith("Interceptor"):
            found_hidden = True
            out.append(f"- `HandlerInterceptor` → {c['name']}  (`{rel}`)")
        if "ControllerAdvice" in c["class_ann"] or "ExceptionHandler" in c["class_ann"]:
            found_hidden = True
            out.append(f"- `@ControllerAdvice 全局异常处理` → {c['name']}  (`{rel}`)")
    if not found_hidden:
        out.append("（未发现）")
    out.append("")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(out))

    # ---------------------------------------------------------------- JSON 输出（阶段1 MCP 数据源）
    # MP 内置方法不在接口里声明，但实际被调用（selectById/insert/...）——
    # 补进 mapper 条目，impact/find_sql 才能感知这类隐式 CRUD 的影响面
    builtin_used = {}
    for (_cc, _cm), callees in graph.items():
        for _k, dc, dm, _w in callees:
            if dm in MP_BUILTIN:
                builtin_used.setdefault(dc, set()).add(dm)

    data = {
        "meta": {
            "project": os.path.basename(ROOT),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "classes": len(classes), "controllers": len(controllers),
            "mappers": len(mappers), "entities": len(entities),
            "routes": len(routes),
        },
        "routes": routes,
        "mappers": [
            {
                "class": mp["name"],
                "base_entity": mp["base_entity"],
                "methods": (
                    [
                        {
                            "name": meth["name"],
                            "params": meth["params"],
                            "sql": ({"kind": meth["sql"][0], "text": meth["sql"][1],
                                     "tables": sql_tables.get(f"{mp['name']}#{meth['name']}", []),
                                     "columns": sql_columns.get(f"{mp['name']}#{meth['name']}", [])}
                                    if meth["sql"]
                                    else xml_stmts.get(f"{mp['name']}#{meth['name']}")),
                            "reverse": rindex.get(f"{mp['name']}#{meth['name']}"),
                        }
                        for meth in mp["methods"]
                    ] + [
                        # 被实际调用的 MP 内置方法（排除与自定义方法同名的）：
                        # 给一份合成 SQL 记录——SELECT * / 全表写，触碰 base_entity 实体的所有列
                        {"name": bm, "params": "(MP 内置)",
                         "sql": mp_builtin_sql_record(bm, by_simple.get(mp["base_entity"])),
                         "reverse": rindex.get(f"{mp['name']}#{bm}")}
                        for bm in sorted(builtin_used.get(mp["name"], set())
                                         - {m["name"] for m in mp["methods"]})
                    ]
                ),
            }
            for mp in sorted(mappers, key=lambda x: x["name"])
        ],
        "entities": [
            {"name": e["name"], "table": e["table_name"], "columns": e["entity_columns"]}
            for e in sorted(entities, key=lambda x: x["name"])
        ],
        "call_graph": {
            f"{cc}#{cm}": [{"kind": k, "class": dc, "method": dm, "is_db_write": w}
                           for k, dc, dm, w in callees]
            for (cc, cm), callees in sorted(graph.items())
        },
        "transactional": {
            "seeds": sorted(f"{c}#{m}" for c, m in tx_seeds),
            "inside_closure": sorted(f"{c}#{m}" for c, m in tx_inside),
        },
        "hidden_entries": [
            {"class": c["name"], "method": meth["name"], "annotations": meth["hidden"],
             "file": os.path.relpath(c["file"], ROOT)}
            for c in sorted(classes.values(), key=lambda x: x["name"])
            for meth in c["methods"] if meth["hidden"]
        ],
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[OK] 扫描 {len(java_files)} 个 Java 文件，{len(classes)} 个类，{len(routes)} 条路由 - framework_map.py:1196")
    print(f"[OK] 事务闭包: {len(tx_inside)} 个方法 | 实体: {len(entities)} 个 | - framework_map.py:1197"
          f"逆向索引: {sum(1 for k in rindex if 'Mapper#' in k)} 个 Mapper 方法")
    print(f"[OK] 地图已生成: {OUT} - framework_map.py:1199")
    print(f"[OK] JSON 已生成: {OUT_JSON} - framework_map.py:1200")


_HEAD_RAW_CACHE = {}


def _head_raw(c):
    """取类声明前的原文（给类级 @RequestMapping 抠路径用）。"""
    if c["fqn"] in _HEAD_RAW_CACHE:
        return _HEAD_RAW_CACHE[c["fqn"]]
    with open(c["file"], "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    idx = raw.find("class " + c["name"])
    if idx < 0:
        idx = raw.find("interface " + c["name"])
    txt = raw[max(0, idx - 800):idx] if idx >= 0 else ""
    _HEAD_RAW_CACHE[c["fqn"]] = txt
    return txt


if __name__ == "__main__":
    main()
