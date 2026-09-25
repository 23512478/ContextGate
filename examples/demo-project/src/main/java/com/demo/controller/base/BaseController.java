package com.demo.controller.base;

import com.demo.service.CrudService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;

import java.util.List;

/**
 * 泛型 CRUD 基类（复刻 cool-admin BaseController&lt;S, T&gt; 形态）：
 * 子类一个 mapping 方法都不用写，只要把 S/T 钉死成具体类型，
 * Spring MVC 就会把这里的 4 个路由注册到子类路径下；
 * 静态分析必须沿继承链收集这些 handler，并按子类视角绑定泛型实参。
 */
public abstract class BaseController<S extends CrudService<T>, T> {

    @Autowired
    protected S service;

    @PostMapping("/add")
    public String add(@RequestBody T entity) {
        service.save(entity);
        return "ok";
    }

    @PostMapping("/update")
    public String update(@RequestBody T entity) {
        service.update(entity);
        return "ok";
    }

    @PostMapping("/delete")
    public String delete(@RequestBody Long[] ids) {
        service.delete(ids);
        return "ok";
    }

    @GetMapping("/page")
    public List<T> page(@RequestParam(defaultValue = "1") int num,
                        @RequestParam(defaultValue = "10") int size) {
        return service.page(num, size);
    }
}
