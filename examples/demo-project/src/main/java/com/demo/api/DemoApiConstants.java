package com.demo.api;

import com.demo.common.RpcConstants;

/**
 * demo-server 对外 RPC 契约的常量（对应 yudao 每个 *-api 模块里的 ApiConstants）。
 * PREFIX 引用另一个包的常量再拼一段，验证跨类常量折叠靠 import 找对归属类。
 */
public interface DemoApiConstants {

    String NAME = "demo-server";

    String PREFIX = RpcConstants.RPC_API_PREFIX + "/demo";
}
