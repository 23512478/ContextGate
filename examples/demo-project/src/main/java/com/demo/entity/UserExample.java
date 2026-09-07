package com.demo.entity;

import java.util.ArrayList;
import java.util.List;

/** MyBatis Generator 风格的 Example 类（验证 Example 动态条件解析）。 */
public class UserExample {
    protected String orderByClause;
    protected boolean distinct;
    protected List<Criteria> criteria;

    public Criteria createCriteria() {
        Criteria c = new Criteria();
        criteria.add(c);
        return c;
    }

    public static class Criteria {
        public Criteria andNicknameEqualTo(String value) {
            return this;
        }

        public Criteria andCreateTimeGreaterThan(String value) {
            return this;
        }
    }
}
