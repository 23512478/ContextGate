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
    # MyBatis Generator 风格的 Example 消费方法（无注解/XML SQL，条件由 Example 动态合成）
    "selectByExample", "countByExample", "deleteByExample",
    "updateByExample", "updateByExampleSelective",
}
# COUNT/EXISTS 族：不取行数据，不触碰业务列
MP_COUNT_ONLY = {"selectCount", "count", "exists", "countByExample"}
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
        cols = [f"{table}.{col} ({entity['name']}.{fname})"
                for fname, col in entity["entity_columns"].items()]
    else:
        # 读方法：selectById/selectList/selectOne/selectBatchIds/...
        #       getById/getOne/list/listByIds/selectMaps/selectObjs/
        #       selectPage/selectMapsPage/lambdaQuery/page 等 → 行读取，全列
        kind = "SELECT"
        if method_name in MP_COUNT_ONLY:
            # COUNT(*)/EXISTS 不取行数据，不触碰业务列（条件列由 Wrapper 分析另算）
            text = "(MyBatis-Plus 内置 COUNT/EXISTS)"
            cols = []
        else:
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
    """扫描 src/main/resources/mapper/**/*.xml。返回 {MapperClass#methodId: sql_record}。"""
    mapper_dir = os.path.join(resources_dir, "mapper")
    if not os.path.isdir(mapper_dir):
        return {}
    out = {}
    for dirpath, _dn, filenames in os.walk(mapper_dir):
        for fn in filenames:
            if fn.endswith(".xml"):
                out.update(_parse_xml_file(os.path.join(dirpath, fn),
                                           table_to_entity, entity_by_simple))
    return out


# 内层 foreach（body 里不再嵌 <foreach>）；逐层替换实现嵌套展开
_FOREACH_INNER_RE = re.compile(
    r"<foreach\b([^>]*)>((?:(?!<foreach)(?!</foreach>).)*)</foreach>", re.S)


def _expand_foreach(raw_xml):
    """把 <foreach collection item open separator close>…</foreach> 重建成 SQL 片段：
    open + 内部文本 + close。separator 的重复次数运行期才定，静态保留一份内部文本
    即可保住 IN (…) 的形状和 #{item} 占位。内层先替换、循环到无 <foreach>，嵌套也能展开。"""
    prev = None
    while prev != raw_xml:
        prev = raw_xml

        def _repl(m):
            attrs, body = m.group(1), m.group(2)

            def attr(name):
                am = re.search(rf'\b{name}="([^"]*)"', attrs)
                return am.group(1) if am else ""

            inner = re.sub(r"<[^>]+>", " ", body)  # 内部的 <if> 等子标签照旧剥掉
            parts = [p for p in (attr("open"), inner.strip(), attr("close")) if p]
            return " ".join(parts)

        raw_xml = _FOREACH_INNER_RE.sub(_repl, raw_xml)
    return raw_xml


def _collect_result_map(rm):
    """递归收集一个 <resultMap> 的列映射。
    返回 (rtype, col_prop, nested)：
      col_prop = {column: property}    顶层 id/result（归因给 resultMap type 实体）
      nested   = [(column, property, 嵌套类型简单名)]
                                       association/collection 里的映射（归因给
                                       javaType/ofType 对应实体，可能是另一张表）"""
    rtype = (rm.get("type") or "").rsplit(".", 1)[-1]
    col_prop, nested = {}, []

    def walk(node, ntype=None):
        for el in node:
            tag = el.tag
            if tag in ("id", "result"):
                c, p = el.get("column"), el.get("property")
                if not c:
                    continue
                if ntype:
                    nested.append((c, p or "", ntype))
                elif p:
                    col_prop[c] = p
            elif tag in ("association", "collection"):
                sub_type = (el.get("javaType") or el.get("ofType") or "").rsplit(".", 1)[-1]
                if not sub_type:
                    continue  # 无法确定嵌套类型，放弃归因
                c = el.get("column")
                if c:
                    nested.append((c, el.get("property") or "", sub_type))
                walk(el, sub_type)

    walk(rm)
    return rtype, col_prop, nested


