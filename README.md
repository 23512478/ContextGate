# ContextGate
ContextGate 是一个面向AI编程助手的智能上下文中间件。它通过静态分析预扫描项目，将稳定函数封装成轻量级签名（Signature），并在AI（如Codex）发起请求时动态路由——只将“必要调用链 + 封装摘要”注入上下文，而非全量源码。目标：降低70-90% Token消耗，同时将AI幻觉率压至最低。  技术标签： #AI-Context-Compression #Code-Indexing #LLM-Optimization #Static-Analysis
