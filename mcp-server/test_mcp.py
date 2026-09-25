#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_mcp.py — MCP Server 冒烟测试（零依赖，测试数据用仓库自带 examples/demo-project）

模拟真实客户端：拉起 mcp_server.py 子进程，走 stdio JSON-RPC 握手，
依次调用 trace_call / find_sql / impact / refresh_map，打印返回并做关键断言。

用法: python test_mcp.py
（默认指向 examples 下的 demo 项目和 demo 地图；
  可用环境变量 CODECONTEXT_PROJECT / CODECONTEXT_MAP 覆盖到你自己的项目）
"""
import json
import subprocess
import sys
import os
import shutil
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
SERVER = os.path.join(HERE, "mcp_server.py")

PROJECT = os.environ.get(
    "CODECONTEXT_PROJECT", os.path.join(ROOT, "examples", "demo-project"))
MAP = os.environ.get(
    "CODECONTEXT_MAP", os.path.join(ROOT, "examples", "demo-framework-map.json"))

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
    env["CODECONTEXT_MAP"] = MAP
    env["CODECONTEXT_PROJECT"] = PROJECT
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
        assert set(tools) >= {"trace_call", "find_sql", "impact", "refresh_map", "list_maps"}, "工具缺失"

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

        # 7.11 内嵌 SQL：MP Wrapper 动态链（trace_call 节点上显示 MP Wrapper 合成 SQL）
        print("\n" + "=" * 70)
        print("### trace_call('GET /api/v1/orders/search')  ← Wrapper 动态 SQL")
        print("-" * 70)
        out_wrapper = call_tool(proc, "trace_call", {"query": "GET /api/v1/orders/search"})
        print(out_wrapper)
        assert "(MP Wrapper)" in out_wrapper, "Wrapper 链应在调用链节点上标注 MP Wrapper"
        assert "SELECT * FROM orders" in out_wrapper, "Wrapper 应合成为 SELECT * 全列"

        # 7.12 内嵌 SQL：JdbcTemplate 裸 SQL（变量传参 + 调用链标注）
        out_jdbc_chain = call_tool(proc, "trace_call", {"query": "GET /api/v1/stats/wallets/top"})
        assert "(JdbcTemplate)" in out_jdbc_chain, "JdbcTemplate 裸 SQL 应在调用链上标注"
        assert "wallet_balance" in out_jdbc_chain, "裸 SQL 文本应出现在调用链上"

        # 7.13 内嵌 SQL 进影响面：wallet_balance 被 StatsService 裸 SELECT 触碰
        out_wallet_inline = call_tool(proc, "impact", {"entity": "User", "field": "walletBalance"})
        assert "StatsService#topWallets" in out_wallet_inline, \
            "JdbcTemplate 裸 SELECT wallet_balance 应计入 User 影响面"
        assert "内嵌 SQL" in out_wallet_inline, "impact 应有内嵌 SQL 分段"
        # Order.title 被 Wrapper .like 条件触碰
        out_order_inline = call_tool(proc, "impact", {"entity": "Order", "field": "title"})
        assert "OrderServiceImpl#searchByTitle" in out_order_inline, \
            "MP Wrapper .like(Order::getTitle) 应计入 Order.title 影响面"

        # 7.14 find_sql 反查内嵌 SQL
        out_find_inline = call_tool(proc, "find_sql", {"query": "topWallets"})
        assert "JdbcTemplate" in out_find_inline and "StatsService#topWallets" in out_find_inline, \
            "find_sql 应能反查 JdbcTemplate 裸 SQL"

        # 7.15 原生 MyBatis 实体（无 @TableName，model 包）能被识别 + 字段级影响面
        out_prod = call_tool(proc, "impact", {"entity": "Product", "field": "stock"})
        assert "Product" in out_prod and "stock" in out_prod, \
            "无 @TableName 的原生 MyBatis 实体应能被识别并支持字段级影响面"
        assert "ProductMapper#deductStock" in out_prod, \
            "UPDATE product SET stock... 应计入 Product.stock 影响面"

        # 7.16 接口方法上的 @Transactional 应传播到实现类（trace_call 显示事务标记）
        out_tx_iface = call_tool(proc, "trace_call", {"query": "POST /api/v1/products/purchase"})
        assert "[@Transactional]" in out_tx_iface or "事务" in out_tx_iface, \
            "接口方法 @Transactional 应传播到 impl，trace_call 应显示事务标记"
        assert "ProductMapper#deductStock" in out_tx_iface, \
            "purchase 链路应追到 ProductMapper#deductStock"

        # 7.17 XML <foreach>：open/close 属性应重建，IN (…) 形状与列保留
        out_foreach = call_tool(proc, "find_sql", {"query": "listByRatings"})
        assert "IN ( #{r} )" in out_foreach, "<foreach> 的 open/close 应重建进 SQL 文本"
        assert "comments.rating (Comment.rating)" in out_foreach, "<foreach> 条件列应保留"

        # 7.18 resultMap extends：父映射的聚合别名列应流入子 resultMap
        #      （COUNT() AS review_count 经 AS 剥离后文本归因拿不到，只有继承映射能归因）
        out_ext = call_tool(proc, "find_sql", {"query": "selectBrief"})
        assert "comments.review_count (Comment.content)" in out_ext, \
            "extends 父映射的列应流入子 resultMap"

        # 7.19 association/collection 嵌套：嵌套列应归因到 javaType/ofType 对应实体
        out_assoc = call_tool(proc, "find_sql", {"query": "selectWithUser"})
        assert "users.mask (User.openid)" in out_assoc, \
            "association 嵌套列应归因到 User（而非外层 Comment）"
        assert "comments.reply_count (Comment.rating)" in out_assoc, \
            "collection 嵌套列应归因到 Comment"

        # 7.20 回归：逗号清理不能吃掉 "id, order_id" 的逗号（order_id 的 order 前缀曾被误当 ORDER 关键字）
        assert "id, order_id" in out_foreach, "列清单里的逗号不应被误清理"

        # 7.21 类级 static final SQL 常量：JdbcTemplate 首参是常量名也应解析出 SQL 全文
        out_const = call_tool(proc, "trace_call", {"query": "GET /api/v1/stats/openid/count"})
        assert "(JdbcTemplate)" in out_const, "常量 SQL 应在调用链上标注 JdbcTemplate"
        assert "openid_total" in out_const and "SQL_DEMO_OPENID" not in out_const, \
            "应解析出 static final 常量里的 SQL 全文，而不是停在常量名"

        # 7.22 Wrapper 拆变量跨语句链式调用：定义/分支续链/消费点分离应拼出完整条件
        out_flex = call_tool(proc, "trace_call", {"query": "GET /api/v1/orders/search-flexible"})
        assert "(MP Wrapper)" in out_flex, "跨语句 Wrapper 应在调用链上标注"
        assert "title = ?" in out_flex and "create_time = ?" in out_flex and "status = ?" in out_flex, \
            "if 分支内续链的 gt(create_time) 应与其他条件一起拼进合成 SQL"
        out_flex_imp = call_tool(proc, "impact", {"entity": "Order", "field": "createTime"})
        assert "searchOrdersFlexible" in out_flex_imp, \
            "分支续链触碰的 create_time 应计入 Order 影响面"

        # 7.23 常量互拼：SQL_A + "x" 折叠出完整 SQL（WHERE_OPENID 流入 SQL_OPENID_DETAIL）
        out_const2 = call_tool(proc, "trace_call", {"query": "GET /api/v1/stats/openid/detail"})
        assert "FROM users WHERE openid = 'demo-openid'" in out_const2, \
            "常量互拼应折叠出完整 SQL（含引用的 WHERE_OPENID 片段）"

        # 7.24 Wrapper 拷贝别名：w2 = w 共享底层链，w 的 eq + w2 的 like 都在
        out_alias = call_tool(proc, "trace_call", {"query": "GET /api/v1/orders/search-alias"})
        assert "status = ?" in out_alias and "title = ?" in out_alias, \
            "别名共享链应同时含 w 的 eq(status) 与 w2 的 like(title)"

        # 7.25 MP 内置 count：COUNT(*) 不触碰业务列（0 列），字段级影响面不应命中
        out_count = call_tool(proc, "trace_call", {"query": "GET /api/v1/wallet/count"})
        assert "selectCount" in out_count, "count 调用应出现在链路上"
        out_nick_count = call_tool(proc, "impact", {"entity": "User", "field": "nickname"})
        assert "countUsers" not in out_nick_count, \
            "selectCount 不触碰业务列，字段级影响面不应命中"
        out_ent_user = call_tool(proc, "impact", {"entity": "User"})
        assert "触碰 0 列" in out_ent_user, "实体级影响面应显示 count 触碰 0 列"

        # 7.26 MBG Example：createCriteria().andXxxEqualTo + selectByExample 合成 WHERE
        out_example = call_tool(proc, "trace_call", {"query": "GET /api/v1/wallet/search-example"})
        assert "nickname = ?" in out_example and "(MP Example)" in out_example, \
            "Example 动态条件应合成 WHERE 并标注 MP Example"
        out_nick_example = call_tool(proc, "impact", {"entity": "User", "field": "nickname"})
        assert "searchExample" in out_nick_example, \
            "Example 条件列 nickname 应计入 User 影响面"

        # 7.27 Wrapper 作方法参数：参数当已定义变量，方法内续链+消费归消费方法
        out_param = call_tool(proc, "trace_call", {"query": "GET /api/v1/orders/search-param"})
        assert "(MP Wrapper)" in out_param and "status = ?" in out_param, \
            "Wrapper 参数应在方法内续链并消费，合成 SQL 标在消费方法"
        out_param_imp = call_tool(proc, "impact", {"entity": "Order", "field": "status"})
        assert "searchByWrapperParam" in out_param_imp, \
            "Wrapper 参数方法内条件列 status 应计入 Order 影响面"

        # 7.28 XML 懒加载子查询：<association select=...> 应标注 N+1，子查询语句本身可见
        out_lazy = call_tool(proc, "find_sql", {"query": "selectLazy"})
        assert "N+1 子查询" in out_lazy and "selectUserById" in out_lazy, \
            "懒加载子查询链接应在 find_sql 标注"
        out_lazy_chain = call_tool(proc, "trace_call", {"query": "GET /api/v1/comments/lazy"})
        assert "N+1 子查询" in out_lazy_chain and "selectUserById" in out_lazy_chain, \
            "懒加载子查询应在调用链上标注"
        out_sub = call_tool(proc, "find_sql", {"query": "selectUserById"})
        assert "users.nickname (User.nickname)" in out_sub, \
            "无 Java 接口方法的 XML 子查询语句也应可反查"

        # 7.29 跨方法 Wrapper 构建：lqw = buildOrderWrapper(status)，helper 条件归并到消费点
        out_helper = call_tool(proc, "trace_call", {"query": "GET /api/v1/orders/search-helper"})
        assert "(MP Wrapper)" in out_helper and "status = ?" in out_helper and "title = ?" in out_helper, \
            "helper 方法体里的条件应归并进消费方法的合成 SQL"
        out_helper_imp = call_tool(proc, "impact", {"entity": "Order", "field": "title"})
        assert "searchByHelper" in out_helper_imp, \
            "helper 构建条件触碰的 title 应计入 Order 影响面"

        # 7.30 Mapper default 方法 this.lambda() 链：select+eq 合成，实体取 Mapper 泛型
        print("\n" + "=" * 70)
        print("### find_sql('selectByNicknameLambda')  ← mapper default 方法 lambda() 链")
        print("-" * 70)
        out_lamb = call_tool(proc, "find_sql", {"query": "selectByNicknameLambda"})
        print(out_lamb)
        assert "（MP Wrapper）" in out_lamb and "SELECT id, nickname FROM users WHERE nickname = ?" in out_lamb, \
            "mapper default 方法的 lambda() 链应合成 SQL 并能反查"

        # 7.31 X 后缀扩展 Wrapper（LambdaQueryWrapperX，yudao 风格）
        out_xwrap = call_tool(proc, "find_sql", {"query": "selectByIdX"})
        assert "SELECT * FROM users WHERE id = ?" in out_xwrap, \
            "LambdaQueryWrapperX 应被识别为 Wrapper 链"

        # 7.32 字段值便捷方法：selectOne(Entity::getField, value)（yudao/BaseMapperPlus 风格）
        out_field = call_tool(proc, "find_sql", {"query": "selectByNicknameField"})
        assert "SELECT * FROM users WHERE nickname = ?" in out_field, \
            "selectOne(Entity::getField, value) 应合成 WHERE 条件"

        # 7.33 ServiceImpl 继承式调用：this.getById() 应归到泛型 M 的 baseMapper.selectById
        out_svc = call_tool(proc, "trace_call", {"query": "GET /api/v1/products/detail"})
        assert "ProductMapper#selectById" in out_svc, \
            "ServiceImpl 继承方法 getById() 应映射到泛型 M 的 selectById 内置方法"

        # 7.34 跨类 helper + 套 helper：buildOrderWrapper 调 OrderQuerySupport.buildBase
        #      （跨类，且 buildOrderWrapper 自身也是 helper=套娃）
        out_helper2 = call_tool(proc, "find_sql", {"query": "searchByHelper"})
        assert "status = ?" in out_helper2 and "title = ?" in out_helper2, \
            "跨类 helper（buildBase）的条件应连同本类 helper 的条件一起归并"

        # 7.35 Wrapper 跨类传播：条件在调用方拼、消费在目标类
        out_prop = call_tool(proc, "find_sql", {"query": "searchByWrapper"})
        assert out_prop.count("SELECT * FROM orders WHERE status = ? AND id = ?") == 1, \
            "跨类传播后应恰好一条完整记录（调用方 status + 目标方法内 id），本地降级版被剔除"
        assert "WHERE id = ?" not in out_prop.replace("status = ? AND id = ?", ""), \
            "不应再有缺失调用方条件的降级版"

        # 7.36 Example 参数跨类传播 + ⑤ criteria 分组语义
        out_exprop = call_tool(proc, "find_sql", {"query": "searchByExample"})
        assert "SELECT * FROM users WHERE nickname = ?" in out_exprop, \
            "Example 参数传播：调用方拼的 andNicknameEqualTo 应出现在目标方法的合成 SQL"
        out_exgrp = call_tool(proc, "find_sql", {"query": "searchExample"})
        assert "(nickname = ?) OR (create_time > ?)" in out_exgrp, \
            "criteria 分组：AND 组/or() 组应带括号、OR 连接（旧版是平铺无括号）"

        # 7.37 跨类常量互拼：SQL_OPENID_CROSS 引用 SqlParts.OPENID_WHERE
        out_const_cross = call_tool(proc, "find_sql", {"query": "demoOpenidCross"})
        assert "SELECT id, nickname FROM users WHERE openid = 'demo-openid'" in out_const_cross, \
            "引用其他类常量（SqlParts.OPENID_WHERE）应全局折叠出完整 SQL"

        # 7.38 Example 参数多跳传播：Controller 拼 nickname → 中转层拼 create_time → 终点消费
        out_relay = call_tool(proc, "find_sql", {"query": "searchByRelay"})
        assert "(nickname = ?) AND (create_time > ?)" in out_relay, \
            "Example 多跳：终点合成 SQL 应同时含 Controller（两跳前）和中转层的条件"
        assert out_relay.count("SELECT * FROM users WHERE") == 1, \
            "Example 多跳：终点应恰好一条完整记录（互传/自环不应产生重复落地）"

        # 7.39 链式返回值接收者：orderQuerySupport.getSelf().listUsersDirect()
        out_chain = call_tool(proc, "trace_call", {"query": "GET /api/v1/wallet/chain-call"})
        assert "listUsersDirect" in out_chain and "selectById" in out_chain, \
            "链式调用：中间 getter 的返回类型可解析，尾方法应接入调用链直到 Mapper 内置方法"

        # 7.40 方法内 new 局部对象 / var 关键字：类型不在注入字段表里也应断链重连
        out_local = call_tool(proc, "trace_call", {"query": "GET /api/v1/wallet/local-new"})
        assert "listUsersDirect" in out_local and "selectById" in out_local, \
            "局部 new 的对象：局部变量类型表应把断掉的链接回 Mapper"
        out_var = call_tool(proc, "trace_call", {"query": "GET /api/v1/wallet/local-var"})
        assert "selectById" in out_var, \
            "var v = new T()：类型应从 new 右值取"

        # 7.41 Wrapper .select() 列裁剪：MP 内置 selectList 的保守全列应收窄到 select 列
        out_sel = call_tool(proc, "find_sql", {"query": "selPrune"})
        assert "SELECT id, nickname FROM users WHERE id = ?" in out_sel, \
            "Wrapper .select() 消费点的 mp-wrapper 记录应裁剪到 select 列"
        out_sel_imp = call_tool(proc, "impact", {"entity": "User"})
        assert any("selectList" in ln and "触碰 2 列" in ln and "✂" in ln
                   for ln in out_sel_imp.splitlines()), \
            "MP 内置 selectList 的全列记录应按 Wrapper .select() 收窄为实际列（✂ 标记）"
        assert any("selectByExample" in ln and "触碰 5 列" in ln
                   for ln in out_sel_imp.splitlines()), \
            "Example 消费没有 select 概念，selectByExample 应保持全列不裁"

        # 7.42 getter 带参的链式中转：getService(userId) 带参，尾方法 listUsersDirect 应接入
        out_carg = call_tool(proc, "trace_call", {"query": "GET /api/v1/wallet/chain-arg"})
        assert "listUsersDirect" in out_carg and "selectById" in out_carg, \
            "带参 getter 中转：尾方法应接入调用链直到 Mapper 内置方法"

        # 7.43 运行期接收者：getBean 链式 / var+getBean / Object 字段（直调+强转）
        out_bean = call_tool(proc, "trace_call", {"query": "GET /api/v1/wallet/bean-chain"})
        assert "listUsersDirect" in out_bean and "selectById" in out_bean \
            and "ApplicationContext" not in out_bean, \
            "getBean(X.class).m()：类型应从 .class 参数取，且不再产生 getBean 噪音边"
        out_bvar = call_tool(proc, "trace_call", {"query": "GET /api/v1/wallet/bean-var"})
        assert "selectById" in out_bvar, \
            "var v = ctx.getBean(X.class)：类型应从 .class 参数取"
        out_objf = call_tool(proc, "trace_call", {"query": "GET /api/v1/wallet/obj-field"})
        assert "listUsersDirect" in out_objf and "selectById" in out_objf, \
            "Object 字段：@PostConstruct 里 new 赋值应推断出真实类型"
        out_ocast = call_tool(proc, "trace_call", {"query": "GET /api/v1/wallet/obj-cast"})
        assert "selectById" in out_ocast, \
            "((X) helper).m() 强转调用：强转类型即接收者类型"

        # 7.44 工厂方法返回值接收者：var f = buildXxx() / factory.build() / 字段工厂赋值
        out_flocal = call_tool(proc, "trace_call", {"query": "GET /api/v1/wallet/factory-local"})
        assert "listUsersDirect" in out_flocal and "selectById" in out_flocal, \
            "var svc = buildSupport()：本类工厂方法产品类型应从签名 ret_type 取"
        out_fbean = call_tool(proc, "trace_call", {"query": "GET /api/v1/wallet/factory-bean"})
        assert "SupportFactory" in out_fbean and "listUsersDirect" in out_fbean \
            and "selectById" in out_fbean, \
            "var svc = supportFactory.create()：recv 类型 + create 的 ret_type 逐节解析"
        out_ffield = call_tool(proc, "trace_call", {"query": "GET /api/v1/wallet/factory-field"})
        assert "listUsersDirect" in out_ffield and "selectById" in out_ffield, \
            "made = supportFactory.create() 字段赋值：工厂描述符应延迟解析出产品类型"

        # 7.45 JdbcTemplate 局部 String 单赋值传播：方法内 final 片段折叠进完整 SQL
        out_local_sql = call_tool(proc, "find_sql", {"query": "demoOpenidLocal"})
        assert "SELECT id, nickname FROM users WHERE openid = 'local-pin'" in out_local_sql, \
            "局部 final String 片段（cols/tail）应不动点折叠进 sql 变量的完整 SQL"
        out_inline_sql = call_tool(proc, "find_sql", {"query": "demoOpenidLocalInline"})
        assert "SELECT COUNT(*) AS c FROM users WHERE openid = 'inline-pin'" in out_inline_sql, \
            "jdbc 首参直接 \"...\" + 局部常量 时应内联续拼，不留半截 SQL"

        # 7.46 自定义泛型基类（非 ServiceImpl）：M/T 沿多层泛型继承折叠
        # GenericOrderService(无自有方法) extends MidOrderService<Order>
        #   extends AbstractEntityService<OrderMapper, T>，路由调 midGet
        # 要穿过 self 继承节点，最终接到 OrderMapper#selectById
        print("\n" + "=" * 70)
        print("### trace_call('GET /api/v1/orders/generic-detail')  ← 自定义泛型基类继承链")
        print("-" * 70)
        out_generic = call_tool(proc, "trace_call",
                                {"query": "GET /api/v1/orders/generic-detail"})
        print(out_generic)
        assert "GenericOrderService#midGet" in out_generic, \
            "具体子类无自有方法：继承来的 midGet 节点应靠继承解析补建"
        assert "GenericOrderService#genericGetById" in out_generic, \
            "midGet 裸调基类 genericGetById：self 边要跨泛型层接通"
        assert "OrderMapper#selectById" in out_generic, \
            "M 字段（protected M mapper）沿两层泛型继承折叠后应接到 OrderMapper#selectById"

        # 7.47 Mapper 泛型经自定义泛型 Mapper 接口链折叠：
        # OrderMapper 现在 extends SuperMapper<Order>（不再直接 BaseMapper<Order>），
        # 实体归因仍得是 Order——impact 应能看到泛型基类那两个调用点
        out_imp_order = call_tool(proc, "impact", {"entity": "Order"})
        assert "GenericOrderService#genericGetById" in out_imp_order, \
            "SuperMapper<T> 接口链折叠出实体 Order 后，泛型调用点应计入 Order 影响面"

        # 7.48 真运行期拼参①：方法参数直接内联，骨架保留 + ? 占位 + 表/列归因 + 提示
        print("\n" + "=" * 70)
        print("### find_sql('runtimeConcatInline')  ← 方法参数拼进 SQL，降级 ? 占位")
        print("-" * 70)
        out_rt_inline = call_tool(proc, "find_sql", {"query": "runtimeConcatInline"})
        print(out_rt_inline)
        assert "SELECT id, nickname FROM users WHERE id = ?" in out_rt_inline, \
            "拼了静态不可知的方法参数：SQL 骨架必须保留，未知值降级为 ?"
        assert "users.id (User.id)" in out_rt_inline and "users.nickname (User.nickname)" \
            in out_rt_inline, "? 占位不影响表/列归因"
        assert "运行期拼参" in out_rt_inline, "has_runtime_param 记录应渲染出提示"

        # 7.49 真运行期拼参②：方法调用返回值（normalize(userId)）同样降级 ?
        out_rt_call = call_tool(proc, "find_sql", {"query": "runtimeConcatCall"})
        assert "SELECT id, nickname FROM users WHERE id = ?" in out_rt_call, \
            "方法调用返回值拼进 SQL：括号整体平衡跳过，值降级为 ?，骨架保留"

        # 7.50 真运行期拼参③：先拼进局部 sql 变量再整变量传参，标记随变量继承
        out_rt_var = call_tool(proc, "find_sql", {"query": "runtimeConcatVar"})
        assert "SELECT id, nickname FROM users WHERE id = ?" in out_rt_var, \
            "局部变量折叠遇运行期成分不再整块丢弃：变量传参路径也要拿到骨架"
        assert "运行期拼参" in out_rt_var, "变量路径应继承 has_runtime_param 标记"
        # trace_call 视图也要看到骨架和提示
        out_rt_trace = call_tool(proc, "trace_call",
                                 {"query": "GET /api/v1/stats/runtime/inline"})
        assert "WHERE id = ?" in out_rt_trace and "运行期拼参" in out_rt_trace, \
            "trace_call 行内 SQL 渲染也要带 ? 骨架与运行期提示"

        # 7.51 Guns 风格自定义路由注解：path 属性优先提取，不是第一个字符串字面量
        out_guns = call_tool(proc, "trace_call",
                             {"query": "GET /api/v1/wallet/guns-resource"})
        assert "GET /api/v1/wallet/guns-resource" in out_guns, \
            "自定义 @GetResource(path=...) 应识别为 GET 路由"
        assert "UserMapper#selectById" in out_guns, \
            "自定义注解路由的调用链应能接到下游 Mapper"

        # 8. refresh_map（真实重跑分析器，结果写回 demo 地图）
        print("\n" + "=" * 70)
        print(f"### refresh_map('{PROJECT}')")
        print("-" * 70)
        print(call_tool(proc, "refresh_map", {"project_root": PROJECT}))

        # 8.1 回归：@MapperScan 启动类（javadoc 里还提到 @Mapper）不应被误判为 Mapper
        out_notmapper = call_tool(proc, "find_sql", {"query": "DemoApplication"})
        assert "没找到匹配" in out_notmapper, \
            "@MapperScan 启动类不应被误判为 Mapper，javadoc 提及注解也不应触发"

        # 8.2 回归：MapStruct 的 @Mapper（import org.mapstruct.Mapper）不是 MyBatis Mapper
        out_notmybatis = call_tool(proc, "find_sql", {"query": "OrderConvert"})
        assert "没找到匹配" in out_notmybatis, \
            "MapStruct 转换器的 @Mapper 不应被误判为 MyBatis Mapper"

        print("\n" + "=" * 70)
        print("[全部通过] MCP Server 工作正常")
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)

    # 9. 多项目模式：CODECONTEXT_MAPS_DIR 地图目录 + project 参数切换
    maps_dir = tempfile.mkdtemp(prefix="contextgate_maps_")
    try:
        env2 = dict(os.environ)
        env2["CODECONTEXT_MAPS_DIR"] = maps_dir
        env2.pop("CODECONTEXT_MAP", None)
        proc2 = subprocess.Popen(
            [sys.executable, SERVER],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", env=env2,
        )
        try:
            send(proc2, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke-test-multi", "version": "0.1"},
            })
            send(proc2, "notifications/initialized", {}, notify=True)

            print("\n" + "=" * 70)
            print("### 多项目模式：refresh_map 注册项目 → project 参数切换")
            print("-" * 70)
            out_lm0 = call_tool(proc2, "list_maps", {})
            assert "地图目录为空" in out_lm0, "初始应为空地图目录"
            # 注册 demo 项目（refresh_map 自动落盘 <项目名>.json）
            out_rf = call_tool(proc2, "refresh_map", {"project_root": PROJECT})
            assert "已注册" in out_rf, "多项目模式 refresh_map 应注册项目"
            # project 参数查询（显式 + 省略）
            out_tc = call_tool(proc2, "trace_call",
                               {"query": "GET /api/v1/orders/my", "project": "demo-project"})
            assert "OrderMapper#selectMyOrders" in out_tc, "显式 project 应能查询"
            out_tc2 = call_tool(proc2, "trace_call", {"query": "GET /api/v1/orders/my"})
            assert "OrderMapper#selectMyOrders" in out_tc2, "省略 project 应查活跃项目"
            out_fs = call_tool(proc2, "find_sql", {"query": "wallet_balance", "project": "Demo-Project"})
            assert "UserMapper#addBalance" in out_fs, "project 名大小写不敏感"
            out_lm = call_tool(proc2, "list_maps", {})
            print(out_lm)
            assert "**demo-project** ← 活跃" in out_lm, "list_maps 应列出已注册项目并标活跃"
            # 不存在的项目应给出可用列表
            out_bad = call_tool(proc2, "impact", {"entity": "User", "project": "no-such"})
            assert "可用项目" in out_bad and "demo-project" in out_bad, \
                "未知项目应提示可用项目列表"
            print("[多项目模式通过]")
        finally:
            proc2.stdin.close()
            proc2.wait(timeout=10)
    finally:
        shutil.rmtree(maps_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