def _parse_xml_file(path, table_to_entity, entity_by_simple):
    """解析单个 MyBatis mapper XML 文件，返回 {MapperClass#methodId: sql_record}。"""
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return {}
    root = tree.getroot()
    ns = root.get("namespace", "")
    mapper_class = ns.rsplit(".", 1)[-1] if ns else ""
    if not mapper_class:
        return {}
    out = {}
    # <sql id> 片段
    fragments = {sf.get("id"): " ".join(sf.itertext()).strip()
                 for sf in root.findall("sql") if sf.get("id")}
    # <resultMap> 列映射（含 extends 继承与 association/collection 嵌套）
    raw_maps, rm_extends = {}, {}
    for rm in root.findall("resultMap"):
        rid = rm.get("id")
        if not rid:
            continue
        raw_maps[rid] = _collect_result_map(rm)
        rm_extends[rid] = rm.get("extends")

    resolved = {}

    def resolve_rm(rid, chain=()):
        """extends 链合并：父映射先并入，子覆盖同名列；chain 防循环引用。"""
        if rid in resolved:
            return resolved[rid]
        info = raw_maps.get(rid)
        if not info or rid in chain:
            return ("", {}, [])
        rtype, cols, nested = info
        ext = rm_extends.get(rid)
        if ext and ext in raw_maps:
            prtype, pcols, pnested = resolve_rm(ext, chain + (rid,))
            rtype = rtype or prtype
            merged = dict(pcols)
            merged.update(cols)
            cols = merged
            nested = pnested + nested
        resolved[rid] = (rtype, cols, nested)
        return resolved[rid]

    for rid in raw_maps:
        resolve_rm(rid)
    # 四类 SQL 语句
    for tag, kind in (("select", "SELECT"), ("insert", "INSERT"),
                      ("update", "UPDATE"), ("delete", "DELETE")):
        for stmt in root.findall(tag):
            mid = stmt.get("id")
            if not mid:
                continue
            raw_xml = ET.tostring(stmt, encoding="unicode")
            raw_xml = re.sub(r'<include\s+refid="([^"]+)"\s*/>',
                             lambda m: fragments.get(m.group(1), m.group(0)), raw_xml)
            raw_xml = _expand_foreach(raw_xml)
            sql_text = re.sub(r"<[^>]+>", " ", raw_xml)
            sql_text = re.sub(r"\s+", " ", sql_text).strip()
            # <set>/<if> 剥离后残留的尾逗号清理；必须带词边界，否则
            # "id, order_id" 里 order_id 的 order 前缀会被误当 ORDER 关键字吃掉逗号
            sql_text = re.sub(r",\s+(?=WHERE\b|ORDER\b|GROUP\b|LIMIT\b)", " ", sql_text,
                              flags=re.IGNORECASE)
            tables = list(dict.fromkeys(t.lower() for t in SQL_TABLE_RE.findall(sql_text)))
            cols = resolve_sql_columns(sql_text, tables, table_to_entity)
            rm_attr = stmt.get("resultMap")
            if rm_attr and rm_attr in resolved:
                rtype, col_prop, nested = resolved[rm_attr]
                r_ent = entity_by_simple.get(rtype)
                if r_ent and r_ent.get("entity_columns"):
                    tname = r_ent["table_name"]
                    for c, prop in col_prop.items():
                        cols.append(f"{tname}.{c} ({r_ent['name']}.{prop})")
                elif tables:
                    for c, prop in col_prop.items():
                        cols.append(f"{tables[0]}.{c} ({rtype}.{prop})")
                # 嵌套映射归因到 javaType/ofType 对应的实体表（可能与外层不同表）
                for c, prop, ntype in nested:
                    n_ent = entity_by_simple.get(ntype)
                    if prop and n_ent and n_ent.get("entity_columns"):
                        cols.append(f"{n_ent['table_name']}.{c} ({n_ent['name']}.{prop})")
            out[f"{mapper_class}#{mid}"] = {
                "kind": kind, "text": sql_text, "tables": tables,
                "columns": sorted(set(cols)), "mp_builtin": False,
            }
    return out


# ---------------------------------------------------------------- 内嵌 SQL：JdbcTemplate 裸 SQL + MP Wrapper 动态 SQL

# jdbcTemplate.xxx(  / namedParameterJdbcTemplate.xxx( 这类变量名带 jdbc 的调用
_JDBC_CALL_RE = re.compile(
    r"\b\w*jdbc\w*\s*\.\s*(queryForList|queryForMap|queryForObject|query|update|batchUpdate|execute)\s*\(",
    re.IGNORECASE)
# 方法内局部 String 变量：String sql = "..." + "..."（JdbcTemplate 常用变量传 SQL）
_LOCAL_STR_RE = re.compile(
    r"(?:[;{}]\s*|^\s*)(?:final\s+)?String\s+(\w+)\s*=\s*((?:\"(?:[^\"\\]|\\.)*\"\s*(?:\+\s*)?)+)",
    re.MULTILINE)
# 类级 static String 常量（static final / final static）：JdbcTemplate 常把 SQL 抽成常量字段
_STATIC_STR_DECL_RE = re.compile(
    r"\b(?:static\s+(?:final\s+)?|final\s+static\s+)String\s+(\w+)\s*=")


def _join_sql_literal(s):
    return re.sub(r"\s+", " ", s.replace(r"\n", " ").replace(r'\"', '"')
                  .replace(r"\'", "'")).strip()


