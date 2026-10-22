# llm_gateway：模型网关（计数代理包装 + 用量限额）。
# 与业务逻辑隔离；入口统一走 providers.get_chat/get_rewrite/get_embedding。
# 模块级零 DB 操作，避免 import 即建连。
