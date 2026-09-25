package com.demo.service;

import java.util.List;

/**
 * 泛型 CRUD 服务契约（复刻 cool-admin IService&lt;T&gt; 的最小形态）：
 * 基类 Controller 的 S 上界就是它，T 沿子类泛型实参钉死成具体实体。
 */
public interface CrudService<T> {

    void save(T entity);

    void update(T entity);

    void delete(Long[] ids);

    List<T> page(int num, int size);
}
