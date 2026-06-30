from dataclasses import dataclass
from datetime import datetime


@dataclass
class Listing:
    id: str
    upload_date: datetime
    fields: dict

    @property
    def url(self) -> str:
        return self.fields.get("url") or self.fields.get("link", "")
