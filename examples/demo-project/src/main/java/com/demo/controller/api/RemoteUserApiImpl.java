package com.demo.controller.api;

import com.demo.api.RemoteUserApi;
import com.demo.mapper.UserMapper;
import org.springframework.web.bind.annotation.RestController;

import javax.annotation.Resource;

/**
 * Feign 接口的服务端实现：mapping 注解全在接口上，本类只有 @Override。
 * 分析器需要沿 implements 把接口上的 HTTP 契约继承过来，
 * 才能发现 GET /rpc-api/demo/user/get 这条隐藏在接口上的路由。
 */
@RestController
public class RemoteUserApiImpl implements RemoteUserApi {

    @Resource
    private UserMapper userMapper;

    @Override
    public Object getUser(Long id) {
        // 远程打进来的请求最终落到本地 Mapper，逆向索引应能反查到 rpc-api 路由
        return userMapper.selectById(id);
    }
}
