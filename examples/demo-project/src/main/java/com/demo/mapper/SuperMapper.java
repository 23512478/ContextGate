package com.demo.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

/**
 * 自定义泛型 Mapper 基类：具体 Mapper 经它间接继承 BaseMapper 的 T。
 * 静态分析要能沿接口继承链把 T 折到具体子类给的实参
 * （OrderMapper extends SuperMapper of Order → 实体仍是 Order）。
 */
public interface SuperMapper<T> extends BaseMapper<T> {
}
