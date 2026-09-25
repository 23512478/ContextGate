package com.demo.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.demo.entity.Widget;
import org.apache.ibatis.annotations.Mapper;

/** 纯 MP BaseMapper：CRUD 全是内置方法，由 WidgetServiceImpl 调用。 */
@Mapper
public interface WidgetMapper extends BaseMapper<Widget> {
}
