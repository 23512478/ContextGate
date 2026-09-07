# 框架调用链地图（阶段0 增强版）

- 项目: `demo-project`
- 生成时间: 2026-09-08 03:22:57
- 扫描类: 20 个 | Controller: 5 个 | Mapper: 5 个 | 实体: 5 个 | HTTP 路由: 12 条 | 调用图边: 20 个方法

---

## 一、HTTP 路由调用链

### `GET /api/v1/comments/order/{orderId}`
**CommentController#listByOrder**
   ├─ CommentMapper#listByOrderId  （Mapper 方法，SQL 未找到）

### `GET /api/v1/comments/{id}`
**CommentController#detail**
   ├─ CommentMapper#selectDetail  （Mapper 方法，SQL 未找到）

### `PATCH /api/v1/comments/{id}`
**CommentController#update**
   ├─ CommentMapper#updateContent  （Mapper 方法，SQL 未找到）

### `POST /api/v1/orders`
**OrderController#create**
   ├─ OrderServiceImpl#create  （组件/工具）

### `GET /api/v1/orders/my`
**OrderController#listMy**
   ├─ OrderServiceImpl#listMyOrders  （组件/工具）

### `GET /api/v1/orders/search`
**OrderController#search**
   ├─ OrderServiceImpl#searchByTitle  （组件/工具）

### `GET /api/v1/products`
**ProductController#list**
   └─ ProductServiceImpl#list
      ├─ ProductMapper#selectAll  → @SELECT 自定义SQL
      │     `SELECT * FROM product ORDER BY create_time DESC`

### `POST /api/v1/products/purchase`
**ProductController#purchase**
   └─ ProductServiceImpl#purchase  [@Transactional]
      ├─ ProductMapper#deductStock  → @UPDATE 自定义SQL ✍️写
      │     `UPDATE product SET stock = stock - #{count} WHERE id = #{id}`

### `GET /api/v1/stats/orders/sum`
**StatsController#orderSum**
   └─ StatsService#orderAmountSum
      ├─ JdbcTemplate#queryForMap  （组件/工具）

### `GET /api/v1/stats/wallets/top`
**StatsController#topWallets**
   └─ StatsService#topWallets
      ├─ JdbcTemplate#queryForList  （组件/工具）

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
  - 触碰列: `orders.amount (Order.amount)`, `orders.create_time (Order.createTime)`, `orders.id (Order.id)`, `orders.status (Order.status)`, `orders.title (Order.title)`, `orders.user_id (Order.userId)`, `users.id (User.id)`, `users.nickname (User.nickname)`
  - ↑ 上游路由: `GET /api/v1/orders/my`
- **ProductMapper#selectById** — @SELECT
  - SQL: `SELECT * FROM product WHERE id = #{id}`
  - 涉及表: `product`
  - 触碰列: `product.create_time (Product.createTime)`, `product.id (Product.id)`, `product.name (Product.name)`, `product.price (Product.price)`, `product.stock (Product.stock)`
- **ProductMapper#selectAll** — @SELECT
  - SQL: `SELECT * FROM product ORDER BY create_time DESC`
  - 涉及表: `product`
  - 触碰列: `product.create_time (Product.createTime)`, `product.id (Product.id)`, `product.name (Product.name)`, `product.price (Product.price)`, `product.stock (Product.stock)`
  - ↑ 上游路由: `GET /api/v1/products`
- **ProductMapper#deductStock** — @UPDATE
  - SQL: `UPDATE product SET stock = stock - #{count} WHERE id = #{id}`
  - 涉及表: `product`
  - 触碰列: `product.id (Product.id)`, `product.stock (Product.stock)`
  - ↑ 上游路由: `POST /api/v1/products/purchase`
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
- `ProductServiceImpl#purchase`  (`src\main\java\com\demo\service\impl\ProductServiceImpl.java`)

### 事务闭包内的方法（在同一事务里执行，出错会一起回滚）

```
OrderMapper#insert
ProductMapper#deductStock
UserMapper#selectById
```

