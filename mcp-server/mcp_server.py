#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_server.py — ContextGate：框架语义 MCP Server

把 analyzer 分析器产出的 framework_map.json 变成 AI 编程工具可直接调用的工具：

  trace_call(query, project)   正向追踪：路由("GET /orders/my")或方法("OrderServiceImpl#create")
                               → 完整框架调用链（Controller → Service → Mapper → SQL）
  find_sql(query, project)     反查 SQL：Mapper 方法名或 SQL 片段 → SQL 全文 + 表 + 列 + 上游路由
  impact(entity, field, project) 影响面：改实体/字段 → 波及的 SQL、路由、事务内写操作
  list_maps()                  列出地图目录里已注册的项目地图（多项目模式）
  refresh_map(project_root)    重新运行分析器刷新地图（代码改动后调一次）

数据源: framework_map.json（默认用仓库自带 examples/demo-framework-map.json，
可用环境变量 CODECONTEXT_MAP 覆盖；refresh_map 用 CODECONTEXT_PROJECT 作为默认项目路径）。
多项目模式（可选）: 配置 CODECONTEXT_MAPS_DIR 指向一个地图目录，每个项目一张
<项目名>.json，refresh_map 自动注册新项目，查询工具用 project 参数切换项目。
"""
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

from mcp.server.fastmcp import FastMCP

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MAP = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "examples", "demo-framework-map.json"))
DEFAULT_ANALYZER = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "analyzer", "framework_map.py"))
# 自带 demo 项目，零配置即可体验（正式使用请用 CODECONTEXT_PROJECT 指向你的项目）
DEFAULT_PROJECT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "examples", "demo-project"))

MAP_PATH = os.environ.get("CODECONTEXT_MAP", DEFAULT_MAP)
PROJECT_ROOT = os.environ.get("CODECONTEXT_PROJECT", DEFAULT_PROJECT)
# 多项目模式（可选）：配置了地图目录后，每个项目一张 <项目名>.json，
# refresh_map 自动注册新项目，查询工具用 project 参数在项目间切换
MAPS_DIR = os.environ.get("CODECONTEXT_MAPS_DIR", "")

HTTP_VERBS = {"GET", "POST", "PUT", "DELETE", "PATCH", "ANY"}

_state = {"maps": {}, "active": None}


def _load_map_file(path):
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"地图文件不存在: {path}\n请先运行 analyzer/framework_map.py，或调用 refresh_map 工具生成。")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_data():
    """加载启动地图。多项目模式加载地图目录里全部 *.json（项目名取 meta.project）；
    单地图模式加载 MAP_PATH。返回默认（活跃）地图。"""
    _state["maps"] = {}
    if MAPS_DIR and os.path.isdir(MAPS_DIR):
        for fn in sorted(os.listdir(MAPS_DIR)):
            if not fn.endswith(".json"):
                continue
            try:
                d = _load_map_file(os.path.join(MAPS_DIR, fn))
            except Exception:
                continue
            name = (d.get("meta") or {}).get("project") or fn[:-5]
            _state["maps"][name] = d
        if _state["maps"] and _state["active"] not in _state["maps"]:
            _state["active"] = sorted(_state["maps"])[0]
        return _state["maps"].get(_state["active"])
    d = _load_map_file(MAP_PATH)
    _state["maps"][MAP_PATH] = d
    _state["active"] = MAP_PATH
    return d


def data():
    if _state["active"] is None or _state["active"] not in _state["maps"]:
        load_data()
    return _state["maps"][_state["active"]]


def _resolve_project(project):
    """工具入口用：把可选 project 参数解析为本次查询的项目并设为活跃。
    单地图模式 no-op；多项目模式下空串=当前活跃项目，找不到时抛 KeyError
    （由各工具的兜底 except 转成可读提示）。"""
    name = (project or "").strip()
    if not MAPS_DIR:
        return
    if not name:
        if _state["active"] is None:
            load_data()
        return
    if name not in _state["maps"]:
        hit = next((k for k in _state["maps"] if k.lower() == name.lower()), None)
        if not hit:
            avail = ", ".join(sorted(_state["maps"])) or "（地图目录为空，先调 refresh_map 生成）"
            raise KeyError(f"项目 '{name}' 不在地图目录 {MAPS_DIR} 里。可用项目: {avail}")
        name = hit
    _state["active"] = name


mcp = FastMCP("contextgate")


# ---------------------------------------------------------------- 查询辅助

def find_routes(query: str):
    """按 'GET /path' 或 '/path 片段' 匹配路由。"""
    q = query.strip()
    verb = None
    parts = q.split(None, 1)
    if len(parts) == 2 and parts[0].upper() in HTTP_VERBS:
        verb, q = parts[0].upper(), parts[1].strip()
    hits = []
    # 精确路径优先：查询串与路由路径全等（可按尾斜杠/大小写差异容忍）直接命中，
    # 避免「/orders/search」被子串匹配拖进 /search-alias 等一族的歧义列表
    exact = [r for r in data()["routes"]
             if (verb or "ANY") and q and r["path"].strip("/") == q.strip("/")]
    if verb:
        exact = [r for r in exact if r["method"] in (verb, "ANY")]
    if exact:
        return exact
    for r in data()["routes"]:
        if q and q not in r["path"]:
            continue
        if verb and r["method"] not in (verb, "ANY"):
            continue
        hits.append(r)
    return hits


def find_graph_nodes(query: str):
    """按 'Class#method' 或裸方法名在调用图里找节点。"""
    q = query.strip()
    graph = data()["call_graph"]
    if "#" in q:
        if q in graph:
            return [q]
        # 接口名 → 找同名方法
        mname = q.split("#", 1)[1]
        return [k for k in graph if k.endswith("#" + mname)]
    return [k for k in graph if k.endswith("#" + q)] or \
           [k for k in graph if k.split("#", 1)[1].startswith(q)]


def mapper_sql_map():
    """mapper方法名 -> {class, sql:{kind,text,tables,columns}, reverse:{...}}"""
    out = {}
    for mp in data()["mappers"]:
        for meth in mp["methods"]:
            out[f"{mp['class']}#{meth['name']}"] = {
                "mapper_class": mp["class"],
                "sql": meth.get("sql"),
                "reverse": meth.get("reverse") or {},
            }
    return out


# ---------------------------------------------------------------- 工具1：正向追踪

@mcp.tool()
def trace_call(query: str, project: str = "") -> str:
    """正向追踪调用链。输入一个 HTTP 路由（如 "POST /orders/my"）或方法名
    （如 "BizOrderServiceImpl#create" 或裸方法名 "create"），
    返回完整的框架调用链树：Controller → Service → Mapper → SQL，含事务标记。
    project: 多项目模式下的项目名（不传=当前活跃项目）。"""
    try:
        _resolve_project(project)
        query = query.strip()
        start_nodes = []
        route_header = None

        rh = find_routes(query)
        if not rh:
            # 严格（动词+路径）没命中 → 退化为纯路径匹配（动词可能记错）
            rh = find_routes(query.split(None, 1)[1] if
                             query.strip().split(None, 1)[0].upper() in HTTP_VERBS
                             and len(query.strip().split(None, 1)) == 2 else query)
        if rh:
            if len(rh) > 5:
                lst = "\n".join(f"- `{r['method']} {r['path']}`" for r in rh[:10])
                return f"匹配到 {len(rh)} 条路由，请精确输入：\n{lst}"
            route_header = rh[0]
            start_nodes = [f"{route_header['controller']}#{route_header['handler']}"]
        else:
            start_nodes = find_graph_nodes(query)
            if not start_nodes:
                return (f"没找到匹配 '{query}' 的路由或方法。\n"
                        f"提示: 路由用 'GET /xxx' 格式，方法用 '类名#方法名' 或裸方法名。")
            if len(start_nodes) > 5:
                lst = "\n".join(f"- {k}" for k in start_nodes[:10])
                return f"匹配到 {len(start_nodes)} 个方法，请精确输入：\n{lst}"

        graph = data()["call_graph"]
        tx_seeds = set(data()["transactional"]["seeds"])
        tx_inside = set(data()["transactional"]["inside_closure"])
        smap = mapper_sql_map()
        # 内嵌 SQL（JdbcTemplate / Wrapper）按所属方法挂到调用链节点上
        inline_by_owner = {}
        for rec in data().get("inline_sql", []):
            inline_by_owner.setdefault(rec["owner"], []).append(rec)

        out_lines = []
        if route_header:
            out_lines.append(f"**{route_header['method']} {route_header['path']}**")
        node_count = 0
        MAX_NODES = 60

        def render(node, depth, path):
            nonlocal node_count
            if node_count >= MAX_NODES:
                out_lines.append("  " * depth + "└─ ...（节点数超限截断）")
                return
            node_count += 1
            prefix = "  " * depth
            branch = "└─ " if depth > 0 else ""
            cls, meth = node.split("#", 1)
            if node in tx_seeds:
                tag = "  [@Transactional]"
            elif node in tx_inside:
                tag = "  [在事务内]"
            else:
                tag = ""
            sql_info = smap.get(node, {}).get("sql")
            extra = ""
            if sql_info:
                if sql_info.get("mp_builtin"):
                    extra = f"  → @{sql_info['kind']} (MP 内置)"
                else:
                    extra = f"  → @{sql_info['kind']} 自定义SQL"
            out_lines.append(f"{prefix}{branch}{cls}#{meth}{tag}{extra}")
            if sql_info and not sql_info.get("mp_builtin"):
                sql_text = sql_info["text"]
                short = sql_text if len(sql_text) <= 110 else sql_text[:107] + "..."
                out_lines.append(f"{prefix}      `{short}`")
            if sql_info and sql_info.get("sub_selects"):
                out_lines.append(f"{prefix}  ↳ N+1 子查询: {', '.join(sql_info['sub_selects'])}")
            # 该方法体内写死的 SQL：JdbcTemplate 裸 SQL / MP Wrapper 动态链
            for rec in inline_by_owner.get(node, []):
                label = {"jdbc-template": "JdbcTemplate", "mp-wrapper": "MP Wrapper",
                         "mp-example": "MP Example"}.get(rec["via"], rec["via"])
                txflag = " 🔒事务内" if rec.get("in_tx") else ""
                out_lines.append(f"{prefix}  → @{rec['kind']} ({label}){txflag}")
                txt = rec["text"]
                short = txt if len(txt) <= 110 else txt[:107] + "..."
                out_lines.append(f"{prefix}      `{short}`")
            for edge in graph.get(node, []):
                child = f"{edge['class']}#{edge['method']}"
                if child in path:
                    out_lines.append(f"{prefix}  ├─ {edge['class']}#{edge['method']}  ↩ 循环，截断")
                    continue
                wtag = " ✍️写" if edge.get("is_db_write") else ""
                if wtag and not smap.get(child, {}).get("sql"):
                    pass  # MP 内置写，显示 ✍️
                path2 = path | {child}
                before = len(out_lines)
                render(child, depth + 1, path2)
                # 给 mapper 写操作补标记
                if wtag and len(out_lines) > before:
                    for i in range(before, len(out_lines)):
                        if child in out_lines[i] and "✍️" not in out_lines[i]:
                            out_lines[i] = out_lines[i].replace("  →", " ✍️  →", 1) if "→" in out_lines[i] else out_lines[i]
                            break

        for sn in start_nodes:
            render(sn, 0 if route_header else 0, {sn})
        return "\n".join(out_lines)
    except Exception as e:
        return f"[trace_call 出错] {e}"


# ---------------------------------------------------------------- 工具2：反查 SQL

@mcp.tool()
def find_sql(query: str, project: str = "") -> str:
    """反查 SQL。输入 Mapper 方法名（如 "selectMyOrders"）或 SQL 片段
    （如 "wallet_balance"、"biz_order"），返回 SQL 全文、涉及表、触碰列、
    上游调用者和路由。改 SQL 前必查。
    project: 多项目模式下的项目名（不传=当前活跃项目）。"""
    try:
        _resolve_project(project)
        q = query.strip()
        if not q:
            return "请输入 Mapper 方法名或 SQL 片段。"
        ql = q.lower()
        hits = []
        for key, info in mapper_sql_map().items():
            sql = info["sql"]
            if not sql:
                continue
            # MP 内置方法的合成 SQL 不参与反查——它的 text 是占位符，搜了也没意义
            if sql.get("mp_builtin"):
                continue
            if ql in key.lower() or ql in sql["text"].lower():
                hits.append((key, info))
        # 内嵌 SQL（JdbcTemplate / Wrapper）：散在方法体里，Mapper 索引看不到
        inline_hits = [rec for rec in data().get("inline_sql", [])
                       if ql in rec["owner"].lower() or ql in rec["text"].lower()]
        if not hits and not inline_hits:
            return f"没找到匹配 '{q}' 的自定义 SQL。\n提示: 也可以输入表名或列名片段。"
        out = [f"找到 {len(hits) + len(inline_hits)} 条匹配（最多显示 8 条）：", ""]
        for key, info in hits[:8]:
            sql = info["sql"]
            rev = info["reverse"]
            out.append(f"**{key}** — @{sql['kind']}")
            out.append(f"- SQL: `{sql['text']}`")
            if sql.get("tables"):
                out.append(f"- 涉及表: {', '.join('`' + t + '`' for t in sql['tables'])}")
            if sql.get("columns"):
                out.append(f"- 触碰列: {', '.join('`' + c + '`' for c in sql['columns'])}")
            callers = rev.get("direct_callers", [])
            if callers:
                out.append(f"- 直接调用者: {', '.join('`' + c + '`' for c in callers)}")
            routes = rev.get("routes", [])
            if routes:
                out.append("- 上游路由: " + ", ".join(f"`{r['method']} {r['path']}`" for r in routes))
            if sql.get("sub_selects"):
                out.append("- N+1 子查询: " + ", ".join(f"`{s}`" for s in sql["sub_selects"]))
            out.append("")
        for rec in inline_hits:
            label = {"jdbc-template": "JdbcTemplate", "mp-wrapper": "MP Wrapper",
                         "mp-example": "MP Example"}.get(rec["via"], rec["via"])
            txflag = "  🔒事务内" if rec.get("in_tx") else ""
            out.append(f"**{rec['owner']}** — @{rec['kind']}（{label}）{txflag}")
            out.append(f"- SQL: `{rec['text']}`")
            if rec.get("tables"):
                out.append(f"- 涉及表: {', '.join('`' + t + '`' for t in rec['tables'])}")
            if rec.get("columns"):
                out.append(f"- 触碰列: {', '.join('`' + c + '`' for c in rec['columns'])}")
            if rec.get("routes"):
                out.append("- 上游路由: " + ", ".join(
                    f"`{r['method']} {r['path']}`" for r in rec["routes"]))
            if rec.get("sub_selects"):
                out.append("- N+1 子查询: " + ", ".join(f"`{s}`" for s in rec["sub_selects"]))
            out.append("")
        return "\n".join(out)
    except Exception as e:
        return f"[find_sql 出错] {e}"


# ---------------------------------------------------------------- 工具3：影响面

@mcp.tool()
def impact(entity: str, field: str = "", project: str = "") -> str:
    """实体变更影响面。输入实体名（如 "SysUser"），可选字段名（如 "openid"）。
    返回：哪些自定义 SQL 会受影响、波及多少路由、哪些写操作在事务里、
    有多少 MP 内置 CRUD 调用点。给实体加/删/改字段前必查。
    project: 多项目模式下的项目名（不传=当前活跃项目）。"""
    try:
        _resolve_project(project)
        ents = [e for e in data()["entities"] if e["name"].lower() == entity.strip().lower()]
        if not ents:
            names = ", ".join(e["name"] for e in data()["entities"])
            return f"实体 '{entity}' 不存在。可用实体: {names}"
        ent = ents[0]
        table = ent["table"]
        columns = ent["columns"] or {}
        field = field.strip()
        col = None
        if field:
            # 字段名大小写不敏感匹配
            col = next((c for f, c in columns.items() if f.lower() == field.lower()), None)
            if col is None:
                fl = ", ".join(f"`{f}`" for f in columns)
                return f"实体 {ent['name']} 没有字段 '{field}'。可用字段: {fl}"

        # 关联的专属 Mapper
        own_mappers = [m["class"] for m in data()["mappers"] if m.get("base_entity") == ent["name"]]

        tx_inside = set(data()["transactional"]["inside_closure"])
        # 事务路径上的方法（种子 + 闭包内）：用于给每个调用者单独标注，
        # 避免点级标记读起来像"所有调用者都在事务里"
        tx_nodes = tx_inside | set(data()["transactional"]["seeds"])
        # 内嵌 SQL 按 owner 索引：声明的 mapper 方法没有注解/XML SQL 时，
        # 其动态条件（Wrapper 链等）记录在这里，兜底时替代"列未知"
        inline_by_owner = {r["owner"]: r for r in data().get("inline_sql", [])}
        own_mapper_set = set(own_mappers)
        affected_sqls = []      # (mapper#method, sql, in_tx)  自定义 SQL（含跨表 JOIN 触碰）
        mp_sites = []           # (key, sql|None, [callers])  MP 内置调用点（事务标记逐调用者给）
        mp_routes = []          # MP 方法上游路由
        for key, info in mapper_sql_map().items():
            rev = info["reverse"]
            sql = info["sql"]
            if sql and table in (sql.get("tables") or []):
                # 不限制 mapper 归属：别的 Mapper 的 JOIN SQL 只要读了本表，也算触碰
                # （如 BizOrderMapper#selectMyOrders 里 j.title 会影响 BizJob）。
                # 列级过滤对自定义 SQL 和 MP 合成 SQL 都适用：
                # columns 条目形如 "table.col (Entity.field)"
                if col is not None:
                    marker = f"{table}.{col} ({ent['name']}.{field})"
                    if marker not in (sql.get("columns") or []):
                        continue
                if sql.get("mp_builtin"):
                    callers = rev.get("direct_callers", [])
                    if callers:
                        mp_sites.append((key, sql, callers))
                        mp_routes.extend(rev.get("routes", []))
                else:
                    affected_sqls.append((key, sql, key in tx_inside))
            elif not sql and info["mapper_class"] in own_mapper_set:
                # 本实体专属 Mapper 里没有静态 SQL 的方法：
                # 优先用内嵌 SQL 记录（Wrapper 动态链的合成结果），实在没有才列未知
                callers = rev.get("direct_callers", [])
                if callers:
                    mp_sites.append((key, inline_by_owner.get(key), callers))
                    mp_routes.extend(rev.get("routes", []))

        # 内嵌 SQL（JdbcTemplate / Wrapper）：同样按表/列过滤
        inline_hits = []
        for rec in data().get("inline_sql", []):
            if table not in (rec.get("tables") or []):
                continue
            if col is not None:
                marker = f"{table}.{col} ({ent['name']}.{field})"
                if marker not in (rec.get("columns") or []):
                    continue
            inline_hits.append(rec)

        # 汇总路由
        route_set = {}
        for key, sql, _ in affected_sqls:
            for r in (info_routes(key)):
                route_set[f"{r['method']} {r['path']}"] = r
        for r in mp_routes:
            route_set[f"{r['method']} {r['path']}"] = r
        for rec in inline_hits:
            for r in rec.get("routes", []):
                route_set[f"{r['method']} {r['path']}"] = r

        out = [f"## 影响面: {ent['name']} → 表 `{table}`" + (f"（字段 `{field}` → 列 `{col}`）" if field else "（实体级）"), ""]
        out.append(f"- 专属 Mapper: {', '.join(f'`{m}`' for m in own_mappers) or '无'}")
        out.append(f"- 被自定义 SQL 触碰: {len(affected_sqls)} 处"
                   + (f"（其中内嵌 {len(inline_hits)} 处）" if inline_hits else ""))
        out.append(f"- MP 内置 CRUD 调用点: {len(mp_sites)} 个方法（已展开为全列触碰）")
        out.append(f"- 波及路由: {len(route_set)} 条")
        out.append("")
        if affected_sqls:
            out.append("### 受影响的自定义 SQL")
            out.append("")
            for key, sql, in_tx in affected_sqls:
                # 写在事务里标"事务内写"，读只标"事务内"（回滚边界同样值得关注）
                tx_flag = ("  🔒事务内写" if in_tx and sql["kind"] != "SELECT"
                           else "  🔒事务内" if in_tx else "")
                out.append(f"- **{key}** — @{sql['kind']}{tx_flag}")
                short = sql["text"] if len(sql["text"]) <= 110 else sql["text"][:107] + "..."
                out.append(f"  - `{short}`")
            out.append("")
        if inline_hits:
            out.append("### 受影响的内嵌 SQL（JdbcTemplate / MP Wrapper，不走 Mapper 接口）")
            out.append("")
            for rec in inline_hits:
                label = {"jdbc-template": "JdbcTemplate", "mp-wrapper": "MP Wrapper",
                         "mp-example": "MP Example"}.get(rec["via"], rec["via"])
                tx_flag = ("  🔒事务内写" if rec.get("in_tx") and rec["kind"] != "SELECT"
                           else "  🔒事务内" if rec.get("in_tx") else "")
                out.append(f"- **{rec['owner']}** — @{rec['kind']}（{label}）{tx_flag}")
                short = rec["text"] if len(rec["text"]) <= 110 else rec["text"][:107] + "..."
                out.append(f"  - `{short}`")
            out.append("")
        if mp_sites:
            out.append("### MP 内置 CRUD 调用点（SELECT * / 全表写，触碰所有实体列）")
            out.append("")
            for key, sql, callers in mp_sites:
                tail = (f" 等 {len(callers)} 处" if len(callers) > 6 else "")
                # 事务标记跟着调用者走：只有从事务路径调进来的才标 🔒
                callers_str = ", ".join(
                    f"`{c}` 🔒" if c in tx_nodes else f"`{c}`" for c in callers[:6])
                if sql:
                    ncol = len(sql.get("columns", []))
                    out.append(f"- **{key}** — @{sql.get('kind','?')}（触碰 {ncol} 列）← {callers_str}{tail}")
                else:
                    out.append(f"- **{key}** （列未知，实体未解析）← {callers_str}{tail}")
            out.append("")
        if route_set:
            out.append("### 波及路由")
            out.append("")
            for rp in sorted(route_set):
                out.append(f"- `{rp}`")
            out.append("")
        if field and not affected_sqls and not mp_sites and not inline_hits:
            out.append(f"（字段 `{field}` 未被任何自定义 SQL、内嵌 SQL 或 MP 内置方法触碰——可能确实无人使用。）")
        return "\n".join(out)
    except Exception as e:
        return f"[impact 出错] {e}"


def info_routes(key):
    """从 JSON 里取某条 SQL 的上游路由。"""
    cls, meth = key.split("#", 1)
    for mp in data()["mappers"]:
        if mp["class"] != cls:
            continue
        for meth_info in mp["methods"]:
            if meth_info["name"] == meth:
                return (meth_info.get("reverse") or {}).get("routes", [])
    return []


# ---------------------------------------------------------------- 工具4：列出项目地图

@mcp.tool()
def list_maps() -> str:
    """列出地图目录里已注册的项目地图（多项目模式）。
    返回每个项目的路由/Mapper/实体数量与地图生成时间，以及当前活跃项目。
    未配置 CODECONTEXT_MAPS_DIR 时为单地图模式。"""
    try:
        if not MAPS_DIR:
            return (f"单地图模式（未配置 CODECONTEXT_MAPS_DIR 环境变量）。\n"
                    f"当前地图: {MAP_PATH}")
        if not _state["maps"]:
            load_data()
        if not _state["maps"]:
            return f"地图目录为空: {MAPS_DIR}（用 refresh_map 生成第一张地图）"
        out = [f"地图目录: {MAPS_DIR}", f"活跃项目: {_state['active']}", ""]
        for name, d in sorted(_state["maps"].items()):
            meta = d.get("meta") or {}
            mark = " ← 活跃" if name == _state["active"] else ""
            out.append(f"- **{name}**{mark}: {meta.get('routes', '?')} 路由 / "
                       f"{meta.get('mappers', '?')} Mapper / "
                       f"{meta.get('entities', '?')} 实体（{meta.get('generated_at', '?')}）")
        return "\n".join(out)
    except Exception as e:
        return f"[list_maps 出错] {e}"


# ---------------------------------------------------------------- 工具5：刷新地图

@mcp.tool()
def refresh_map(project_root: str = "") -> str:
    """重新运行分析器，刷新框架地图（代码改动后调用）。
    project_root 为 Spring Boot 项目根目录；若已通过环境变量
    CODECONTEXT_PROJECT 配置过，可不传。多项目模式（CODECONTEXT_MAPS_DIR）
    下按项目目录名落盘 <项目名>.json 并注册为活跃项目。"""
    try:
        root = project_root.strip() or PROJECT_ROOT
        if not root:
            return ("未指定项目路径。请传入 project_root 参数，"
                    "或在 MCP 配置里设置环境变量 CODECONTEXT_PROJECT。")
        if not os.path.isdir(root):
            return f"项目目录不存在: {root}"
        if MAPS_DIR:
            # 多项目：地图按项目目录名落盘到地图目录，注册并设为活跃
            os.makedirs(MAPS_DIR, exist_ok=True)
            name = os.path.basename(os.path.normpath(root))
            map_md = os.path.join(MAPS_DIR, name + ".md")
        else:
            # 单地图：把分析结果写到当前地图位置（.json 换成 .md 作为分析器输出参数），
            # 这样 refresh 后 load_data() 读到的一定是刚生成的地图
            name = None
            map_md = os.path.splitext(MAP_PATH)[0] + ".md"
        proc = subprocess.run(
            [sys.executable, DEFAULT_ANALYZER, root, map_md],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
            stdin=subprocess.DEVNULL,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if MAPS_DIR:
            d = _load_map_file(os.path.join(MAPS_DIR, name + ".json"))
            _state["maps"][name] = d
            _state["active"] = name
            meta = d["meta"]
        else:
            load_data()
            meta = data()["meta"]
        head = f"[refresh_map 完成]\n{out.strip()}\n"
        if MAPS_DIR:
            head += f"项目: {name}（已注册，设为活跃）\n"
        return (head + f"当前地图: {meta['routes']} 路由 / {meta['mappers']} Mapper / "
                f"{meta['entities']} 实体（{meta['generated_at']}）")
    except Exception as e:
        return f"[refresh_map 出错] {e}"


# ---------------------------------------------------------------- 启动

if __name__ == "__main__":
    try:
        load_data()
        if MAPS_DIR:
            print(f"[codecontext] 多项目模式，地图目录: {MAPS_DIR}，"
                  f"已加载 {len(_state['maps'])} 个项目", file=sys.stderr)
        else:
            print(f"[codecontext] 地图已加载: {MAP_PATH}", file=sys.stderr)
    except FileNotFoundError as e:
        print(f"[codecontext] {e}", file=sys.stderr)
    mcp.run()  # stdio 传输，供 Trae/Cursor/Claude Code 等客户端拉起
