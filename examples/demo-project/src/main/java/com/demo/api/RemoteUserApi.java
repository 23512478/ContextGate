package com.demo.api;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;

/**
 * 跨服务 Feign 接口：跑在 demo-server 进程里，别的微服务靠它远程查用户。
 * 服务名和路径全部是常量拼出来的（yudao 三层链：RpcConstants → ApiConstants → XxxApi），
 * 静态分析器必须把常量折叠到底，才算真正连上了这条边。
 */
@FeignClient(name = DemoApiConstants.NAME)
public interface RemoteUserApi {

    String PREFIX = DemoApiConstants.PREFIX + "/user";

    @GetMapping(PREFIX + "/get")
    Object getUser(@RequestParam("id") Long id);
}
