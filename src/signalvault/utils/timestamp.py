"""时间戳格式化工具。"""


def format_timestamp(ts: str) -> str:
    """将 SRT 时间戳 '00:12:34,567' 转为 '00:12:34'。"""
    return ts.split(",")[0] if "," in ts else ts