def _static_str_fields(body_raw):
    """扫类级 static String 常量，返回 {name: [token, ...]}，
    token = ("lit", 文本) | ("id", 标识符)。
    右值取到字符串外的首个 ';'；出现方法调用等非「字面量/标识符/+」成分即放弃
    （运行期拼接静态拿不到）。跨类引用在消费点解析，这里只收 token。"""
    out = {}
    for dm in _STATIC_STR_DECL_RE.finditer(body_raw):
        i, n = dm.end(), len(body_raw)
        tokens, buf, in_str = [], [], False
        while i < n:
            ch = body_raw[i]
            if in_str:
                if ch == "\\" and i + 1 < n:
                    buf.append(body_raw[i:i + 2])
                    i += 2
                    continue
                if ch == '"':
                    in_str = False
                    tokens.append(("lit", "".join(buf)))
                    buf = []
                else:
                    buf.append(ch)
            elif ch == '"':
                in_str = True
                buf = []
            elif ch == ";":
                break
            elif ch == "+":
                pass  # 拼接符
            elif not ch.isspace():
                m = re.match(r"\w+", body_raw[i:])
                if not m:
                    break  # 方法调用/下标等，放弃该字段
                tokens.append(("id", m.group(0)))
                i += len(m.group(0))
                continue
            i += 1
        if tokens:
            out[dm.group(1)] = tokens
    return out
# new LambdaQueryWrapper<User>( / new QueryWrapper<User>(
_WRAPPER_NEW_RE = re.compile(
    r"new\s+(LambdaQueryWrapper|LambdaUpdateWrapper|QueryWrapper|UpdateWrapper)\s*<\s*(\w+)\s*>\s*\(")
# IService 的 .lambdaQuery() / .lambdaUpdate()
_LAMBDA_ENTRY_RE = re.compile(r"\.\s*(lambdaQuery|lambdaUpdate)\s*\(")
# 条件链上的动词：.eq( / .like( / .orderByDesc( / .set( ...
_VERBS_WHERE = {"eq", "ne", "gt", "lt", "ge", "le", "like", "likeright", "likeleft",
                "in", "notin", "between", "orderbyasc", "orderbydesc", "groupby"}
_VERB_SET = {"set"}
_VERB_SELECT = {"select"}


def _leading_concat_strings(s, start):
    """从 s[start] 开始，提取开头那段「字符串字面量 + 号拼接」拼成的完整字符串。
    遇到第一个不是字符串/加号/空白的东西就停（说明 SQL 是变量传参，静态拿不到）。"""
    i, n, parts = start, len(s), []
    while True:
        mt = re.match(r'\s*"((?:[^"\\]|\\.)*)"', s[i:])
        if not mt:
            mt = re.match(r"\s*\"\"\"(.*?)\"\"\"", s[i:], re.S)  # 文本块
            if not mt:
                break
        parts.append(mt.group(1))
        i += mt.end()
        m2 = re.match(r"\s*\+\s*", s[i:])
        if not m2:
            break
        i += m2.end()
    if not parts:
        return None
    sql = " ".join(parts)
    return re.sub(r"\s+", " ", sql.replace(r"\n", " ").replace(r'\"', '"')
                  .replace(r"\'", "'")).strip()


def _enclosing_verb(region, pos):
    """从 region[pos]（方法引用 X::getY 处）往左找包裹它的最近一个链动词：.verb( ..."""
    depth, i = 0, pos - 1
    while i >= 0:
        ch = region[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth == 0:
                vm = re.search(r"\.(\w+)\s*$", region[:i])
                return vm.group(1).lower() if vm else None
            depth -= 1
        elif ch == ";" and depth == 0:
            return None
        i -= 1
    return None


def _stmt_to_semicolon(text, start):
    """从 start 取到语句结束（分号），限定在当前方法体内。"""
    end = text.find(";", start)
    return text[start:end if end >= 0 else len(text)]


# Wrapper 变量的跨语句 def-use：定义 / 消费动词
_WRAP_TYPES = {"LambdaQueryWrapper", "LambdaUpdateWrapper", "QueryWrapper", "UpdateWrapper"}
_WRAPPER_DECL_RE = re.compile(
    r"(?:final\s+)?(\w+)(?:\s*<\s*(\w+)\s*>)?\s+(\w+)\s*=\s*new\s+"
    r"(LambdaQueryWrapper|LambdaUpdateWrapper|QueryWrapper|UpdateWrapper)"
    r"\s*(?:<\s*(\w+)?\s*>)?\s*\(")
# 消费点：BaseMapper / IService 上接收 Wrapper 的方法
_CONSUME_VERBS = {"selectlist", "selectone", "selectcount", "selectpage", "selectmaps",
                  "selectmapspage", "selectobjs", "list", "getone", "count", "page",
                  "remove", "delete", "update", "saveorupdate", "exists"}


def _split_statements(body):
    """把方法体切成语句片段：; { } 都是分隔符（块结构不参与 def-use，分支内续链
    保守计入），字符串字面量里的分隔符跳过。返回语句文本列表（不含分隔符）。"""
    stmts, buf = [], []
    in_str = False
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        if in_str:
            if ch == "\\":
                buf.append(body[i:i + 2])
                i += 2
                continue
            if ch == '"':
                in_str = False
            buf.append(ch)
        elif ch == '"':
            in_str = True
            buf.append(ch)
        elif ch in ";{}":
            stmts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf)
    if tail.strip():
        stmts.append(tail)
    return stmts


