import time
from nodepowerctrl import NodePowerController

class NodeInfo:
    _maxBootTime = 10
    _nodeId = 0
    _lastWakeUpTime = None
    _nodePowerCtrl = None

    def __init__(self, nodeId: int) -> None:
        self._nodeId = nodeId

    def __str__(self):
        if (self.is_under_power_ctrl()):
            return f"{self._nodeId}:{self._nodePowerCtrl.address}:{self._maxBootTime}"
        else:
            return f"{self._nodeId}:no_power_control"
    
    def update_last_wake_time(self):
        self._lastWakeUpTime = time.time()
    
    def reset_last_wake_time(self):
        self._lastWakeUpTime = None

    def update_power_ctrl(self, nodePowerCtrl: NodePowerController):
        self._nodePowerCtrl = nodePowerCtrl
    
    def update_max_boot_time(self, maxBootTime: int ):
        self._maxBootTime = maxBootTime
    
    def is_under_power_ctrl(self):
        return self._nodePowerCtrl != None
    