package com.demo.service;

import org.springframework.stereotype.Component;

/** 工厂类：产品类型写在 create 方法签名上（验证工厂方法返回值接收者推断）。 */
@Component
public class SupportFactory {

    /** 工厂方法：返回类型 OrderQuerySupport 是静态可知的，与参数/方法体无关。 */
    public OrderQuerySupport create() {
        return new OrderQuerySupport();
    }
}