### 事务内的数据库写操作（✍️ 出错回滚的关键路径）

- `OrderServiceImpl#create` → `OrderMapper#insert` ✍️
- `ProductServiceImpl#purchase` → `ProductMapper#deductStock` ✍️

---

## 四、实体 ↔ 表 ↔ SQL 联动（改实体字段的波及面）

> 给实体加/删字段前，先看这一节：哪些 SQL 会受影响、哪些路由会变化。

### Comment → 表 `comments`（6 个字段）

- 字段: `id`→`id`, `orderId`→`order_id`, `userId`→`user_id`, `content`→`content`, `rating`→`rating`, `createTime`→`create_time`
- 专属 Mapper: `CommentMapper`
- 被自定义 SQL 触碰: 无（全部走 MP 内置 CRUD）

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

### Product → 表 `product`（5 个字段）

- 字段: `id`→`id`, `name`→`name`, `price`→`price`, `stock`→`stock`, `createTime`→`create_time`
- 被自定义 SQL 触碰: 3 处
  - `ProductMapper#selectById`（波及 0 条路由）
  - `ProductMapper#selectAll`（波及 1 条路由）
  - `ProductMapper#deductStock`（波及 1 条路由）

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
- **ProductMapper#selectAll** ← 1 条路由 
  - 直接调用者: `ProductServiceImpl#list`
  - `GET /api/v1/products`
- **ProductMapper#deductStock** ← 1 条路由 
  - 直接调用者: `ProductServiceImpl#purchase`
  - `POST /api/v1/products/purchase`
- **OrderMapper#selectMyOrders** ← 1 条路由 
  - 直接调用者: `OrderServiceImpl#listMyOrders`
  - `GET /api/v1/orders/my`
- **CommentMapper#updateContent** ← 1 条路由 
  - 直接调用者: `CommentController#update`
  - `PATCH /api/v1/comments/{id}`
- **CommentMapper#selectDetail** ← 1 条路由 
  - 直接调用者: `CommentController#detail`
  - `GET /api/v1/comments/{id}`
- **CommentMapper#listByOrderId** ← 1 条路由 
  - 直接调用者: `CommentController#listByOrder`
  - `GET /api/v1/comments/order/{orderId}`

---

## 六、隐藏入口（没有 HTTP 路由但会被框架触发）

- `PostConstruct` → DemoDataInitializer#initDemoData  (`src\main\java\com\demo\config\DemoDataInitializer.java`)

---

## 七、内嵌 SQL（不走 Mapper 接口：JdbcTemplate 裸 SQL / MP Wrapper 动态链）

> 这类 SQL 散落在 Service/Controller/Config 里，传统 Mapper 索引完全看不到。

- **DemoDataInitializer#initDemoData** — @INSERT（JdbcTemplate）  (`src\main\java\com\demo\config\DemoDataInitializer.java`)
  - `INSERT INTO users (openid, nickname, wallet_balance) VALUES ('demo-openid', 'demo-user', 0)`
  - 涉及表: `users`
- **OrderServiceImpl#searchByTitle** — @SELECT（MP Wrapper）  (`src\main\java\com\demo\service\OrderServiceImpl.java`)
  - `SELECT * FROM orders WHERE title = ? AND status = ? ORDER BY create_time`
  - 涉及表: `orders`
  - 上游路由: `GET /api/v1/orders/search`
- **StatsService#topWallets** — @SELECT（JdbcTemplate）  (`src\main\java\com\demo\service\StatsService.java`)
  - `SELECT id, nickname, wallet_balance FROM users ORDER BY wallet_balance DESC LIMIT 10`
  - 涉及表: `users`
  - 上游路由: `GET /api/v1/stats/wallets/top`
- **StatsService#orderAmountSum** — @SELECT（JdbcTemplate）  (`src\main\java\com\demo\service\StatsService.java`)
  - `SELECT COALESCE(SUM(amount), 0) AS total FROM orders`
  - 涉及表: `orders`
  - 上游路由: `GET /api/v1/stats/orders/sum`
