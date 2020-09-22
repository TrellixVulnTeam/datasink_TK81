#
# initialize.py -- initialize the data sink
#
# This is open-source software licensed under a BSD license.
# Please see the file LICENSE.txt for details.
#
import sys

import yaml
import pika

default_topic = 'general'


def setup_queue(channel, queue_name, dct, config):
    priority = dct.get('priority', config['default_priority'])

    # durable=True to make sure queue is persistent
    durable = dct.get('persist', False)
    exclusive = dct.get('transient', False)

    args = {'x-priority': priority,
            'x-overflow': 'drop-head',
            'x-dead-letter-exchange': 'dlx',
            #'x-dead-letter-routing-key': queue_name,
            }
    if 'queue_length' in dct:
        args['x-max-length'] = dct['queue_length'],
    if 'ttl_sec' in dct:
        args['x-message-ttl'] = int(1000 * dct['ttl_sec']),

    # NOTE: if exclusive==True, the queue is deleted when the
    #       client exits
    channel.queue_declare(queue=queue_name, durable=durable,
                          exclusive=exclusive, arguments=args)

    channel.queue_bind(exchange=config['realm'],
                       queue=queue_name,
                       # NOTE: acts as a selector for messages to this queue
                       routing_key=dct.get('topic', default_topic))

def callback(ch, method, properties, body):
    print(" [x] %r" % (properties,))
    print(" [reason] : %s : %r" % (properties.headers['x-death'][0]['reason'], body))
    ch.basic_ack(delivery_tag=method.delivery_tag)

def handle_dlx(channel, config):
    print(" [*] Waiting for dead letters. To exit press Ctrl+C")

    channel.basic_consume(queue=config['backlog_queue'],
                          on_message_callback=callback)
    channel.start_consuming()

def read_config(keys_file):

    if not keys_file.endswith('.yml'):
        keys_file = keys_file + '.yml'

    # read datasink config file
    with open(keys_file, 'r') as in_f:
        buf = in_f.read()
    config = yaml.safe_load(buf)

    return config

def configure(keys_file):

    config = read_config(keys_file)
    durable = config.get('persist', False)

    auth = pika.PlainCredentials(username=config['realm_username'],
                                 password=config['realm_password'])
    params = pika.ConnectionParameters(host=config['realm_host'],
                                       #port=config['realm_port'],
                                       credentials=auth)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    # this is our main exchange for publishing datasink requests on this realm
    channel.exchange_declare(exchange=config['realm'], exchange_type='direct',
                             durable=durable)

    # declare our "dead letter exchange" (DLX). Unacknowledged messages,
    # message timeouts, etc. end up getting routed here.
    # NOTE: exchange type should be "fanout" for the DLX
    channel.exchange_declare(exchange='dlx', exchange_type='fanout',
                             durable=durable)

    # declare the queue that will be bound to the DLX
    channel.queue_declare(queue=config['backlog_queue'], durable=durable)
    channel.queue_bind(exchange='dlx',
                       #routing_key='task_queue', # x-dead-letter-routing-key
                       queue=config['backlog_queue'])

    # SET UP DATASINK QUEUES
    for name, dct in config['keys'].items():
        if dct.get('enabled', False):
            setup_queue(channel, name, dct, config)

    return connection, channel, config


def main(options, args):

    configfile = options.configfile
    if configfile is None:
        raise ValueError("Please specify a config file with -f")

    connection, channel, config = configure(configfile)

    handle_dlx(channel, config)


if __name__ == "__main__":

    # Parse command line options
    from argparse import ArgumentParser

    argprs = ArgumentParser()

    argprs.add_argument("--debug", dest="debug", default=False,
                        action="store_true",
                        help="Enter the pdb debugger on main()")
    argprs.add_argument("-f", "--config", dest="configfile",
                        help="Specify the configuration file for this realm")
    argprs.add_argument("--profile", dest="profile", action="store_true",
                        default=False,
                        help="Run the profiler on main()")
    #log.addlogopts(argprs)

    (options, args) = argprs.parse_known_args(sys.argv[1:])

    # Are we debugging this?
    if options.debug:
        import pdb

        pdb.run('main(options, args)')

    # Are we profiling this?
    elif options.profile:
        import profile

        print(("%s profile:" % sys.argv[0]))
        profile.run('main(options, args)')

    else:
        main(options, args)
