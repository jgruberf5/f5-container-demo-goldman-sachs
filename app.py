#!/usr/bin/env python3

import json
import shlex
import subprocess
import yaml
import os
import signal
import tempfile
import psutil
import socket
import re
import requests
import base64
import dns.resolver

from werkzeug.utils import secure_filename
from urllib.parse import urlparse
from urllib.parse import parse_qs
from urllib.error import URLError

from flask import Flask, request, render_template, Response, send_from_directory
from flask_compress import Compress
from flask_socketio import SocketIO, emit

from threading import Thread, Event

from psycopg2 import connect
from sqlalchemy import create_engine
from pymongo import MongoClient
from azure.cosmos import CosmosClient as cosmos_client
from azure.cosmos import exceptions as cosmos_exceptions

CONFIG_FILE = os.getenv('CONFIG_FILE', './config.yaml')
CONFIG_MAP_DIR = '/etc/container-demo-runner'
NAMESPACE_FILE = '/var/run/secrets/kubernetes.io/serviceaccount/namespace'
PUPPETEER_HOME = os.getenv('PYPPETEER_HOME', '/tmp/webscreenshots')

UPLOAD_FOLDER = "%s/uploads" % (tempfile.gettempdir())

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, mode=0o777)

config = {}

with open(CONFIG_FILE, 'r') as config_yaml:
    config = yaml.safe_load(config_yaml)

if os.path.exists(CONFIG_MAP_DIR):
    for ck in config.keys():
        if os.path.exists("%s/%s" % (CONFIG_MAP_DIR, ck)):
            with open("%s/%s" % (CONFIG_MAP_DIR, ck), 'r') as cmv:
                cv = cmv.read()
                if isinstance(config[ck], list):
                    try:
                        cv = json.loads(cv)
                        print(
                            'loading config setting: %s from ConfigMap value: %s' % (ck, cv))
                        config[ck] = cv
                    except json.JSONDecodeError as jde:
                        print('error reading %s from ConfigMap: ' % (ck, jde))
                else:
                    print(
                        'loading config setting: %s from ConfigMap value: %s' % (ck, cv))
                    config[ck] = cv

if 'host_entries' in config:
    with open('/etc/hosts', 'a+') as eh:
        eh.write('\n#### entries added by container-demo-runner ####\n')
        eh.write(config['host_entries'])
        eh.write('\n#### end entries added by container-demo-runner ####\n')

app = Flask(__name__)
Compress(app)
websocket = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

pids_by_sid = {}
runners = {}


def root_dir():  # pragma: no cover
    return os.path.abspath(os.path.dirname(__file__))


def get_file(filename):  # pragma: no cover
    try:
        src = os.path.join(root_dir(), filename)
        return open(src, mode='rb').read()
    except IOError as exc:
        return str(exc)


def get_hostname():
    hostname = socket.gethostname()
    print('found hostname: %s' % hostname)
    if os.path.exists(NAMESPACE_FILE):
        print('running in K8s, adding namespace to hostname')
        with open(NAMESPACE_FILE, 'r') as nsf:
            hostname = "%s/%s" % (
                re.sub(r"[\n\t\s]*", "", nsf.read()), hostname)
    return hostname


def get_nameserver():
    nameserver = dns.resolver.Resolver().nameservers[0]
    print('found nameserver: %s' % nameserver)
    return nameserver


def dig_fqdn(fqdn, record_type='A'):
    try:
        result = dns.resolver.query(fqdn, record_type)
        return str(result[0])
    except dns.resolver.NoAnswer:
        return None
    except Exception:
        return None


def stream_emitter(id, event, stream_type, stream):
    print("started background thread to stream %s" % stream_type)
    while not event.is_set():
        line = stream.readline()
        if not line or event.is_set():
            break
        response = {
            'id': id,
            'stream': stream_type,
            'data': line
        }
        websocket.emit('commandResponse', response, namespace='/')
    event.set()


def destroy_pid(pid):
    print('destroying process id: %d' % pid)
    if pid in runners.keys():
        process_runner = runners[pid]
        if process_runner['stdout_thread'].is_alive():
            process_runner['stdout_kill_event'].set()
        if process_runner['stderr_thread'].is_alive():
            process_runner['stderr_kill_event'].set()
        del process_runner['stdout_thread']
        del process_runner['stdout_kill_event']
        del process_runner['stderr_thread']
        del process_runner['stderr_kill_event']
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
        del runners[pid]
    else:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()


