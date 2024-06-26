from abc import ABC, abstractmethod
import json
import logging
import os
import ShellyPy

class NodePowerControl():
    powerControlledNodes = []

    def read_nodes(self):
        try:
            # print(os.getcwd())
            text = open('./.config/shellynodes.json', 'r').read() 
            shellyNodes = json.loads(text)
        
            for shellyNode in shellyNodes['nodes']:
                self.powerControlledNodes.append(ShellyPlug(**shellyNode))
        except:
            logging.exception("Error reading power control nodes json")
    
    def power_cycle(self, nodeID):
        node = next((n for n in self.powerControlledNodes if n.nodeID == nodeID), None)
        
        if node != None:
            node.power_cyle()

class PowerControlledNode(ABC):
    address = str()
    nodeID = int()
    
    @abstractmethod
    def power_cyle(self):
        pass

class ShellyPlug(PowerControlledNode):
    def __init__(self, nodeID, address):
        self.address = address        
        self.nodeID = nodeID
        
    def power_cyle(self):
        print(f"Power cyling the shelly plug {self.nodeID}.")
        shelly = ShellyPy.Shelly(self.address)
        shelly.relay(0, turn=False, timer=3) # turn off and after 3 seconds on
        
class AmtMachine(PowerControlledNode):
    def __init__(self, nodeID, address):
        self.address = address        
        self.nodeID = nodeID

    def power_cyle(self):
        print("Power cyling the amt managed machine.")