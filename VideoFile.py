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
    def bitrate(self) -> float | None:
        """Average bits per second, or None if size or duration is unknown."""
        if self.duration and self.duration > 0 and self.size >= 0:
            return self.size * 8 / self.duration
        return None

    @property
    def name(self):
        return os.path.basename(self.path)

    @property
    def name_prefix(self):
        return os.path.splitext(self.name)[0]

    @property
    def extension(self):
        return os.path.splitext(self.path)[1]