def destroy_all_processes_for_sid(sid):
    if sid in pids_by_sid.keys():
        for pid in pids_by_sid[sid]:
            if psutil.pid_exists(pid):
                destroy_pid(pid)
        del pids_by_sid[sid]


def command_allowed(cmd):
    if isinstance(cmd, list):
        cmd = shlex.join(cmd)
    allowed = False
    for regex in config['allowed_commands']:
        if re.match(r"%s" % regex, cmd):
            allowed = True
            break
    return allowed


def run_cmd(sid, cmd, id, env=None):
    destroy_all_processes_for_sid(sid)
    if isinstance(cmd, list):
        cmd = shlex.join(cmd)
    print('running cmd: %s with id: %s' % (cmd, id))
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, universal_newlines=True, env=env)
    pids_by_sid[sid] = [process.pid]
    stdout_kill_event = Event()
    stderr_kill_event = Event()
    process_runner = {
        'stdout_kill_event': stdout_kill_event,
        'stdout_thread': websocket.start_background_task(
            stream_emitter, id, stdout_kill_event, 'stdout', process.stdout),
        'stderr_kill_event': Event(),
        'stderr_thread': websocket.start_background_task(
            stream_emitter, id, stderr_kill_event, 'stderr', process.stderr)
    }
    runners[process.pid] = process_runner
    process.wait()
    return process.returncode


def get_latency_from_ping_pong_output(output):
    match = re.search(r'avg-latency=(.*)\(std-dev=', output)
    if match:
        return match.group(1).strip()
    else:
        return ''


def get_bandwidth_from_throughput_output(output):
    match = re.search(r'MBps \((.*)Mbps', output)
    if match:
        return match.group(1).strip()
    else:
        return ''


def performance_test(sid, id, sourcelabel, targetlabel, target, port, runcount, latency, bandwidth):
    destroy_all_processes_for_sid(sid)
    header = "source_host, target_host"
    if latency:
        header = "%s, avg_latency_usec" % header
    if bandwidth:
        header = "%s, 32k_throughput_mbits, 64k_throughput_mbits, 128k_throughput_mbits, 1M_throughput_mbits" % header
    header = "%s\n" % header
    header_stdout_response = {
        'id': id,
        'stream': 'stdout',
        'data': header
    }
    websocket.emit('commandResponse', header_stdout_response)
    try:
        for i in range(runcount):
            print('running performance test (%d/%d)' % ((i + 1), runcount))
            labels_stdout_response = {
                'id': id,
                'stream': 'stdout',
                'data': "%s, %s" % (sourcelabel, targetlabel)
            }
            websocket.emit('commandResponse', labels_stdout_response)
            if latency:
                cmd = "sockperf ping-pong --tcp -i %s -p %d" % (target, port)
                print('    test : %s' % cmd)
                output = ''
                while len(output) < 1:
                    process = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, universal_newlines=True
                    )
                    pids_by_sid[sid] = [process.pid]
                    full_out = process.communicate()[0]
                    output = get_latency_from_ping_pong_output(full_out)
                    if process.returncode > 0 or len(output) == 0:
                        full_out = "%s\n%s\n\n" % (cmd, full_out)
                        error_response = {
                            'id': id,
                            'stream': 'stderr',
                            'data': full_out
                        }
                        websocket.emit('commandResponse', error_response)
                    print('    output: %d: %s' % (process.returncode, output))
                latency_stdout_response = {
                    'id': id,
                    'stream': 'stdout',
                    'data': ", %s" % output
                }
                websocket.emit('commandResponse', latency_stdout_response)
            if bandwidth:
                for msg_size in ['32768', '65536', '131072', '1048575']:
                    cmd = "sockperf throughput --tcp -i %s -p %s -m %s" % (
                        target, port, msg_size)
                    print('    test : %s' % cmd)
                    output = ''
                    while len(output) < 1:
                        process = subprocess.Popen(
                            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, universal_newlines=True
                        )
                        pids_by_sid[sid] = [process.pid]
                        full_out = process.communicate()[0]
                        output = get_bandwidth_from_throughput_output(full_out)
                        if process.returncode > 0 or len(output) == 0:
                            full_out = "%s\n%s\n\n" % (cmd, full_out)
                            error_response = {
                                'id': id,
                                'stream': 'stderr',
                                'data': full_out
                            }
                            websocket.emit('commandResponse', error_response)
                        print('    output: %d: %s' %
                              (process.returncode, output))
                    bandwidth_stdout_response = {
                        'id': id,
                        'stream': 'stdout',
                        'data': ", %s" % output
                    }
                    websocket.emit('commandResponse',
                                   bandwidth_stdout_response)
            eor_stdout_response = {
                'id': id,
                'stream': 'stdout',
                'data': "\n"
            }
            websocket.emit('commandResponse', eor_stdout_response)
        return 0
    except Exception as e:
        error_response = {
            'id': id,
            'stream': 'stderr',
            'data': "error running test on target: %s - %s - %s.. \n\n" % (target, e.__class__.__name__, e)
        }
        print("commandResponse to %s: %s" %
              (error_response['stream'], error_response['data']))
        websocket.emit('commandResponse', error_response)
        return -1


