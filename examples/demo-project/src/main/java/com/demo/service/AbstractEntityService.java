package com.demo.service;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.springframework.beans.factory.annotation.Autowired;

/**
 * 自定义泛型基类（不是 MP 的 ServiceImpl，没有任何硬编码优待）：
 * 方法体里只看得到 M 和 T，具体是谁全靠子类在 extends 上给实参。
 * 静态分析沿继承链把 M/T 折成具体类型后，mapper 调用才能接到正确的 Mapper。
 */
public abstract class AbstractEntityService<M extends BaseMapper<T>, T> {

    @Autowired
    protected M mapper;

    /** 走 M 上的 MP 内置方法：折叠后应接到具体子类给的 Mapper#selectById。 */
    public T genericGetById(Long id) {
        return mapper.selectById(id);
    }
}
