from pydantic import BaseModel, Field, model_validator


class Thresholds(BaseModel):
    cpu_warn: float = Field(80, ge=1, le=100)
    cpu_crit: float = Field(95, ge=1, le=100)
    mem_warn: float = Field(80, ge=1, le=100)
    mem_crit: float = Field(92, ge=1, le=100)
    disk_warn: float = Field(85, ge=1, le=100)
    disk_crit: float = Field(95, ge=1, le=100)

    @model_validator(mode="after")
    def warn_below_crit(self):
        for m in ("cpu", "mem", "disk"):
            if getattr(self, f"{m}_warn") >= getattr(self, f"{m}_crit"):
                raise ValueError(f"{m}: warning threshold must be lower than critical threshold")
        return self
