import time

class NodeInfo:
    _maxBootTime = 7
    _nodeId = 0
    _lastWakeUpTime = None

    def __init__(self, nodeId: int) -> None:
        self._nodeId = nodeId

    def update_last_wake_time(self):
        self._lastWakeUpTime = time.time()
    
    def reset_last_wake_time(self):
        self._lastWakeUpTime = None
        