def _wrapper_defuse(owner, body, cls, ent_by_simple, table_to_entity):
    """Wrapper 拆成变量跨语句链式调用的 def-use 重建：
      定义   XxxWrapper<Entity> w = new XxxWrapper<>()（实体：构造泛型 > 声明泛型）
      续链   w.like(...) / w = w.eq(...)（if/for 分支内续链保守计入，宁多报不漏报）
      消费   orderMapper.selectList(w) 等——把该变量攒下的全部链文本拼成 region
    交给 _wrapper_record 合成 SQL；消费后链重置（变量可复用）。
    只支持单变量直链：w2 = w 拷贝别名、跨方法传递不追。"""
    ent, chains, recs = {}, {}, []
    for raw_stmt in _split_statements(body):
        stmt = raw_stmt.strip()
        if not stmt:
            continue
        # 定义
        dm = _WRAPPER_DECL_RE.match(stmt)
        if dm:
            decl_type, decl_ent, var, wtype, ctor_ent = dm.groups()
            entity = ctor_ent or (decl_ent if decl_type in _WRAP_TYPES else None)
            if entity:
                ent[var] = (wtype, entity)
                chains[var] = [stmt]
                continue
        # 拷贝别名：w2 = w（含 `Type w2 = w;` 声明式）→ Java 里两个引用指向
        # 同一 Wrapper 对象，链表共享：任一变量后续续链都进同一个链
        am = re.search(r"(\w+)\s*=\s*(\w+)\s*$", stmt)
        if am and am.group(1) not in ent and am.group(2) in ent:
            ent[am.group(1)] = ent[am.group(2)]
            chains[am.group(1)] = chains[am.group(2)]
            continue
        # 与已定义变量相关的语句
        touched = [v for v in ent if re.search(r"\b" + re.escape(v) + r"\b", stmt)]
        for var in touched:
            wtype, entity = ent[var]
            if re.match(re.escape(var) + r"\s*[.=]", stmt):
                # 续链 / 重新赋值续链
                chains[var].append(stmt)
                continue
            # 消费点：接收者调用了消费动词，且变量作为参数传入
            vm = re.search(r"\.\s*(\w+)\s*\(", stmt)
            if vm and vm.group(1).lower() in _CONSUME_VERBS:
                region = ";\n".join(chains[var] + [stmt])
                rec = _wrapper_record(owner, region, wtype, entity,
                                      ent_by_simple, table_to_entity)
                if rec:
                    recs.append(rec)
                chains[var] = []  # 消费后链重置，变量可复用
    return recs


# ---------------------------------------------------------------- MBG Example 动态条件

# MyBatis Generator 的 criteria 方法：andXxxEqualTo / orXxxGreaterThan / ...
# 方法名里编码了连接词 + 列名 + 操作符，列名按 camel 转下划线后须命中实体列才收
_EXAMPLE_CRITERIA_RE = re.compile(
    r"\.\s*(and|or)([A-Z]\w*?)("
    r"EqualTo|NotEqualTo|GreaterThan|GreaterThanOrEqualTo|LessThan|LessThanOrEqualTo|"
    r"In|NotIn|Between|NotBetween|Like|NotLike|LikeLeft|LikeRight|IsNull|IsNotNull)\s*\(")
_EXAMPLE_OP_SQL = {
    "EqualTo": "=", "NotEqualTo": "<>",
    "GreaterThan": ">", "GreaterThanOrEqualTo": ">=",
    "LessThan": "<", "LessThanOrEqualTo": "<=",
    "In": "IN", "NotIn": "NOT IN",
    "Between": "BETWEEN", "NotBetween": "NOT BETWEEN",
    "Like": "LIKE", "NotLike": "NOT LIKE", "LikeLeft": "LIKE", "LikeRight": "LIKE",
    "IsNull": "IS NULL", "IsNotNull": "IS NOT NULL",
}
# 消费动词 → 语句类型（selectByExample 行读取全列；countByExample 只触碰条件列）
_EXAMPLE_CONSUME = {"selectbyexample": ("SELECT", True), "countbyexample": ("SELECT", False),
                    "deletebyexample": ("DELETE", False), "updatebyexample": ("UPDATE", True),
                    "updatebyexampleselective": ("UPDATE", True)}


