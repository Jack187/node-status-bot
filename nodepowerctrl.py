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

class NodePowerController(ABC):
    address = str()
    nodeID = int()
    
    @abstractmethod
    def power_cyle(self):
        pass

class ShellyPlug(NodePowerController):
    def __init__(self, nodeID, address):
        self.address = address        
        self.nodeID = nodeID
        
    def power_cyle(self):
        print(f"Power cyling the shelly plug {self.nodeID}.")
        try:
            shelly = ShellyPy.Shelly(self.address)
            result = shelly.relay(0, turn=False, timer=10) # turn off and after 10 seconds on
            if 'ison' in result.keys(): # shelly gen1
                return not result['ison']
            elif 'was_on' in result.keys(): #shelly plus plug s (gen2)
                return result['was_on']
            else:
                logging.warn("shelly.relay returned unknown result. Power cycle maybe not successfull.")
                return False
        except:
            logging.exception('Error switching shelly')
            return False
        
class AmtMachine(NodePowerController):
    def __init__(self, nodeID, address):
        self.address = address        
        self.nodeID = nodeID

    def power_cyle(self):
        print("Power cyling the amt managed machine.")