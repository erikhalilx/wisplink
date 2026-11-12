from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, model_validator

PRESETS = {
    "30m": 1800,
    "1h": 3600,
    "6h": 21600,
    "24h": 86400,
    **{f"{days}d": days * 86400 for days in (7, 14, 30, 90, 180, 365)},
}


class ExpiryChoice(BaseModel):
    preset: (
        Literal[
            "30m",
            "1h",
            "6h",
            "24h",
            "7d",
            "14d",
            "30d",
            "90d",
            "180d",
            "365d",
            "forever",
        ]
        | None
    ) = None
    at: AwareDatetime | None = None

    @model_validator(mode="after")
    def exclusive_choice(self):
        if (self.preset is None) == (self.at is None):
            raise ValueError("请选择时长或指定日期，二选一。")
        return self

    def resolve(self, now: int, created_at: int, max_days: int | None) -> int | None:
        if self.preset == "forever":
            if max_days is not None:
                raise ValueError("管理员设置了累计有效期上限，无法选择永久。")
            return None
        expires_at = int(self.at.timestamp()) if self.at else now + PRESETS[self.preset]
        if expires_at <= now:
            raise ValueError("到期时间必须晚于当前时间。")
        if max_days is not None and expires_at > created_at + max_days * 86400:
            raise ValueError("超出管理员设置的累计有效期上限。")
        return expires_at


def timestamp(value: int | None) -> str | None:
    return (
        datetime.fromtimestamp(value, timezone.utc).isoformat()
        if value is not None
        else None
    )
