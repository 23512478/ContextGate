package com.demo.controller;

import com.demo.annotation.AdminApi;
import com.demo.controller.base.BaseController;
import com.demo.entity.Widget;
import com.demo.service.WidgetService;

/**
 * 空类 Controller：类级组合注解 {@link AdminApi} 让它成为 Controller，
 * 4 个路由全部继承自 {@link BaseController}；
 * 泛型实参把 S 钉成 WidgetService、T 钉成 Widget，
 * 基类方法体里的 service.save(...) 才能接到 WidgetMapper。
 */
@AdminApi(path = "/widget")
public class WidgetController extends BaseController<WidgetService, Widget> {
}