def _example_defuse(owner, body, ent_by_simple, table_to_entity):
    """MyBatis Generator 的 Example 动态条件：
    new XxxExample → createCriteria().andXxxEqualTo(...) → selectByExample(example)。
    AND/OR 按出现顺序平铺（MBG 的 criteria 分组语义不还原，宁近似不漏报）；
    Example 作方法参数传入的（调用方在别处拼条件）不追。"""
    ent_m = re.search(r"\b(\w+)Example\s+(\w+)\s*=\s*new\s+\w+Example\b", body)
    if not ent_m:
        return []
    ent = ent_by_simple.get(ent_m.group(1))
    if not ent or not ent.get("entity_columns"):
        return []
    ecols, table = ent["entity_columns"], ent["table_name"]
    example_vars = {m.group(2) for m in
                    re.finditer(r"\b(\w+)Example\s+(\w+)\s*=\s*new\s+\w+Example\b", body)}

    conds = []
    for cm in _EXAMPLE_CRITERIA_RE.finditer(body):
        field = cm.group(2)[0].lower() + cm.group(2)[1:]
        col = ecols.get(field)
        if not col:
            continue  # 不是本实体列（其他类的 and 方法等），不收
        conds.append((cm.group(1).upper(), col, _EXAMPLE_OP_SQL[cm.group(3)]))
    if not conds:
        return []
    where_parts = []
    for i, (conj, col, op) in enumerate(conds):
        kw = "" if i == 0 else conj
        where_parts.append((kw + " " if kw else "") + f"{col} {op} ?")
    where_clause = " ".join(where_parts)
    cond_cols = [c for _c, c, _o in conds]

    recs = []
    for xm in re.finditer(
            r"\.\s*(\w+)\s*\(([^;{}]{0,200})", body):
        kind, full_cols = _EXAMPLE_CONSUME.get(xm.group(1).lower(), (None, None))
        if not kind:
            continue
        if not any(re.search(r"\b" + re.escape(v) + r"\b", xm.group(2)) for v in example_vars):
            continue
        if kind == "SELECT":
            if xm.group(1).lower().startswith("count"):
                text = f"SELECT COUNT(*) FROM {table} WHERE {where_clause}"
                cols = cond_cols  # COUNT 只依赖 WHERE 里的列
            else:
                text = f"SELECT * FROM {table} WHERE {where_clause}"
                cols = [f"{table}.{c} ({ent['name']}.{f})"
                        for f, c in ecols.items()]  # 行读取，全列
        elif kind == "DELETE":
            text = f"DELETE FROM {table} WHERE {where_clause}"
            cols = cond_cols
        else:
            text = f"UPDATE {table} SET ? WHERE {where_clause}"
            cols = [f"{table}.{c} ({ent['name']}.{f})" for f, c in ecols.items()]
        recs.append({"owner": owner, "via": "mp-example", "kind": kind, "text": text,
                     "tables": [table], "columns": sorted(set(cols))})
    return recs


