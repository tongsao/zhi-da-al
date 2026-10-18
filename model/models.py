import datetime

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, Text

from model.initDataBase import Base


class chunks(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer)
    chunk_index = Column(Integer)
    content = Column(String)
    char_count = Column(Integer)
    vector_id = Column(String(100))
    created_at = Column(DateTime, default=datetime.datetime.now)

class conversations(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), index=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now)

class documents(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    file_name = Column(String(255), index=True)
    file_type = Column(String(255), index=True)
    file_path = Column(String)
    chunk_size = Column(Integer)
    chunk_overlap = Column(Integer)
    chunk_count = Column(Integer)
    total_chars     = Column(Integer)
    status = Column(String(255), index=True)
    error_msg = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.now)
    updated_at = Column(DateTime, default=datetime.datetime.now)
class messageInfo(Base):
    __tablename__ = "message_info"
    id = Column(String(255), primary_key=True, comment="id")
    conversation_id = Column(String(255), nullable=True, comment="会话id")
    role = Column(String(20), nullable=False, comment="角色: user/assistant")
    content = Column(Text, nullable=False, comment="消息内容")
    user_id = Column(String(255), nullable=True, comment="用户id")
    created_at = Column(DateTime, default=datetime.datetime.now, comment="创建时间")


class zd_file_info(Base):
    __tablename__ = "zd_file_info"

    ID = Column(String(500), primary_key=True, comment="主键ID")
    FILE_NAME = Column(String(255), nullable=True, comment="文件名")
    FILE_PATH = Column(String(255), nullable=True, comment="文件路径")
    FILE_TYPE = Column(String(50), nullable=True, comment="文件类型")
    FILE_TITLE = Column(String(255), nullable=True, comment="文件标题")
    CHUNK_COUNT = Column(Integer, nullable=True, comment="分块数量")
    CREATE_DATE = Column(DateTime, default=datetime.datetime.now, comment="创建时间")


class evalRun(Base):
    __tablename__ = "eval_run"

    id = Column(Integer, primary_key=True, index=True)
    run_type = Column(String(20), index=True, comment="评测类型: full=含LLM问答 / retrieval=仅检索")
    top_k = Column(Integer, comment="检索块数")
    total = Column(Integer, comment="评测题数")
    passed = Column(Integer, nullable=True, comment="命中题数，仅 full 有值")
    hit_rate = Column(Float, nullable=True, comment="回答命中率，仅 full 有值")
    avg_latency_ms = Column(Integer, nullable=True, comment="平均问答耗时ms，仅 full 有值")
    recall_any = Column(Float, nullable=True, comment="recall@k，口径=块命中任一关键词")
    recall_all = Column(Float, nullable=True, comment="recall@k，口径=块含全部关键词")
    mrr_any = Column(Float, nullable=True, comment="MRR，口径=任一关键词")
    mrr_all = Column(Float, nullable=True, comment="MRR，口径=全部关键词")
    by_difficulty = Column(JSON, nullable=True, comment="按难度分组统计")
    by_category = Column(JSON, nullable=True, comment="按类别分组统计")
    detail = Column(JSON, nullable=True, comment="每题明细")
    created_at = Column(DateTime, default=datetime.datetime.now, comment="创建时间")


class qaFeedback(Base):
    __tablename__ = "qa_feedback"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String(255), nullable=True, comment="会话id")
    question = Column(Text, nullable=False, comment="用户问题")
    answer = Column(Text, nullable=False, comment="模型回答")
    action = Column(String(20), nullable=False, comment="用户操作: copy=复制 / usable=可用 / need_fix=需修改 / unusable=不可用")
    created_at = Column(DateTime, default=datetime.datetime.now, comment="创建时间")


class evalGenRun(Base):
    __tablename__ = "eval_gen_run"

    id = Column(Integer, primary_key=True, index=True)
    top_k = Column(Integer, comment="检索块数")
    total = Column(Integer, comment="评测题数")
    done = Column(Integer, default=0, comment="已完成题数，后台评测进度")
    status = Column(String(20), index=True, comment="状态: running=进行中 / success=完成 / failed=失败")
    error_msg = Column(Text, nullable=True, comment="失败原因")
    elapsed_seconds = Column(Integer, nullable=True, comment="总耗时秒")
    workers = Column(Integer, nullable=True, comment="并发数")
    correctness_avg = Column(Float, nullable=True, comment="事实正确性均分，满分2")
    completeness_avg = Column(Float, nullable=True, comment="要点完整性均分，满分2")
    faithfulness_avg = Column(Float, nullable=True, comment="忠于资料均分，满分2")
    correctness_full_rate = Column(Float, nullable=True, comment="correctness 满分率")
    completeness_full_rate = Column(Float, nullable=True, comment="completeness 满分率")
    faithfulness_full_rate = Column(Float, nullable=True, comment="faithfulness 满分率")
    detail = Column(JSON, nullable=True, comment="每题明细：问题/标准答案/生成答案/三维得分/扣分原因")
    created_at = Column(DateTime, default=datetime.datetime.now, comment="创建时间")