def db_connect_postgress(
        host='localhost', user='admin', password='admin', dbname='demo',
        use_tls=False, tls_client_cert=None,
        tls_client_key=None, tls_ca_cert='./postgres.ca',
        tls_verify=False):
    args = {
        "host": host,
        "user": user,
        "password": password,
        "dbname": dbname
    }
    if use_tls:
        args["sslcert"] = tls_client_cert
        args["sslkey"] = tls_client_key
        args["sslrootcert"] = tls_ca_cert
        if tls_verify:
            args["sslmode"] = "verify-full"
        else:
            args["sslmode"] = "allow"
    try:
        db = create_engine('postgresql+psycopg2://', connect_args=args)
        connection = db.connect()
        cursor = connection.cursor()
        cursor.execute("SELECT version()")
        version = cursor.fetchone()
        return {
            "host": host,
            "version": version,
            "error": False,
            "error_message": None
        }
    except Exception as ex:
        return {
            "host": host,
            "version": None,
            "error": True,
            "error_message": str(ex)
        }


def db_connect_mongodb(
        host='localhost', user='admin', password='admin', dbname='demo',
        use_tls=False, tls_client_cert=None,
        tls_client_key=None, tls_ca_cert=None,
        tls_verify=False):
    tls_client_combined = './mongo.combined'
    if use_tls:
        # combine client cert and key into one combined file
        if os.path.exists(tls_client_cert) and os.path.exists(tls_client_key):
            with open(tls_client_combined, 'w') as combined_cert_key:
                combined_content = ''
                with open(tls_client_cert, 'r') as cert:
                    combined_content = cert.read()
                with open(tls_client_key, 'r') as key:
                    combined_content = "%s\n\n%s" % (
                        combined_content, key.read())
                combined_cert_key.write(combined_content)
    try:
        client = MongoClient(host, username=user, password=password,
                             tls=use_tls, tlsCertificateKeyFile=tls_client_combined,
                             tlsCAFile=tls_ca_cert, tlsInsecure=not tls_verify)
        version = client.server_info()["version"]
        return {
            "host": host,
            "version": version,
            "error": False,
            "error_message": None
        }
    except Exception as ex:
        return {
            "host": host,
            "version": None,
            "error": True,
            "error_message": str(ex)
        }


def db_connect_cosmos(endpoint=None, clientkey=None, database='test'):
    with cosmos_client(endpoint, credential=clientkey) as client:
        response = {
            "url": endpoint,
            "error": None,
            "message": None
        }
        try:
            database = client.create_database(database)
            response["message"] = f"Successfully created to DB id: {database.id}"
        except cosmos_exceptions.CosmosResourceExistsError:
            database = client.get_database_client(database)
            response["message"] = f"Successfully connected to DB id: {database.id}"
        except cosmos_exceptions.CosmosHttpResponseError as chre:
            response["error"] = 400
            response["message"] = str(chre)
        return response


@app.route('/')
def run_iscapp():
    return render_template(
        'demoapp_index.html', location=os.getenv('DEMO_LOCATION', ''))


