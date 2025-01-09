import os
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class VideoFile:
    id: int
    path: str
    size: int
    date_modified: datetime
    duration: float | None = None
    rating: int | None = None
    tags: set[str] = field(default_factory=set)

    @property
    def name(self):
        return os.path.basename(self.path)

    @property
    def name_prefix(self):
        return self.name.split('.')[0]

    @property
    def extension(self):
        return os.path.splitext(self.path)[1]