def scan_inline_sql(classes, by_simple, table_to_entity):
    """扫所有方法体里的两类「不走 Mapper 接口」的 SQL：
      1. JdbcTemplate 裸 SQL：jdbcTemplate.update("INSERT ...") / queryForList("SELECT ...")
      2. MP Wrapper 动态链：new LambdaQueryWrapper<User>().eq(User::getName, ...) / lambdaQuery()...
    返回记录列表，字段：owner / via / kind / text / tables / columns。
    in_tx / routes 由主流程补。"""
    out = []
    ent_by_simple = {n: c for n, c in by_simple.items() if c.get("is_entity")}
    # ServiceImpl<XxxMapper, Entity> 的类 → Entity（lambdaQuery() 不带泛型时靠它）
    service_entity = {}
    for c in classes.values():
        sm = re.search(r"ServiceImpl<\s*(\w+)\s*,\s*(\w+)\s*>", c["extends"])
        if sm:
            service_entity[c["name"]] = sm.group(2)

    for c in classes.values():
        for meth in c["methods"]:
            body = meth.get("body_raw") or ""
            if not body:
                continue
            owner = f"{c['name']}#{meth['name']}"

            # 局部 String 变量名 -> SQL 文本（String sql = "..." + "..."; 这种写法）
            local_str = {}
            for lm in _LOCAL_STR_RE.finditer(body):
                start = body.index(lm.group(2).lstrip(), lm.start())
                txt = _leading_concat_strings(body, start)
                if txt:
                    local_str[lm.group(1)] = txt

            # ---- 1) JdbcTemplate 裸 SQL ----
            for jm in _JDBC_CALL_RE.finditer(body):
                api = jm.group(1).lower()
                sql = _leading_concat_strings(body, jm.end())
                if not sql:
                    # 首参不是字面量：局部变量 → 本类 static 常量 → 其他类常量（Foo.SQL_X）
                    arg_m = re.match(r"\s*([\w.]+)\b", body[jm.end():])
                    name = arg_m.group(1) if arg_m else ""
                    if "." in name:
                        cls_name, const_name = name.rsplit(".", 1)
                        ref = by_simple.get(cls_name.rsplit(".", 1)[-1])
                        sql = (ref or {}).get("static_strs", {}).get(const_name)
                    elif name in local_str:
                        sql = local_str[name]
                    else:
                        sql = c.get("static_strs", {}).get(name)
                if not sql or not re.search(r"\b(select|insert|update|delete|create|alter|drop)\b",
                                            sql, re.IGNORECASE):
                    continue
                first = re.match(r"\s*(\w+)", sql).group(1).upper()
                if api.startswith("query"):
                    kind = "SELECT"
                elif api in ("update", "batchupdate"):
                    kind = first if first in ("INSERT", "UPDATE", "DELETE") else "UPDATE"
                else:  # execute：看 SQL 首词
                    kind = first if first in ("SELECT", "INSERT", "UPDATE", "DELETE",
                                              "CREATE", "ALTER", "DROP") else "SELECT"
                tables = list(dict.fromkeys(t.lower() for t in SQL_TABLE_RE.findall(sql)))
                cols = resolve_sql_columns(sql, tables, table_to_entity)
                out.append({"owner": owner, "via": "jdbc-template", "kind": kind,
                            "text": sql, "tables": tables, "columns": sorted(set(cols))})

            # ---- 2) MP Wrapper 动态链 ----
            # 2a) 单语句内联链：new XxxWrapper<Entity>( ... 链到分号。
            #     赋值给变量的构造语句跳过（跨语句的完整链由 2c 的 def-use 重建，
            #     否则会多报一条只有构造语句的不完整记录）
            for wm in _WRAPPER_NEW_RE.finditer(body):
                seg_start = max(body.rfind(";", 0, wm.start()),
                                body.rfind("{", 0, wm.start()),
                                body.rfind("}", 0, wm.start()))
                if re.search(r"=\s*$", body[seg_start + 1:wm.start()]):
                    continue
                wtype, ent_name = wm.group(1), wm.group(2)
                rec = _wrapper_record(owner, _stmt_to_semicolon(body, wm.start()),
                                      wtype, ent_name, ent_by_simple, table_to_entity)
                if rec:
                    out.append(rec)
            # 2b) .lambdaQuery() / .lambdaUpdate()（ServiceImpl 里，实体从 ServiceImpl 泛型拿）
            for lm in _LAMBDA_ENTRY_RE.finditer(body):
                ent_name = service_entity.get(c["name"])
                if not ent_name:
                    continue
                wtype = "LambdaUpdateWrapper" if lm.group(1) == "lambdaUpdate" else "LambdaQueryWrapper"
                rec = _wrapper_record(owner, _stmt_to_semicolon(body, lm.start()),
                                      wtype, ent_name, ent_by_simple, table_to_entity)
                if rec:
                    out.append(rec)
            # 2c) 跨语句 def-use：Wrapper 拆成变量，定义/续链/消费分离的写法
            out.extend(_wrapper_defuse(owner, body, c, ent_by_simple, table_to_entity))

            # ---- 3) MBG Example 动态条件 ----
            out.extend(_example_defuse(owner, body, ent_by_simple, table_to_entity))
    return out


