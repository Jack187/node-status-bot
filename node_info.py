import time
from nodepowerctrl import NodePowerController

class NodeInfo:
    _maxBootTime = 2
    _nodeId = 0
    _lastWakeUpTime = None
    _nodePowerCtrl = None

    def __init__(self, nodeId: int) -> None:
        self._nodeId = nodeId

    def update_last_wake_time(self):
        self._lastWakeUpTime = time.time()
    
    def reset_last_wake_time(self):
        self._lastWakeUpTime = None

    def update_power_ctrl(self, nodePowerCtrl: NodePowerController):
        self._nodePowerCtrl = nodePowerCtrl
        