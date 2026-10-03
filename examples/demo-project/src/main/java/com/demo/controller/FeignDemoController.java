package com.demo.controller;

import com.demo.api.RemoteUserApi;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import javax.annotation.Resource;

/**
 * Feign 调用方：本进程的业务通过注入的 Feign 接口跨服务取数据。
 * 调用链在这里出进程：Controller →(🌐 feign) demo-server GET /rpc-api/demo/user/get
 * →(🛂 服务端) RemoteUserApiImpl → UserMapper。
 */
@RestController
public class FeignDemoController {

    @Resource
    private RemoteUserApi remoteUserApi;

    @GetMapping("/api/v1/feign/user")
    public Object remoteUser(@RequestParam Long id) {
        return remoteUserApi.getUser(id);
    }
}
