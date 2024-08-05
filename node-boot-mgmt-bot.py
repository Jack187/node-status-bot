import logging, argparse, time, datetime

import telegram
from telegram import Update, ParseMode
from telegram.ext import Updater, CallbackContext, CommandHandler, PicklePersistence, Defaults

import grid3.graphql
from grid3.types import Node

from managed_node import ManagedNode, NodeInfo
from nodepowerctrl import ShellyPlug

NETWORKS = ['main']
DEFAULT_PING_TIMEOUT = 10
DEFAULT_MAX_BOOT_TIME = 3
DEFAULT_MSG_LEVEL = logging.WARN

# arguments parsing
arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('token', help='Specify a bot token')
arg_parser.add_argument('-s', '--secret', help='A TF Chain secret for use with RMB', type=str)
arg_parser.add_argument('-v', '--verbose', help='Verbose output', action="store_true")
arg_parser.add_argument('-p', '--poll', help='Set polling frequency in seconds', type=int, default=60)
arg_parser.add_argument('-l', '--logs', help='Specify how many lines the log file must grow before a notification is sent to the admin', type=int, default=10)
arg_parser.add_argument('-t', '--test', help='Enable test feature', action="store_true")
arg_parser.add_argument('-d', '--dump', help='Dump bot data', action="store_true")
arg_parser.add_argument('-i', '--init', help='Init mode for seting up a bot user', action="store_true")
args = arg_parser.parse_args()

# telegram variables
pickler = PicklePersistence(filename='bot_data')
defaults = Defaults(parse_mode=ParseMode.HTML)
updater = Updater(token=args.token, persistence=pickler, use_context=True, defaults=defaults)
dispatcher = updater.dispatcher

# threefold
mainnet_gql = grid3.graphql.GraphQL('https://graphql.grid.tf/graphql')
testnet_gql = grid3.graphql.GraphQL('https://graphql.test.grid.tf/graphql')
devnet_gql = grid3.graphql.GraphQL('https://graphql.dev.grid.tf/graphql')

graphqls = {'main': mainnet_gql,
            'test': testnet_gql,
            'dev': devnet_gql}

msgLevel = DEFAULT_MSG_LEVEL

if args.verbose:
    log_level = logging.INFO

    #Force fetching the schemas when verbose so they don't dump on console
    mainnet_gql.fetch_schema()
else:
    log_level = logging.WARNING

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=log_level, 
    handlers=[logging.FileHandler('node-boot-mgmt-bot.log'), logging.StreamHandler()])

def send_message(context, chat_id, text):
    try:
        context.bot.send_message(chat_id=chat_id, text=text)
    except telegram.error.Unauthorized:
        # User blocked the bot or deleted their account
        pass
    except:
        logging.exception('Error sending message')

def format_list(items):
    if len(items) == 1:
        text = ' ' + str(items[0])
    elif len(items) == 2:
        text = 's ' + str(items[0]) + ' and ' + str(items[1])
    else:
        text = 's '
        for i in items[:-1]:
            text = text + str(i) + ', '
        text = text + 'and ' + str(items[-1])
    return text

def format_nodes(up, down, standby):
    up.sort()
    down.sort()
    standby.sort()
    text = ''

    if up:
        text += '<b><u>Up nodes:</u></b>\n'
        text += format_verticle_list(up)
    if down:
        if up:
            text += '\n'
        text += '<b><u>Down nodes:</u></b>\n'
        text += format_verticle_list(down)
    if standby:
        if up or down:
            text += '\n'
        text += '<b><u>Standby nodes:</u></b>\n'
        text += format_verticle_list(standby)

    return text

def format_verticle_list(items):
    text = ''
    for item in items:
        text += str(item) + '\n'
    return text

def initialize(context: CallbackContext):
    for key in ['chats', 'nodes', 'nodeInfos']:
        context.bot_data.setdefault(key, {})

    for net in NETWORKS:
        context.bot_data['nodes'].setdefault(net, {})
        context.bot_data['nodeInfos'].setdefault(net, {})

    subs = 0
    for chat, data in context.bot_data['chats'].items():
        for net in NETWORKS:
            if data['nodes'][net]:
                subs += 1
                break
    print('{} chats and {} subscribed users'.format(len(context.bot_data['chats']), subs))

