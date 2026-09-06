#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_mcp.py — MCP Server 冒烟测试（零依赖，测试数据用仓库自带 examples/demo-project）

模拟真实客户端：拉起 mcp_server.py 子进程，走 stdio JSON-RPC 握手，
依次调用 trace_call / find_sql / impact / refresh_map，打印返回并做关键断言。

用法: python test_mcp.py
（默认指向 examples 下的 demo 项目和 demo 地图；
  可用环境变量 CONTEXTGATE_PROJECT / CONTEXTGATE_MAP 覆盖到你自己的项目）
"""
import json
import subprocess
import sys
import os

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
SERVER = os.path.join(HERE, "mcp_server.py")

PROJECT = os.environ.get(
    "CONTEXTGATE_PROJECT", os.path.join(ROOT, "examples", "demo-project"))
MAP = os.environ.get(
    "CONTEXTGATE_MAP", os.path.join(ROOT, "examples", "demo-framework-map.json"))

_id = 0


def send(proc, method, params=None, notify=False):
    global _id
    msg = {"jsonrpc": "2.0", "method": method}
    if not notify:
        _id += 1
        msg["id"] = _id
    if params is not None:
        msg["params"] = params
    proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
    proc.stdin.flush()
    if notify:
        return None
    # 读到对应 id 的响应
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("server closed stdout")
        resp = json.loads(line)
        if resp.get("id") == _id:
            return resp


def call_tool(proc, name, arguments):
    resp = send(proc, "tools/call", {"name": name, "arguments": arguments})
    if "error" in resp:
        return f"[JSON-RPC error] {resp['error']}"
    content = resp["result"].get("content", [])
    texts = [c.get("text", "") for c in content if c.get("type") == "text"]
    return "\n".join(texts)


def main():
    # 显式注入 demo 地图/项目，保证测试不受使用者全局环境变量影响
    env = dict(os.environ)
    env["CONTEXTGATE_MAP"] = MAP
    env["CONTEXTGATE_PROJECT"] = PROJECT
    proc = subprocess.Popen(
        [sys.executable, SERVER],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", env=env,
    )
    try:
        # 1. 握手
        resp = send(proc, "initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "smoke-test", "version": "0.1"},
        })
        info = resp["result"]
        print(f"[握手 OK] server={info['serverInfo']['name']} "
              f"protocol={info['protocolVersion']}")
        send(proc, "notifications/initialized", {}, notify=True)

        # 2. 工具列表
        resp = send(proc, "tools/list", {})
        tools = [t["name"] for t in resp["result"]["tools"]]
        print(f"[工具列表] {tools}")
        assert set(tools) >= {"trace_call", "find_sql", "impact", "refresh_map"}, "工具缺失"

        # 3. trace_call: 路由查询（故意写错动词 POST，实测动词回退匹配）
        print("\n" + "=" * 70)
        print("### trace_call('POST /orders/my')  ← 动词写错，应回退到 GET")
        print("-" * 70)
        out = call_tool(proc, "trace_call", {"query": "POST /orders/my"})
        print(out)
        assert "GET /api/v1/orders/my" in out, "应回退匹配到 GET 路由"
        assert "OrderMapper#selectMyOrders" in out, "调用链应到 Mapper 自定义 SQL"

        # 4. trace_call: 事务方法查询（MP 内置方法应显示 (MP 内置) 标记）
        print("\n" + "=" * 70)
        print("### trace_call('OrderServiceImpl#create')")
        print("-" * 70)
        out = call_tool(proc, "trace_call", {"query": "OrderServiceImpl#create"})
        print(out)
        assert "[@Transactional]" in out, "create 应标为事务种子"
        assert "(MP 内置)" in out, "MP 内置方法不应显示为自定义SQL"

        # 5. find_sql
        print("\n" + "=" * 70)
        print("### find_sql('wallet_balance')")
        print("-" * 70)
        out = call_tool(proc, "find_sql", {"query": "wallet_balance"})
        print(out)
        assert "UserMapper#addBalance" in out, "应反查到 addBalance"
        assert "POST /api/v1/wallet/recharge" in out, "应给出上游路由"

        # 6. impact: 实体级
        print("\n" + "=" * 70)
        print("### impact('User')")
        print("-" * 70)
        print(call_tool(proc, "impact", {"entity": "User"}))

        # 7. impact: 字段级（walletBalance 是全限定类型 java.math.BigDecimal，回归用例）
        print("\n" + "=" * 70)
        print("### impact('User', field='walletBalance')  ← 全限定类型字段 + MP 列展开")
        print("-" * 70)
        out_wallet = call_tool(proc, "impact", {"entity": "User", "field": "walletBalance"})
        print(out_wallet)
        assert "addBalance" in out_wallet, "addBalance 写 wallet_balance 应命中"
        assert "selectById" in out_wallet, "MP 内置 selectById（SELECT *）应触碰 wallet_balance"
        assert "列未知" not in out_wallet, "User 的 MP 内置不应再出现列未知"

        # 7.6 裸 SELECT * 展开回归：Message.content 只在 SELECT * 里出现
        out_star = call_tool(proc, "impact", {"entity": "Message", "field": "content"})
        assert "selectRecent" in out_star, "裸 SELECT * 应展开为实体全列，content 命中"

        # 7.7 跨表 JOIN 归属回归：User.nickname 被订单查询 u.nickname 读取
        out_cross = call_tool(proc, "impact", {"entity": "User", "field": "nickname"})
        assert "OrderMapper#selectMyOrders" in out_cross, "跨表 JOIN 读 u.nickname 应计入 User 影响面"

        # 7.8 XML mapper 回归：trace_call 走到 XML 里的 SQL（resultMap + include + JOIN）
        print("\n" + "=" * 70)
        print("### trace_call('GET /api/v1/comments/{id}')  ← SQL 在 CommentMapper.xml")
        print("-" * 70)
        out_xml_chain = call_tool(proc, "trace_call", {"query": "GET /api/v1/comments/{id}"})
        print(out_xml_chain)
        assert "CommentMapper#selectDetail" in out_xml_chain, "XML 语句应出现在调用链上"

        # 7.9 XML mapper 回归：find_sql 反查 XML 语句（裸 SELECT * 展开 + <set> 动态 SQL）
        print("\n" + "=" * 70)
        print("### find_sql('listByOrderId')  ← 反查 XML <select>")
        print("-" * 70)
        out_find_xml = call_tool(proc, "find_sql", {"query": "listByOrderId"})
        print(out_find_xml)
        assert "CommentMapper#listByOrderId" in out_find_xml, "XML <select> 应被 find_sql 反查"
        assert "GET /api/v1/comments/order/" in out_find_xml, "XML 语句也应能逆向到路由"

        # 7.10 XML mapper 回归：impact 覆盖 resultMap / SELECT * / <set update 三类 XML 语句，
        #       且 XML 里的 JOIN 读 u.nickname 应跨表计入 User
        out_comment = call_tool(proc, "impact", {"entity": "Comment", "field": "content"})
        print("\n" + "=" * 70)
        print("### impact('Comment', field='content')  ← 三类 XML 语句都应命中")
        print("-" * 70)
        print(out_comment)
        assert "selectDetail" in out_comment, "resultMap 语句应命中 content"
        assert "listByOrderId" in out_comment, "XML 裸 SELECT * 应展开命中 content"
        assert "updateContent" in out_comment, "<set> 更新语句应命中 content"
        # XML 里的 JOIN 读 u.nickname：跨表计入 User 影响面
        out_nick_xml = call_tool(proc, "impact", {"entity": "User", "field": "nickname"})
        assert "CommentMapper#selectDetail" in out_nick_xml, \
            "XML JOIN 读 u.nickname 应跨表计入 User 影响面"

        # 8. refresh_map（真实重跑分析器，结果写回 demo 地图）
        print("\n" + "=" * 70)
        print(f"### refresh_map('{PROJECT}')")
        print("-" * 70)
        print(call_tool(proc, "refresh_map", {"project_root": PROJECT}))

        print("\n" + "=" * 70)
        print("[全部通过] MCP Server 工作正常")
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


if __name__ == "__main__":
    main()