@app.route('/diag')
def runner_ui():
    host = request.host
    if str.find(host, ':') > 0:
        host = str.split(host, ':')[0]
    banner_text = os.getenv('BANNER', '')
    banner_background_color = "#%s" % os.getenv('BANNER_COLOR', '000000')
    banner_text_color = '#%s' % os.getenv('BANNER_TEXT_COLOR', 'ffffff')
    return render_template(
        'diag_index.html',
        hostname='connecting...',
        banner_text=(banner_text),
        banner_background_color=banner_background_color,
        banner_text_color=banner_text_color)


@app.route('/dump')
def dump_ui():
    banner_text = os.getenv('BANNER', '')
    banner_background_color = "#%s" % os.getenv('BANNER_COLOR', '000000')
    banner_text_color = '#%s' % os.getenv('BANNER_TEXT_COLOR', 'ffffff')
    request_header_out_string = ""
    request_env_out_string = ""
    for (header, value) in request.headers:
        request_header_out_string = "%s%s: %s\n" % (
            request_header_out_string, header, value)
    for e in request.environ:
        request_env_out_string = "%s%s: %s\n" % (
            request_env_out_string,
            e,
            request.environ[e])
    return render_template(
        'dump_index.html',
        hostname=get_hostname(),
        banner_text=(banner_text),
        banner_background_color=banner_background_color,
        banner_text_color=banner_text_color,
        requestmethod=request.method,
        requesturl=request.url,
        requestheaders=request_header_out_string,
        requestenv=request_env_out_string)


@app.route('/webscreenshots/<path:name>')
def send_screenshot(name):
    return send_from_directory(PUPPETEER_HOME, name, mimetype='image/jepg')


@app.route('/upload', methods=['POST', 'GET'])
def upload():
    if request.method == 'POST':
        if 'file' in request.files:
            file = request.files['file']
            if file.filename:
                fn = secure_filename(file.filename)
                file.save(os.path.join(UPLOAD_FOLDER, fn))
    file_listing = "<ul>"
    for f in os.listdir(UPLOAD_FOLDER):
        file_listing = "%s<li><a href='/upload/%s'>%s</a>" % (
            file_listing, f, f)
    file_listing = "%s</ul>" % file_listing
    return """
    <!doctype html>
    <title>Upload new File</title>
    <h1>Upload new File</h1>
    <form method=post enctype=multipart/form-data>
      <input type=file name=file>
      <input type=submit value=Upload>
    </form>
    <hr/>
    <div>
    <pre>
    %s
    </pre>
    </div
    """ % (file_listing)


@app.route('/upload/<path:path>')
def get_uploaded_file(path):  # pragma: no cover
    mimetypes = {
        ".css": "text/css",
        ".html": "text/html",
        ".htm": "text/html",
        ".js": "application/javascript",
        ".jpeg": "image/jpeg",
        ".ico": "image/x-icon"
    }
    complete_path = os.path.join(UPLOAD_FOLDER, path)
    ext = os.path.splitext(path)[1]
    mimetype = mimetypes.get(ext, "application/binary")
    content = get_file(complete_path)
    return Response(content, mimetype=mimetype)


@app.route('/resolv', methods=['GET'])
def proxy_resolv():
    rargs = request.args
    if rargs.get("fqdn"):
        try:
            dig_answer = dig_fqdn(rargs.get("fqdn"))
            if dig_answer:
                resp = {
                    "fqdn": rargs.get("fqdn"),
                    "error": None,
                    "message": dig_answer
                }
                return Response(
                    json.dumps(resp),
                    status=200,
                    mimetype='application/json'
                )
            else:
                return Response(
                    json.dumps({
                        "fqdn": rargs.get("fqdn"),
                        "error": 404,
                        "message": "NotFound"
                    }),
                    status=404, mimetype='application/json')
        except Exception as rex:
            return Response(
                json.dumps({
                    "fqdn": rargs.get("fqdn"),
                    "error": 500,
                    "message": rex
                }),
                status=500, mimetype='application/json')
    else:
        return Response(
            json.dumps({
                "fqdn": None,
                "error": 404,
                "message": "NotFound"
            }),
            status=404, mimetype='application/json')