def _wrapper_record(owner, region, wtype, ent_name, ent_by_simple, table_to_entity):
    """把一段 Wrapper 链文本转成合成 SQL 记录。
    Entity::getXxx 方法引用 → 实体字段 → 列名；链动词决定列是 WHERE / SET / SELECT 子句。"""
    ent_obj = ent_by_simple.get(ent_name)
    if not ent_obj or not ent_obj.get("entity_columns"):
        return None
    table = ent_obj["table_name"]
    ecols = ent_obj["entity_columns"]  # field -> column

    where_cols, set_cols, select_cols, order_cols = [], [], [], []
    for rm in re.finditer(r"(\w+)\s*::\s*get(\w+)", region):
        ref_type, getter = rm.group(1), rm.group(2)
        if ref_type != ent_name:
            continue  # 别的实体的方法引用（如联表 DTO），不碰本表
        field = getter[0].lower() + getter[1:] if getter else ""
        col = ecols.get(field)
        if not col:
            continue
        verb = _enclosing_verb(region, rm.start()) or "eq"
        if verb in _VERB_SET:
            set_cols.append(col)
        elif verb in _VERB_SELECT:
            select_cols.append(col)
        elif verb.startswith("orderby") or verb == "groupby":
            order_cols.append(col)
        else:
            where_cols.append(col)  # eq/like/in 等条件列

    is_update = "UpdateWrapper" in wtype or bool(set_cols) or re.search(r"\.\s*update\s*\(", region)
    is_delete = not is_update and re.search(r"\.\s*(remove|delete)\s*\(", region)
    if is_update:
        kind = "UPDATE"
        set_clause = ", ".join(f"{c} = ?" for c in dict.fromkeys(set_cols)) or "?"
        where_clause = " AND ".join(f"{c} = ?" for c in dict.fromkeys(where_cols))
        text = f"UPDATE {table} SET {set_clause}" + (f" WHERE {where_clause}" if where_clause else "")
    elif is_delete:
        kind = "DELETE"
        where_clause = " AND ".join(f"{c} = ?" for c in dict.fromkeys(where_cols))
        text = f"DELETE FROM {table}" + (f" WHERE {where_clause}" if where_clause else "")
    else:
        kind = "SELECT"
        if select_cols:
            sel = ", ".join(dict.fromkeys(select_cols + where_cols + order_cols))
            text = f"SELECT {sel} FROM {table}"
        else:
            text = f"SELECT * FROM {table}"  # 无显式 select：MP 查整行，等同全列
        where_clause = " AND ".join(f"{c} = ?" for c in dict.fromkeys(where_cols))
        if where_clause:
            text += f" WHERE {where_clause}"
        if order_cols:
            text += " ORDER BY " + ", ".join(dict.fromkeys(order_cols))
    cols = resolve_sql_columns(text, [table], table_to_entity)
    return {"owner": owner, "via": "mp-wrapper", "kind": kind,
            "text": re.sub(r"\s+", " ", text).strip(),
            "tables": [table], "columns": sorted(set(cols))}


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
        # 这张表的限定前缀：表名本身 + 指向它的别名（c / comments）
        prefixes = {t} | {a for a, tt in alias_map.items() if tt == t}
        for fname, col in ent["entity_columns"].items():
            if star:
                cols.append(f"{t}.{col} ({ent['name']}.{fname})")
                continue
            # 带前缀：c.create_time / comments.create_time
            qualified = any(
                re.search(r"\b" + re.escape(p) + r"\." + re.escape(col) + r"\b", sql_for_cols)
                for p in prefixes)
            # 裸列名（前面不能是点，否则它属于别的别名，如 u.create_time 里的 create_time 不算）；
            # 多表 JOIN 时裸列名归属有歧义，保守归所有含该列的表（循环已按实体列过滤）
            bare = bool(re.search(r"(?<![\w.])" + re.escape(col) + r"\b", sql_for_cols))
            if qualified or bare:
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
    r"|(?:static\s+|final\s+)*"
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
        # 分组 1/2 = 带访问修饰符；分组 3/4 = 不带（包私有）
        ftype = fm.group(1) or fm.group(3)
        fname = fm.group(2) or fm.group(4)
        # 无修饰符分支会扫到方法体：`return order;` 会被误判为
        # 类型是 "return" 的字段，进而把 order.setX() 解析成 return#setX 调用边
        if fname and ftype and ftype.strip() not in RET_KEYWORDS:
            fields[fname] = simple_type(ftype)

    # 类级 static String 常量的字符串值：必须在 body_raw 上收（body_clean 里字面量已被抹白）。
    # 右值支持字面量拼接与同类常量互拼（SQL_A + "x"），迭代折叠到不动点；环/未知标识符放弃
    static_strs = {}
    pending = _static_str_fields(body_raw)
    progress = True
    while pending and progress:
        progress = False
        for name, tokens in list(pending.items()):
            parts, ok = [], True
            for kind_, val in tokens:
                if kind_ == "lit":
                    parts.append(val)
                elif val in static_strs:
                    parts.append(static_strs[val])
                else:
                    ok = False
                    break
            if ok:
                static_strs[name] = _join_sql_literal(" ".join(parts))
                del pending[name]
                progress = True

    # 实体信息：@TableName + 字段 -> 列名（MP 驼峰转下划线，@TableField 显式覆盖）
    table_name = None
    tm = re.search(r'@TableName\(\s*(?:value\s*=\s*)?"([^"]+)"', head_raw)
    if tm:
        table_name = tm.group(1)
    # 原生 MyBatis 兜底：model/domain/entity 包下的普通类（无 @TableName）也算实体，
    # 表名由类名驼峰转下划线推断（MyBatis Generator 风格）
    if table_name is None and kind == "class":
        pkg_parts = (pkg or "").split(".")
        if any(p in pkg_parts for p in ("model", "domain", "entity", "entities", "pojo", "beans")):
            # 排除明显不是实体的：带 Example/Criteria/Param/Query/VO/DTO/BO 后缀的
            if not re.search(r"(Example|Criteria|Param|Query|Vo|VO|Dto|DTO|Bo|BO|Wrapper)$", cname):
                table_name = camel_to_snake(cname)
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
            # 原始方法体（含字符串字面量）：JdbcTemplate 裸 SQL / Wrapper 链分析用
            "body_raw": raw[brace_idx:mb_end + 1] if end_char == "{" else "",
        })

    return {
        "fqn": fqn,
        "name": cname,
        "pkg": pkg,
        "kind": kind,
        "extends": extends,
        "implements": implements,
        "fields": fields,
        "static_strs": static_strs,
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


def tx_closure(graph, by_simple, impl_of):
    """事务闭包：@Transactional 方法 + 它们在同一事务里能触达的所有下游调用。
    语义依据 Spring REQUIRED 传播：事务内调用的下游代码也在事务里。
    同时处理接口方法上的 @Transactional：传播到其实现类的同名方法。"""
    seeds = set()
    for c in by_simple.values():
        for m in c["methods"]:
            if not m["transactional"]:
                continue
            if c["kind"] == "class":
                seeds.add((c["name"], m["name"]))
            elif c["kind"] == "interface":
                # 接口方法标了 @Transactional：找实现类同名方法作为种子
                impl_name = impl_of.get(c["name"])
                if impl_name:
                    seeds.add((impl_name, m["name"]))
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
    # 支持多模块：ROOT 下所有 src/main/java 目录都扫（单模块项目就是一个）
    src_roots = set()
    if os.path.isdir(JAVA_SRC):
        src_roots.add(JAVA_SRC)
    for dirpath, dirnames, _fn in os.walk(ROOT):
        if os.sep + "target" + os.sep in dirpath + os.sep:
            dirnames[:] = []
            continue
        if dirpath.endswith(os.path.join("src", "main", "java")):
            src_roots.add(dirpath)
            dirnames[:] = []  # 不再深入，src/main/java 下没有子模块
    for src in src_roots:
        for dirpath, dirnames, filenames in os.walk(src):
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
    tx_seeds, tx_inside = tx_closure(graph, by_simple, impl_of)

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
    xml_stmts = {}
    # 多模块：扫所有 src/main/resources 和 src/main/java 下的 .xml
    # （MyBatis 允许 XML 与 Mapper 接口同目录放置）
    for dirpath, _dn, filenames in os.walk(ROOT):
        if os.sep + "target" + os.sep in dirpath + os.sep:
            continue
        in_java = os.sep + os.path.join("src", "main", "java") + os.sep in dirpath + os.sep
        in_res = os.sep + os.path.join("src", "main", "resources") + os.sep in dirpath + os.sep
        if not (in_java or in_res):
            continue
        for fn in filenames:
            if not fn.endswith(".xml"):
                continue
            path = os.path.join(dirpath, fn)
            xml_stmts.update(_parse_xml_file(path, table_to_entity_for_xml, by_simple))

    # 逆向索引
    rindex = reverse_index(graph, routes)

    # 内嵌 SQL（JdbcTemplate 裸 SQL / MP Wrapper 动态链）
    inline_sql = scan_inline_sql(classes, by_simple, table_to_entity)
    route_of_node = {(r["controller"], r["handler"]): r for r in routes}
    for rec in inline_sql:
        ocls, ometh = rec["owner"].split("#", 1)
        rec["in_tx"] = (ocls, ometh) in tx_inside
        # 上游路由：Controller 方法自身就是路由；Service 方法走逆向索引
        if (ocls, ometh) in route_of_node:
            r = route_of_node[(ocls, ometh)]
            rec["routes"] = [{"method": r["method"], "path": r["path"]}]
        else:
            ri = rindex.get(rec["owner"])
            rec["routes"] = ri["routes"] if ri else []
        rec["file"] = os.path.relpath(by_simple[ocls]["file"], ROOT)

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

    # 内嵌 SQL（JdbcTemplate / MP Wrapper）
    out.append("---")
    out.append("")
    out.append("## 七、内嵌 SQL（不走 Mapper 接口：JdbcTemplate 裸 SQL / MP Wrapper 动态链）")
    out.append("")
    out.append("> 这类 SQL 散落在 Service/Controller/Config 里，传统 Mapper 索引完全看不到。")
    out.append("")
    if inline_sql:
        for rec in inline_sql:
            via = {"jdbc-template": "JdbcTemplate", "mp-wrapper": "MP Wrapper",
                   "mp-example": "MP Example"}.get(rec["via"], rec["via"])
            tx = "  🔒事务内" if rec["in_tx"] else ""
            out.append(f"- **{rec['owner']}** — @{rec['kind']}（{via}）{tx}  (`{rec['file']}`)")
            short = rec["text"] if len(rec["text"]) <= 120 else rec["text"][:117] + "..."
            out.append(f"  - `{short}`")
            if rec["tables"]:
                out.append(f"  - 涉及表: {', '.join('`' + t + '`' for t in rec['tables'])}")
            if rec["routes"]:
                out.append("  - 上游路由: " + ", ".join(
                    f"`{r['method']} {r['path']}`" for r in rec["routes"]))
    else:
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
                                    else xml_stmts.get(f"{mp['name']}#{meth['name']}")
                                    or (mp_builtin_sql_record(meth["name"],
                                                              by_simple.get(mp["base_entity"]))
                                        if meth["name"] in MP_BUILTIN else None)),
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
        # 不走 Mapper 接口的 SQL：JdbcTemplate 裸 SQL / MP Wrapper 动态链
        "inline_sql": inline_sql,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[OK] 扫描 {len(java_files)} 个 Java 文件，{len(classes)} 个类，{len(routes)} 条路由")
    print(f"[OK] 事务闭包: {len(tx_inside)} 个方法 | 实体: {len(entities)} 个 | "
          f"逆向索引: {sum(1 for k in rindex if 'Mapper#' in k)} 个 Mapper 方法")
    print(f"[OK] 地图已生成: {OUT}")
    print(f"[OK] JSON 已生成: {OUT_JSON}")


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