def get_nodes(net, node_ids, nodeInfos):
    """
    Query a list of node ids in GraphQL, create Node objects for consistency and easy field access, then assign them a status and return them.
    """
    graphql = graphqls[net]
    nodes = graphql.nodes(['nodeID', 'twinID', 'updatedAt', 'power'], 
                          nodeID_in=node_ids)
    for node in nodes:
        nid = node['nodeID']

    nodes = [ManagedNode(Node(node), nodeInfos[node['nodeID']]) for node in nodes]
   
    for node in nodes:
        if node.power is None: 
            node.power = {'state': None, 'target': None}
        node.status = get_node_status(node)  

    return nodes

def get_node_status(node):
    """
    More or less the same methodology that Grid Proxy uses. Nodes are supposed to report every 40 minutes, so we consider them offline after one hour. Standby nodes should wake up once every 24 hours, so we consider them offline after that.
    """
    one_hour_ago = time.time() - 60 * 60
    one_day_ago = time.time() - 60 * 60 * 24

    # It's possible that some node might not have a power state
    if node.updatedAt > one_hour_ago and node.power['state'] != 'Down':
        return 'up'
    elif node.power['state'] == 'Down' and node.power['target'] == 'Up' and node_within_wake_timeframe(node):
        return 'waking'
    elif node.power['state'] == 'Down' and node.power['target'] == 'Up':
        return 'waking_blocked'
    elif node.power['state'] == 'Down' and node.updatedAt > one_day_ago:
        return 'standby'
    else:
        return 'down'

def node_within_wake_timeframe(node: ManagedNode):
    nodeInfo = node._nodeInfo
    node_max_boot_time_ago = time.time() - 60 * nodeInfo._maxBootTime
    last_wakeup_time = nodeInfo._lastWakeUpTime
    
    if (last_wakeup_time is None or last_wakeup_time > node_max_boot_time_ago):
        return True

    return False

def new_user():
    return {'net': 'main', 'nodes': {'main': [], 'test': [], 'dev': []}}

def start(update: Update, context: CallbackContext):
    if not args.init:
        # only allowed if in init (setup mode)
        return
    
    chat_id = update.effective_chat.id
    context.bot_data['chats'].setdefault(chat_id, new_user())
    msg = '''
Hey there, I'm the ThreeFold Node boot managment bot. Beep boop.

I can give you information about whether a node is up or down right now and also notify you if its state changes in the future. Here are the commands I support:

/status - check the current status of one node. This is based on Grid proxy and should match what's reported by the explorer which updates relatively slowly.
Example: /status 1

/subscribe (/sub) - subscribe to updates about one or more nodes. If you don't provide an input, the nodes you are currently subscribed to will be shown. 
Example: /sub 1 2 3

/unsubscribe (/unsub) - unsubscribe from updates about one or more nodes. If you don't give an input, you'll be unsubscribed from all updates.

/durationdefault - sets the default boot duration in minutes that is used for new added nodes.
Example: /durationdefault 9

/duration node duration - set the max duration in minutes the boot is allowed to take before a warning is send.
Example: duration 111 8

/durationall duration - 


This bot is experimental and probably has bugs. Only you are responsible for your node's uptime and your farming rewards.
    '''
    send_message(context, chat_id, text=msg)

