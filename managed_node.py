from grid3.types import Node
from node_info import NodeInfo

class ManagedNode:
    _node = Node
    _nodeInfo = NodeInfo
    
    def __init__(self, node: Node, nodeInfo: NodeInfo) -> None:
        self._node = node
        self._nodeInfo = nodeInfo
    
    def __getattr__(self, name):
        try:
            return getattr(self._node, name)
        except KeyError:
            raise AttributeError("'Node' object has no attribute '{}'".format(name))
        