@app.route('/webproxy')
def webproxy():
    rargs = request.args
    if rargs.get("url"):
        method = rargs.get("method")
        if not method:
            method = 'GET'
        try:
            resp = requests.request(
                method=method, url=rargs["url"], verify=False)
            return Response(
                json.dumps({
                    "url": rargs.get("url"),
                    "error": resp.status_code,
                    "message": resp.text
                }),
                status=resp.status_code, mimetype='application/json')
        except Exception as wex:
            return Response(
                json.dumps({
                    "url": rargs.get("url"),
                    "error": 500,
                    "message": wex
                }),
                status=500, mimetype='application/json')
    else:
        return Response(
            json.dumps({
                "url": None,
                "error": 404,
                "message": "NotFound"
            }),
            status=404, mimetype='application/json')


@app.route('/dbconnect')
def dbconnect():
    rargs = request.args
    if rargs.get("url"):
        try:
            db_url = urlparse(rargs.get("url"))
            if db_url.scheme not in ['mongodb', 'postgres', 'cosmos']:
                return Response(
                    json.dumps({
                        "url": rargs.get("url"),
                        "error": 400,
                        "message": f"invalid DB URL scheme: {db_url.scheme}"
                    }),
                    status=400, mimetype='application/json')
            # define type of DB and attempt the correct type of connect
            # and return the version of the db we are connected to
            if db_url.scheme == 'cosmos':
                cosmos_url = f"http://{db_url.hostname}:{db_url.port}"
                qs = parse_qs(db_url.query)
                cosmos_db_name = None
                cosmos_db_key = None
                if 'dbname' in qs:
                    cosmos_db_name = qs['dbname'][0]
                if 'dbkey' in qs:
                    cosmos_db_key = qs['dbkey'][0]
                try:
                    response = db_connect_cosmos(cosmos_url, cosmos_db_key, cosmos_db_name)
                    response_status = 200
                    if response['error']:
                        response_status = response['error']
                    return Response(
                        json.dumps(response),
                        status=response_status, mimetype='application/json')
                except Exception as ex:
                    return Response(
                        json.dumps({
                            "url": cosmos_url,
                            "error": 500,
                            "message": f"DB connection error: {ex}"
                        }),
                        status=500, mimetype='application/json')
        except URLError as ue:
            return Response(
                json.dumps({
                    "url": rargs.get("url"),
                    "error": 400,
                    "message": ue
                }),
                status=400, mimetype='application/json')
    else:
        return Response(
            json.dumps({
                "url": None,
                "error": 404,
                "message": "NotFound"
            }),
            status=404, mimetype='application/json')


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def get_resource(path):  # pragma: no cover
    mimetypes = {
        ".css": "text/css",
        ".html": "text/html",
        ".js": "application/javascript",
        ".jpeg": "image/jpeg",
        ".ico": "image/x-icon"
    }
    complete_path = os.path.join(root_dir(), path)
    ext = os.path.splitext(path)[1]
    mimetype = mimetypes.get(ext, "text/html")
    content = get_file(complete_path)
    return Response(content, mimetype=mimetype)


@websocket.on('connect')
def client_connect():
    print('client connected with sid: %s' % request.sid)


@websocket.on('disconnect')
def client_disconnect():
    print('client disconnected with sid: %s' % request.sid)
    destroy_all_processes_for_sid(request.sid)


@websocket.on_error_default
def error_handler(e):
    print('socket IO error: %s' % e)


