package com.demo.common;

/**
 * 公共 RPC 前缀常量（对应 yudao 里的 RpcConstants）。
 * 接口里的 String 字段是隐式 public static final，故意不加修饰符，
 * 用来验证分析器对接口常量的识别。
 */
public interface RpcConstants {

    String RPC_API_PREFIX = "/rpc-api";
}
