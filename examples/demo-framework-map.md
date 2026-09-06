# 框架调用链地图（阶段0 增强版）

- 项目: `demo-project`
- 生成时间: 2026-09-07 01:08:14
- 扫描类: 9 个 | Controller: 2 个 | Mapper: 3 个 | 实体: 3 个 | HTTP 路由: 4 条 | 调用图边: 6 个方法

---

## 一、HTTP 路由调用链

### `POST /api/v1/orders`
**OrderController#create**
   ├─ OrderServiceImpl#create  （组件/工具）

### `GET /api/v1/orders/my`
**OrderController#listMy**
   ├─ OrderServiceImpl#listMyOrders  （组件/工具）

### `GET /api/v1/wallet/me`
**WalletController#me**
   ├─ UserMapper#selectById  （MP 内置）

### `POST /api/v1/wallet/recharge`
**WalletController#recharge**
   ├─ UserMapper#addBalance  → @UPDATE 自定义SQL ✍️写
   │     `UPDATE users SET wallet_balance = COALESCE(wallet_balance, 0) + #{delta} WHERE id = #{userId}`

---

## 二、Mapper 自定义 SQL（注解方式）

- **MessageMapper#selectRecent** — @SELECT
  - SQL: `SELECT * FROM messages WHERE conversation_id = #{conversationId} ORDER BY create_time DESC`
  - 涉及表: `messages`
  - 触碰列: `messages.content (Message.content)`, `messages.conversation_id (Message.conversationId)`, `messages.create_time (Message.createTime)`, `messages.id (Message.id)`, `messages.role (Message.role)`
- **OrderMapper#selectMyOrders** — @SELECT
  - SQL: `SELECT o.*, u.nickname AS user_name FROM orders o LEFT JOIN users u ON o.user_id = u.id WHERE o.user_id = #{userId} ORDER BY o.create_time DESC`
  - 涉及表: `orders`, `users`
  - 触碰列: `orders.amount (Order.amount)`, `orders.create_time (Order.createTime)`, `orders.id (Order.id)`, `orders.status (Order.status)`, `orders.title (Order.title)`, `orders.user_id (Order.userId)`, `users.create_time (User.createTime)`, `users.id (User.id)`, `users.nickname (User.nickname)`
  - ↑ 上游路由: `GET /api/v1/orders/my`
- **UserMapper#selectByOpenid** — @SELECT
  - SQL: `SELECT * FROM users WHERE openid = #{openid}`
  - 涉及表: `users`
  - 触碰列: `users.create_time (User.createTime)`, `users.id (User.id)`, `users.nickname (User.nickname)`, `users.openid (User.openid)`, `users.wallet_balance (User.walletBalance)`
- **UserMapper#selectAll** — @SELECT
  - SQL: `SELECT id, nickname, wallet_balance, create_time FROM users ORDER BY create_time DESC`
  - 涉及表: `users`
  - 触碰列: `users.create_time (User.createTime)`, `users.id (User.id)`, `users.nickname (User.nickname)`, `users.wallet_balance (User.walletBalance)`
- **UserMapper#addBalance** — @UPDATE
  - SQL: `UPDATE users SET wallet_balance = COALESCE(wallet_balance, 0) + #{delta} WHERE id = #{userId}`
  - 涉及表: `users`
  - 触碰列: `users.id (User.id)`, `users.wallet_balance (User.walletBalance)`
  - ↑ 上游路由: `POST /api/v1/wallet/recharge`

---

## 三、事务边界影响面（@Transactional）

### 事务入口（声明处）

- `OrderServiceImpl#create`  (`src\main\java\com\demo\service\OrderServiceImpl.java`)

### 事务闭包内的方法（在同一事务里执行，出错会一起回滚）

```
OrderMapper#insert
UserMapper#selectById
```

### 事务内的数据库写操作（✍️ 出错回滚的关键路径）

- `OrderServiceImpl#create` → `OrderMapper#insert` ✍️

---

## 四、实体 ↔ 表 ↔ SQL 联动（改实体字段的波及面）

> 给实体加/删字段前，先看这一节：哪些 SQL 会受影响、哪些路由会变化。

### Message → 表 `messages`（5 个字段）

- 字段: `id`→`id`, `conversationId`→`conversation_id`, `role`→`role`, `content`→`content`, `createTime`→`create_time`
- 专属 Mapper: `MessageMapper`
- 被自定义 SQL 触碰: 1 处
  - `MessageMapper#selectRecent`（波及 0 条路由）

### Order → 表 `orders`（6 个字段）

- 字段: `id`→`id`, `userId`→`user_id`, `title`→`title`, `amount`→`amount`, `status`→`status`, `createTime`→`create_time`
- 专属 Mapper: `OrderMapper`
- 被自定义 SQL 触碰: 1 处
  - `OrderMapper#selectMyOrders`（波及 1 条路由）

### User → 表 `users`（5 个字段）

- 字段: `id`→`id`, `openid`→`openid`, `nickname`→`nickname`, `walletBalance`→`wallet_balance`, `createTime`→`create_time`
- 专属 Mapper: `UserMapper`
- 被自定义 SQL 触碰: 4 处
  - `OrderMapper#selectMyOrders`（波及 1 条路由）
  - `UserMapper#selectByOpenid`（波及 0 条路由）
  - `UserMapper#selectAll`（波及 0 条路由）
  - `UserMapper#addBalance`（波及 1 条路由）

---

## 五、逆向索引（这条 SQL / Mapper 方法，谁在用？）

> 改 SQL 前必查：上游有多少路由依赖它，动了会炸几个接口。

- **UserMapper#addBalance** ← 1 条路由 
  - 直接调用者: `WalletController#recharge`
  - `POST /api/v1/wallet/recharge`
- **OrderMapper#selectMyOrders** ← 1 条路由 
  - 直接调用者: `OrderServiceImpl#listMyOrders`
  - `GET /api/v1/orders/my`

---

## 六、隐藏入口（没有 HTTP 路由但会被框架触发）

（未发现）
