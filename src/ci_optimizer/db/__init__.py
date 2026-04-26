"""ci_optimizer.db — 数据访问层包。

对外暴露三个子模块：
- models   : SQLAlchemy ORM 表定义（Repository / AnalysisReport / Finding / FailureDiagnosis）
- database : 异步引擎、session 工厂以及启动时的 schema 初始化与迁移
- crud     : 所有数据库读写操作的函数集合，上层业务代码统一通过此层访问数据库
"""