@websocket.on('message')
def message_handler(message, data):
    print('received message: %s:%s sid: %s' % (message, data, request.sid))
    if message == 'commandRequest':
        if data['type'] == 'variable':
            print('setting client variable: %s with command: %s' %
                  (data['target'], data['cmd']))
            response = {
                'variableName': data['target'],
                'variableValue': None
            }
            if data['cmd'][0] == 'hostname':
                response['variableValue'] = get_hostname()
            if data['cmd'][0] == 'nameserver':
                response['variableValue'] = get_nameserver()
            emit('variableResponse', response)
        elif data['type'] == 'performance':
            print('running performance test with target: %s:%d' %
                  (data['target'], int(data['port'])))
            try:
                data['target'] = socket.gethostbyname(data['target'])
                exit_code = performance_test(
                    request.sid, data['id'], data['sourcelabel'], data['targetlabel'], data['target'], int(data['port']), int(data['runcount']), data['latency'], data['bandwidth'])
                complete_response = {
                    'id': data['id'],
                    'stream': 'completed',
                    'data': exit_code
                }
                print("commandResponse to %s: %s" %
                      (complete_response['stream'], complete_response['data']))
                emit('commandResponse', complete_response)
            except Exception as e:
                error_response = {
                    'id': data['id'],
                    'stream': 'stderr',
                    'data': "target: %s is not valid. %s - %s\n\n" % (data['target'], e.__class__.__name__, e)
                }
                print("commandResponse to %s: %s" %
                      (error_response['stream'], error_response['data']))
                emit('commandResponse', error_response)
                complete_response = {
                    'id': data['id'],
                    'stream': 'completed',
                    'data': -1
                }
                print("commandResponse to %s: %s" %
                      (complete_response['stream'], complete_response['data']))
                emit('commandResponse', complete_response)
        elif data['type'] == 'halt':
            destroy_all_processes_for_sid(request.sid)
            print('halting all commands for sid: %s' % request.sid)
            complete_response = {
                'id': data['id'],
                'stream': 'completed',
                'data': 0
            }
            emit('commandResponse', complete_response)
        elif data['type'] == 'webscreenshot':
            print('getting web screen shot for: %s' % data['target'])
            try:
                if not os.path.exists:
                    os.makedirs(PUPPETEER_HOME)
                urlparse(data['target'])
                scripting_path = os.path.dirname(os.path.realpath(__file__))
                snapshot_file_name = "%s.jpg" % base64.b64encode(
                    data['target'].encode()).decode()
                snapshot_file_path = "%s/%s" % (
                    PUPPETEER_HOME, snapshot_file_name)
                cmd = "%s/web_screenshot.py --url '%s' --screenshot '%s'" % (
                    scripting_path, data['target'], snapshot_file_path)
                print('running command: %s' % cmd)
                env = {'PYPPETEER_HOME': PUPPETEER_HOME}
                exit_code = run_cmd(request.sid, cmd, data['id'], env)
                display_response = {
                    'id': data['id'],
                    'stream': 'image',
                    'data': "/webscreenshots/%s" % snapshot_file_name
                }
                print("commandResponse to %s: %s" %
                      (display_response['stream'], display_response['data']))
                emit('commandResponse', display_response)
                complete_response = {
                    'id': data['id'],
                    'stream': 'completed',
                    'data': exit_code
                }
                print("commandResponse to %s: %s" %
                      (complete_response['stream'], complete_response['data']))
                emit('commandResponse', complete_response)
            except Exception as e:
                error_response = {
                    'id': data['id'],
                    'stream': 'stderr',
                    'data': "url: %s is not valid. %s - %s\n\n" % (data['cmd'], e.__class__.__name__, e)
                }
                print("commandResponse to %s: %s" %
                      (error_response['stream'], error_response['data']))
                emit('commandResponse', error_response)
                complete_response = {
                    'id': data['id'],
                    'stream': 'completed',
                    'data': -1
                }
                print("commandResponse to %s: %s" %
                      (complete_response['stream'], complete_response['data']))
                emit('commandResponse', complete_response)
        else:
            if command_allowed(data['cmd']):
                print('running %s for sid: %s' % (data['cmd'], request.sid))
                exit_code = run_cmd(request.sid, data['cmd'], data['id'])
                complete_response = {
                    'id': data['id'],
                    'stream': 'completed',
                    'data': exit_code
                }
                print("commandResponse to %s: %s" %
                      (complete_response['stream'], complete_response['data']))
                emit('commandResponse', complete_response)
            else:
                error_response = {
                    'id': data['id'],
                    'stream': 'stderr',
                    'data': "command: %s is not allowed on server." % data['cmd']
                }
                print("commandResponse to %s: %s" %
                      (error_response['stream'], error_response['data']))
                emit('commandResponse', error_response)
                complete_response = {
                    'id': data['id'],
                    'stream': 'completed',
                    'data': -1
                }
                print("commandResponse to %s: %s" %
                      (complete_response['stream'], complete_response['data']))
                emit('commandResponse', complete_response)
    else:
        print("recieved unknown message: %s:%s" % (message, data))


if __name__ == "__main__":
    websocket.run(
        app,
        host=config['http_listen_address'],
        port=int(config['http_listen_port'])
    )
