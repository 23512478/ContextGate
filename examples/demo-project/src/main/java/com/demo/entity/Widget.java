package com.demo.entity;

import com.baomidou.mybatisplus.annotation.TableName;

/** 小组件实体：供"空 Controller 子类 + 泛型基类 CRUD"夹具使用。 */
@TableName("widget")
public class Widget {
    private Long id;
    private String name;
    private Integer status;
}
