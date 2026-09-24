package com.demo.service;

import com.demo.mapper.OrderMapper;

/**
 * 中间泛型层：M 在这一层已钉成 OrderMapper，T 继续透传给最底下的具体子类。
 * 用来验证两层泛型折叠（子类 T=Order 要一路透到 AbstractEntityService）。
 */
public abstract class MidOrderService<T> extends AbstractEntityService<OrderMapper, T> {

    /** self 调用跨泛型层：裸调基类方法，调用图要靠继承节点补建才接得上。 */
    public T midGet(Long id) {
        return genericGetById(id);
    }
}
