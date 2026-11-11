from dataclasses import dataclass, field
from typing import List


@dataclass
class DeviceState:
    connected: bool = False
    port_name: str = ""
    protocol_running: bool = False
    stimulus_on: bool = False
    recent_samples: List[float] = field(default_factory=list)
    recent_voltages_v: List[float] = field(default_factory=list)
    recent_elapsed_us: List[int] = field(default_factory=list)
