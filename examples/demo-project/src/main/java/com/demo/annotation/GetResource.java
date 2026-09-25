package com.demo.annotation;

import java.lang.annotation.*;

/**
 * 模拟 Guns 框架的自定义路由注解（@GetResource 的简化版）。
 * 真实场景：注解是 @RequestMapping 的组合注解，路径在显式 path 属性上，
 * 且第一个字符串字面量是 name（资源名）而非路径——旧版取第一个字符串会取错。
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface GetResource {

    /** 资源名称（必填，写前面模拟 Guns 的参数顺序）。 */
    String name();

    /** 请求路径。 */
    String path() default "";
}
