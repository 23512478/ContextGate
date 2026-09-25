package com.demo.service;

import com.demo.entity.Widget;

/** 小组件服务：自身不声明方法，save/update/delete/page 全在 CrudService 契约里。 */
public interface WidgetService extends CrudService<Widget> {
}
