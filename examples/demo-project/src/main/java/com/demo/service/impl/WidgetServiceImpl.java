package com.demo.service.impl;

import com.demo.entity.Widget;
import com.demo.mapper.WidgetMapper;
import com.demo.service.WidgetService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class WidgetServiceImpl implements WidgetService {

    @Autowired
    private WidgetMapper widgetMapper;

    @Override
    public void save(Widget widget) {
        widgetMapper.insert(widget);
    }

    @Override
    public void update(Widget widget) {
        widgetMapper.updateById(widget);
    }

    @Override
    public void delete(Long[] ids) {
        for (Long id : ids) {
            widgetMapper.deleteById(id);
        }
    }

    @Override
    public List<Widget> page(int num, int size) {
        return widgetMapper.selectList(null);
    }
}
