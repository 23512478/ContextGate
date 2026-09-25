package com.demo.annotation;

import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.lang.annotation.*;

/**
 * 类级组合路由注解（模拟 jetlinks / lamp 一类框架的形态：
 * 自定义注解上直接元标注 @RestController + @RequestMapping）。
 * 只标在类上；类本身哪怕一个方法都没有（CRUD 全靠继承泛型基类），
 * 分析器也应凭元注解把它识别成 Controller，类前缀只取显式 path。
 */
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
@RestController
@RequestMapping
public @interface AdminApi {

    /** 类级路径前缀（显式 path，绝不退化为注解里的第一个字符串）。 */
    String path() default "";
}