def subscribe(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    
    if not chat_id in context.bot_data['chats']:
        return
    
    # user = context.bot_data['chats'].setdefault(chat_id, new_user())
    user = context.bot_data['chats'][chat_id]

    net = user['net']
    subbed_nodes = user['nodes'][net]

    node_ids = []
    if context.args:
        try:
            for arg in context.args:
                node_ids.append(int(arg))
        except ValueError:
            send_message(context, chat_id, text='There was a problem processing your input. This command accepts one or more node ids separated by a space.')
            return
    else:
        if subbed_nodes:
            send_message(context, chat_id, text='You are currently subscribed to node' + format_list(subbed_nodes))
            return
        else:
            send_message(context, chat_id, text='You are not subscribed to any nodes')
            return
    
    try:
        new_ids = [n for n in node_ids if n not in subbed_nodes]
        new_nodeinfos = {nodeId: NodeInfo(nodeId) for nodeId in new_ids }
        new_nodes = {node.nodeId: node for node in get_nodes(net, new_ids, new_nodeinfos)}
        if not new_nodes:
            send_message(context, chat_id, text='No valid node ids found.')
            return

        context.bot_data['nodes'][net].update(new_nodes)
        context.bot_data['nodeInfos'][net].update(new_nodeinfos)

        #Do this to preserve the order since gql will not
        new_subs = [n for n in node_ids if n in new_nodes]
    
    except:
        logging.exception("Failed to fetch node info")
        send_message(context, chat_id, text='Error fetching node data. Please wait a moment and try again.')
        return

    msg = 'You have been successfully subscribed to node' + format_list(new_subs)

    if subbed_nodes:
        msg += '\n\nYou are now subscribed to node' + format_list(subbed_nodes + new_subs)
    
    subbed_nodes.extend(new_subs)
    send_message(context, chat_id, text=msg)   


def unsubscribe(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    
    if not chat_id in context.bot_data['chats']:
        return
    
    # user = context.bot_data['chats'].setdefault(chat_id, new_user())
    user = context.bot_data['chats'][chat_id]

    if len(user['nodes']) == 0:
        send_message(context, chat_id, text="You weren't subscribed to any updates.")
    else:
        if context.args and context.args[0] == 'all':
            for net in NETWORKS:
                user['nodes'][net] = []
            send_message(context, chat_id, text='You have been unsubscribed from all updates')

        elif context.args:
            removed_nodes = []
            net = user['net']
            subbed_nodes = user['nodes'][net]
            for node in context.args:
                try:
                    subbed_nodes.remove(int(node))
                    removed_nodes.append(node)
                except ValueError:
                    pass
            if removed_nodes:
                send_message(context, chat_id, text='You have been unsubscribed from node' + format_list(removed_nodes))
            else:
                send_message(context, chat_id, text='No valid and subscribed node ids found.')

        else:
            send_message(context, chat_id, text='Please write "/unsubscribe all" if you wish to remove all subscribed nodes.')

def powerctrl(update: Update, context: CallbackContext):
    """
    Sets the 
    """
    chat_id = update.effective_chat.id
    
    if not chat_id in context.bot_data['chats']:
        return
    
    user = context.bot_data['chats'][chat_id]

    if len(user['nodes']) == 0:
        send_message(context, chat_id, text="No node subscribed.")
    else:
        if context.args:
            pwrCtrledNodes = []
            net = user['net']
            nodeInfos = context.bot_data['nodeInfos'][net]
            for pwrCtrlData in context.args:
                try:
                    pwrCtrlData = pwrCtrlData.split(":")
                    nodeId = pwrCtrlData[0]
                    nodeInfo = nodeInfos[int(nodeId)]
                    if len(pwrCtrlData) > 1:
                        address = pwrCtrlData[1] # parse ip or hostname
                        nodeInfo.update_power_ctrl(ShellyPlug(nodeId, address))
                        pwrCtrledNodes.append(nodeInfo)
                except ValueError:
                    pass
            
            pwrCtrledNodes = {ni._nodeId: ni for ni in pwrCtrledNodes }
            context.bot_data['nodeInfos'][net].update(pwrCtrledNodes)

            if pwrCtrledNodes:
                send_message(context, chat_id, text='You have actived power control for node' + format_list(list(pwrCtrledNodes.keys())))
            else:
                send_message(context, chat_id, text='No power control set.')        

def check_job(context: CallbackContext):
    """
    The main attraction. This function collects all the node ids that have an active subscription, checks their status, then sends alerts to users whose nodes have a status change.
    """
    for net in NETWORKS:
        # First gather all actively subscribed nodes and note who is subscribed
        try:
            subbed_nodes = {}

            for chat_id, data in context.bot_data['chats'].items():
                for node_id in data['nodes'][net]:
                    subbed_nodes.setdefault(node_id, []).append(chat_id)

            nodeInfos = context.bot_data['nodeInfos'][net]
            nodes = get_nodes(net, subbed_nodes, nodeInfos)
        except:
            logging.exception("Error fetching node data for check")
            continue

        for node in nodes:
            try:
                #print(node.status)
                previous = context.bot_data['nodes'][net][node.nodeId]

                if previous.power['target'] == 'Down' and node.power['target'] == 'Up':
                    nodeInfos[node.nodeId].update_last_wake_time()
                    if (msgLevel <= logging.INFO):
                        for chat_id in subbed_nodes[node.nodeId]:
                            send_message(context, chat_id, text='Node {} wake up initiated \N{hot beverage}'.format(node.nodeId))

                elif previous.status == 'up' and node.status == 'down':
                    # to be safe reset here as well (up should have done it already)
                    nodeInfos[node.nodeId].reset_last_wake_time()
                    if (msgLevel <= logging.WARN):
                        for chat_id in subbed_nodes[node.nodeId]:                        
                            send_message(context, chat_id, text='Node {} has gone offline \N{warning sign}'.format(node.nodeId))

                elif previous.status == 'waking' and node.status == 'waking_blocked':
                    if (msgLevel <= logging.WARN):
                        for chat_id in subbed_nodes[node.nodeId]:
                            msg = 'Node {} wake up takes longer than expected \N{warning sign}'.format(node.nodeId)
                            send_message(context, chat_id, text=msg)
                            
                            nodePwrCtrler = nodeInfos[node.nodeId]._nodePowerCtrl
                            if nodePwrCtrler:

                                if nodePwrCtrler.power_cyle():
                                    msg = 'Executed power cycle for node {} ({}) \N{electric plug}'.format(node.nodeId, nodePwrCtrler.address)
                                else:
                                    msg = 'Execute power cycle for node {} ({}) failed! \N{Heavy Exclamation Mark Symbol}'.format(node.nodeId, nodePwrCtrler.address)
                            else:
                                msg = 'No power controller set for node {}. Node will not be power cycled \N{Heavy Exclamation Mark Symbol}'.format(node.nodeId)

                            send_message(context, chat_id, text=msg)
                            # TODO reset for another try (maybe multiply with reset attempts??

                elif previous.status == 'up' and node.status == 'standby':
                    # to be safe reset here as well (up should have done it already)
                    nodeInfos[node.nodeId].reset_last_wake_time()
                    if (msgLevel <= logging.INFO):
                        for chat_id in subbed_nodes[node.nodeId]:
                            send_message(context, chat_id, text='Node {} has gone to sleep \N{Sleeping Symbol}'.format(node.nodeId))

                elif previous.status == 'standby' and node.status == 'down':
                    # to be safe reset here as well (up should have done it already)
                    nodeInfos[node.nodeId].reset_last_wake_time()
                    if (msgLevel <= logging.WARN):
                        for chat_id in subbed_nodes[node.nodeId]:
                            send_message(context, chat_id, text='Node {} did not wake up within 24 hours \N{warning sign}'.format(node.nodeId))

                elif previous.status != 'up' and node.status == 'up':
                    nodeInfos[node.nodeId].reset_last_wake_time()
                    if (msgLevel <= logging.INFO):
                        for chat_id in subbed_nodes[node.nodeId]:
                            send_message(context, chat_id, text='Node {} has come online \N{electric light bulb}'.format(node.nodeId))

            except:
                logging.exception("Error in alert block")

            finally:
                context.bot_data['nodes'][net][node.nodeId] = node


# Anyone commands
#dispatcher.add_handler(CommandHandler('chat_id', check_chat))
#dispatcher.add_handler(CommandHandler('network', network))
#dispatcher.add_handler(CommandHandler('net', network))
#dispatcher.add_handler(CommandHandler('ping', status_ping))
dispatcher.add_handler(CommandHandler('start', start))
#dispatcher.add_handler(CommandHandler('status', status_gql))
dispatcher.add_handler(CommandHandler('subscribe', subscribe))
dispatcher.add_handler(CommandHandler('sub', subscribe))
#dispatcher.add_handler(CommandHandler('timeout', timeout))
dispatcher.add_handler(CommandHandler('unsubscribe', unsubscribe))
dispatcher.add_handler(CommandHandler('unsub', unsubscribe))
dispatcher.add_handler(CommandHandler('powerctrl', powerctrl))

updater.job_queue.run_once(initialize, when=0)
updater.job_queue.run_repeating(check_job, interval=args.poll, first=0)
# updater.job_queue.run_repeating(log_job, interval=3600, first=0)

updater.start_polling()
updater.idle()