package com.demo.convert;

import com.demo.entity.Order;

import java.util.List;
import java.util.Map;

import org.mapstruct.Mapper;

/**
 * MapStruct 转换器：@Mapper 与 MyBatis @Mapper 撞名——
 * 回归：按 import 归属区分，本类不应被误判为 MyBatis Mapper（ruoyi-vue-pro 踩中的坑）。
 */
@Mapper(componentModel = "spring")
public interface OrderConvert {

    List<Map<String, Object>> toMapList(List<Order> orders);
}
