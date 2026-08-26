#!/usr/bin/env python3
"""Small dependency-free CLI for Linux Vortex Terminal.

The desktop renderer is optional: this command talks to the same Store and
ExecutionManager, preserving the one-authority rule for local commands.
"""
from __future__ import annotations
import argparse
import datetime
import difflib
import json
import os
import select
import shutil
import tempfile
import urllib.error
import urllib.request
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.artifacts import ArtifactError, analyze_path
from backend.vortex_backend import (ADAPTER_MANIFESTS, EXIT_CODES, ExecutionManager, SessionManager, Store, build_plan, build_undo_plan, detect_context, digest, now_iso, probe_executable, command_spec, report_markdown, runtime_root, validate_cwd, plan_digest)

def emit(value, as_json=False):
    if as_json: print(json.dumps({"schema_version": 1, **value}, sort_keys=True, indent=2))
    else: print(json.dumps(value, indent=2, ensure_ascii=False))

def plan_text(plan):
    print(f"[{plan['status'].upper()}] {plan['request']}")
    print(f"Plan {plan['id']}  expires {plan['expires_at']}  digest {plan['digest'][:18]}…")
    for i, command in enumerate(plan['commands'], 1):
        print(f"  {i}. {command['display']}")
        print(f"     {command['explanation']} [{command['risk']}, {command['network_class']}, {command['tool_state_at_plan']}]")
    for note in plan['notes']:
        print(f"  • {note}")
    if plan['approval_required']:
        print(f"\nConfirmation phrase: {plan['approval_phrase']}")

def wait_operation(store, manager, op_id):
    try:
        while True:
            op = store.get_operation(op_id)
            if op and op['status'] not in ('started', 'running'): return op
            time.sleep(.15)
    except KeyboardInterrupt:
        manager.cancel(op_id)
        raise

def _normalize_args(raw):
    # Accept global presentation/scope flags in the conventional position
    # before or after a subcommand, while keeping `--` opaque for direct mode.
    raw = list(raw)
    global_flags = {'--json', '--offline', '--no-color', '--non-interactive', '--allow-root', '--dry-run', '--yes'}
    prefix, cleaned, i = [], [], 0
    while i < len(raw):
        item = raw[i]
        if item == '--':
            cleaned.extend(raw[i:]); break
        if item in global_flags:
            prefix.append(item)
        elif item in ('--cwd', '--format', '--profile', '--engagement-id') and i + 1 < len(raw):
            prefix.extend([item, raw[i + 1]]); i += 1
        else:
            cleaned.append(item)
        i += 1
    # argparse otherwise assigns the first token after `run --` to the optional plan id.
    if 'run' in cleaned:
        try:
            run_at, separator = cleaned.index('run'), cleaned.index('--')
            if separator > run_at:
                cleaned = cleaned[:separator] + ['--direct-mode'] + cleaned[separator + 1:]
        except ValueError:
            pass
    commands = {'ask', 'plan', 'doctor', 'tools', 'adapters', 'artifact', 'backup', 'db', 'migrate', 'undo', 'retention', 'model', 'shell', 'history', 'explain', 'audit', 'report', 'completion', 'theme', 'engagement', 'session', 'run', 'health', 'agents', 'tasks', 'memory', 'learning', 'conversations', 'sandbox', 'plugins', 'benchmark', 'deps', 'serve', 'install', 'turn'}
    if cleaned and cleaned[0] not in commands and not cleaned[0].startswith('-'):
        cleaned.insert(0, '_request')
    return prefix + cleaned

SHELL_START = "# >>> vortex shell integration >>>"
SHELL_END = "# <<< vortex shell integration <<<"


def install_user(prefix=None, user=True):
    """Write a user-local launcher. Never uses sudo and never installs packages."""
    del user
    root = Path(__file__).resolve().parent.parent
    dest_dir = Path(prefix).expanduser() if prefix else Path.home() / ".local" / "bin"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "vortex"
    dest.write_text(f'#!/usr/bin/env sh\nexec python3 "{root / "cli" / "vortex.py"}" "$@"\n', encoding="utf-8")
    dest.chmod(0o755)
    return {
        "ok": True,
        "method": "user-local",
        "auto_install_packages": False,
        "path": str(dest),
        "source": str(root),
        "message": "User-local launcher written. Add ~/.local/bin to PATH if needed. No apt packages were installed.",
    }


def shell_rc_path(shell, home=None):
    home = Path(home or Path.home())
    return {'bash': home / '.bashrc', 'zsh': home / '.zshrc', 'fish': home / '.config' / 'fish' / 'config.fish'}[shell]


def shell_block(shell):
    if shell == 'fish':
        return f"{SHELL_START}\nfunction vortex-plan\n    command vortex plan $argv\nend\n{SHELL_END}\n"
    return f"{SHELL_START}\nvortex-plan() {{ command vortex plan \"$@\"; }}\n{SHELL_END}\n"


def shell_proposal(shell, current, install):
    start = current.find(SHELL_START)
    end = current.find(SHELL_END)
    if start >= 0 and end >= start:
        end += len(SHELL_END)
        if end < len(current) and current[end] == '\n': end += 1
        base = current[:start] + current[end:]
    else:
        base = current
    if install:
        if base and not base.endswith('\n'): base += '\n'
        base += shell_block(shell)
    return base


def shell_command(shell, action, yes, as_json):
    rc = shell_rc_path(shell)
    current = rc.read_text(encoding='utf-8', errors='replace') if rc.exists() else ''
    proposed = shell_proposal(shell, current, action != 'uninstall')
    diff = ''.join(difflib.unified_diff(current.splitlines(True), proposed.splitlines(True), fromfile=str(rc), tofile=str(rc) + ' (Vortex proposal)'))
    if action == 'preview':
        payload = {'shell': {'shell': shell, 'path': str(rc), 'action': action, 'changes': bool(diff), 'diff': diff}}
        if as_json: emit(payload, True)
        else: print(diff or 'No Vortex shell changes would be made.')
        return 0
    if not yes:
        if as_json: emit({'shell': {'shell': shell, 'path': str(rc), 'action': action, 'changes': bool(diff), 'diff': diff}, 'error': {'code':'confirmation_required'}}, True)
        else:
            print(diff or 'No Vortex shell changes would be made.', file=sys.stderr)
            print('Re-run with --yes to apply only the Vortex-owned block.', file=sys.stderr)
        return EXIT_CODES['confirmation_required']
    if diff:
        rc.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup = None
        if rc.exists():
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            backup = rc.with_name(rc.name + '.vortex.bak-' + stamp)
            shutil.copy2(rc, backup)
        fd, temp_name = tempfile.mkstemp(prefix='.vortex-shell-', dir=str(rc.parent), text=True)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as handle: handle.write(proposed)
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, rc)
        finally:
            if os.path.exists(temp_name): os.unlink(temp_name)
        Store().append_audit('shell_integration_' + action, {'shell': shell, 'path': str(rc), 'backup': str(backup) if backup else None})
    result = {'shell': {'shell': shell, 'path': str(rc), 'action': action, 'changed': bool(diff)}}
    if as_json: emit(result, True)
    else: print(f"[{('INSTALLED' if action == 'install' else 'UNINSTALLED')}] {shell} integration {'updated' if diff else 'already clean'}: {rc}")
    return 0


def runtime_metadata():
    path = runtime_root() / 'sidecar.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        pid = int(data.get('pid', 0))
        if pid and pid != os.getpid():
            try: os.kill(pid, 0)
            except OSError: return None
        return data
    except (OSError, ValueError, TypeError):
        return None


def remote_request(metadata, route, body=None):
    host = metadata.get('host')
    if host in ('0.0.0.0', '::', ''): host = '127.0.0.1'
    url = f"http://{host}:{int(metadata['port'])}{route}"
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers={'Content-Type':'application/json', **({'X-Vortex-Token': metadata['token']} if metadata.get('token') else {})})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as response:
        payload = json.loads(response.read())
    if 'error' in payload and not payload.get('ok', False): raise RuntimeError(payload['error'].get('message', 'sidecar request failed'))
    return payload


def attach_remote_session(metadata, session_id, as_json=False):
    sequence = 0
    while True:
        payload = remote_request(metadata, f"/api/sessions/{session_id}/events?since={sequence}")
        for event in payload.get('events', []):
            stream = sys.stderr if as_json else sys.stdout
            stream.write(event.get('data', '')); stream.flush(); sequence = max(sequence, int(event.get('seq', sequence)))
        session = payload.get('session')
        if session and session.get('status') not in ('starting', 'running'): return session
        readable, _, _ = select.select([sys.stdin], [], [], .05)
        if readable:
            data = os.read(sys.stdin.fileno(), 65536)
            if not data:
                remote_request(metadata, f"/api/sessions/{session_id}/kill", {}); return payload.get('session')
            remote_request(metadata, f"/api/sessions/{session_id}/input", {'data': data.decode('utf-8', errors='replace')})


def attach_foreground_session(manager, session_id):
    sequence = 0
    while True:
        payload = manager.events_since(session_id, sequence)
        for event in payload.get('events', []):
            sys.stdout.write(event.get('data', ''))
            sys.stdout.flush()
            sequence = max(sequence, event.get('seq', sequence))
        session = payload.get('session')
        if session and session.get('status') not in ('starting', 'running'):
            return session
        readable, _, _ = select.select([sys.stdin], [], [], 0.05)
        if readable:
            data = os.read(sys.stdin.fileno(), 65536)
            if not data:
                manager.kill(session_id)
                return manager.info(session_id)
            manager.write(session_id, data.decode('utf-8', errors='replace'))


def main(argv=None):
    argv = _normalize_args(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog='vortex', description='Linux Vortex Terminal — local-first AI cybersecurity and Linux operations workbench')
    parser.add_argument('--json', action='store_true', dest='as_json', help='machine-readable output')
    parser.add_argument('--cwd', default=None, help='working-directory scope')
    parser.add_argument('--engagement-id', default=None, help='active authorized engagement for security adapters')
    parser.add_argument('--offline', action='store_true', help='disable model and outbound capabilities')
    parser.add_argument('--no-color', action='store_true', help='disable terminal color')
    parser.add_argument('--non-interactive', action='store_true')
    parser.add_argument('--allow-root', action='store_true', help='explicitly allow one UID 0 invocation')
    parser.add_argument('--dry-run', action='store_true', help='print a plan without executing it')
    parser.add_argument('--yes', action='store_true', help='skip the interactive prompt only for a policy-valid plan')
    parser.add_argument('--format', choices=('text', 'json', 'md'), default='text', help='output format')
    parser.add_argument('--profile', choices=('safe', 'standard', 'expert'), default='safe', help='policy friction profile')
    parser.add_argument('--version', action='version', version='vortex 0.2.0')
    sub = parser.add_subparsers(dest='subcommand')
    for name in ('ask', 'plan'):
        p = sub.add_parser(name); p.add_argument('request')
    sub.add_parser('doctor')
    sub.add_parser('tools')
    sub.add_parser('adapters')
    sub.add_parser('health')
    sub.add_parser('agents')
    tk = sub.add_parser('tasks'); tk.add_argument('action', choices=['list','show','pause','reject'], nargs='?', default='list'); tk.add_argument('task_id', nargs='?')
    sub.add_parser('memory')
    sub.add_parser('learning')
    conv = sub.add_parser('conversations'); conv.add_argument('action', choices=['list','show','export'], nargs='?', default='list'); conv.add_argument('conversation_id', nargs='?')
    sub.add_parser('sandbox')
    sub.add_parser('plugins')
    sub.add_parser('deps')
    sub.add_parser('benchmark')
    sv = sub.add_parser('serve'); sv.add_argument('--bind-host', dest='bind_host', default=os.environ.get('VORTEX_HOST', '127.0.0.1')); sv.add_argument('--bind-port', dest='bind_port', type=int, default=int(os.environ.get('VORTEX_PORT', '8765'))); sv.add_argument('--token', default=os.environ.get('VORTEX_SIDECAR_TOKEN'))
    ins = sub.add_parser('install'); ins.add_argument('--user', action='store_true', dest='user_install'); ins.add_argument('--prefix', default=None)
    tn = sub.add_parser('turn'); tn.add_argument('request')
    art = sub.add_parser('artifact'); art.add_argument('action', choices=['inspect','analyze'], nargs='?', default='inspect'); art.add_argument('path'); art.add_argument('--type', choices=['auto','nmap-xml','http-headers','text'], default='auto')
    b = sub.add_parser('backup'); b.add_argument('path'); b.add_argument('--force', action='store_true')
    db = sub.add_parser('db'); db.add_argument('action', choices=['integrity'], nargs='?', default='integrity')
    sub.add_parser('migrate')
    u = sub.add_parser('undo'); u.add_argument('history_id')
    rt = sub.add_parser('retention'); rt.add_argument('action', choices=['status','prune'], nargs='?', default='status'); rt.add_argument('--history-days', type=int, default=90); rt.add_argument('--output-days', type=int, default=30)
    mdl = sub.add_parser('model'); mdl.add_argument('action', choices=['status','list','test','use'], nargs='?', default='status'); mdl.add_argument('provider', nargs='?')
    sh = sub.add_parser('shell'); sh.add_argument('action', choices=['preview','install','uninstall']); sh.add_argument('shell', choices=['bash','zsh','fish'])
    h = sub.add_parser('history'); h.add_argument('action', choices=['list','show','search','replay'], nargs='?', default='list'); h.add_argument('query', nargs='?')
    x = sub.add_parser('explain'); x.add_argument('request', nargs='+')
    a = sub.add_parser('audit'); a.add_argument('action', choices=['verify'], nargs='?', default='verify')
    rprt = sub.add_parser('report'); rprt.add_argument('history_id')
    c = sub.add_parser('completion'); c.add_argument('shell', choices=['bash','zsh','fish'])
    t = sub.add_parser('theme'); t.add_argument('action', choices=['show','preview','export','install','uninstall'], nargs='?', default='show')
    sess = sub.add_parser('session'); sess.add_argument('action', choices=['new','list','attach','kill'], nargs='?', default='new'); sess.add_argument('session_id', nargs='?'); sess.add_argument('--shell')
    e = sub.add_parser('engagement'); e.add_argument('action', choices=['list','create']); e.add_argument('--name'); e.add_argument('--authorization'); e.add_argument('--target', action='append')
    n = sub.add_parser('_request', help=argparse.SUPPRESS); n.add_argument('request', nargs='+')
    sub._choices_actions = [action for action in sub._choices_actions if action.dest != '_request']
    r = sub.add_parser('run'); r.add_argument('plan_id', nargs='?'); r.add_argument('--digest'); r.add_argument('--approval-token'); r.add_argument('--preflight-digest'); r.add_argument('--direct-mode', nargs=argparse.REMAINDER, dest='direct_mode'); r.add_argument('direct', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    args.as_json = args.as_json or args.format == 'json'
    is_natural_request = args.subcommand == '_request'
    store = Store()
    try:
        if args.subcommand == 'doctor': emit({'doctor': detect_context()}, args.as_json); return EXIT_CODES['success']
        if args.subcommand == 'health':
            from backend.health import collect
            from backend.config import load_settings
            emit({'health': collect(store, None, load_settings())}, args.as_json); return 0
        if args.subcommand == 'agents':
            from backend.agents.council import discover
            emit({'agents': discover()}, args.as_json); return 0
        if args.subcommand == 'tasks':
            from backend.workspace import Workspace
            workspace = Workspace(store)
            if getattr(args, 'action', 'list') == 'show' and getattr(args, 'task_id', None):
                emit({'task': workspace.get_task(args.task_id)}, args.as_json); return 0
            if args.action in ('pause', 'reject'):
                if not args.task_id:
                    raise ValueError('task id is required')
                manager = ExecutionManager(store)
                if args.action == 'pause':
                    task = workspace.pause_task(args.task_id, manager)
                    if not task:
                        raise ValueError('task not found')
                    emit({'task': task}, args.as_json); return 0
                task = workspace.get_task(args.task_id)
                if not task or not task.get('plan_id'):
                    raise ValueError('task or plan not found')
                emit(workspace.reject_task_plan(task['plan_id'], task['id'], manager), args.as_json); return 0
            emit({'tasks': workspace.list_tasks(), 'interrupted': workspace.interrupted_tasks()}, args.as_json); return 0
        if args.subcommand == 'memory':
            from backend.workspace import Workspace
            emit({'memories': Workspace(store).list_memories()}, args.as_json); return 0
        if args.subcommand == 'learning':
            from backend.workspace import Workspace
            ws = Workspace(store)
            emit({'experiences': ws.list_experiences(), 'procedures': ws.list_procedures()}, args.as_json); return 0
        if args.subcommand == 'sandbox':
            from backend.sandbox import isolation_status
            emit({'sandbox': isolation_status()}, args.as_json); return 0
        if args.subcommand == 'plugins':
            from backend.plugins.loader import list_manifests
            emit({'plugins': list_manifests()}, args.as_json); return 0
        if args.subcommand == 'deps':
            from backend.dependencies import inventory
            emit({'dependencies': inventory()}, args.as_json); return 0
        if args.subcommand == 'serve':
            from backend.vortex_backend import serve
            serve(getattr(args, 'bind_host', '127.0.0.1'), int(getattr(args, 'bind_port', 8765)), getattr(args, 'token', None))
            return 0
        if args.subcommand == 'install':
            result = install_user(getattr(args, 'prefix', None))
            emit({'install': result}, args.as_json)
            return 0 if result.get('ok') else EXIT_CODES['failure']
        if args.subcommand == 'turn':
            from backend.config import load_settings
            from backend.orchestrate import run_turn
            from backend.workspace import Workspace
            settings = load_settings()
            if args.offline:
                settings['offline'] = True
            result = run_turn(store, Workspace(store), ExecutionManager(store), args.request, cwd=args.cwd, engagement_id=args.engagement_id, conversation_id=None, settings=settings, confirm=bool(args.yes), approval_token=None)
            emit(result, args.as_json)
            return 0
        if args.subcommand == 'benchmark':
            from backend.benchmark import run_suite
            from backend.workspace import Workspace
            emit({'benchmark': run_suite(store, Workspace(store), ExecutionManager(store), args.cwd)}, args.as_json); return 0
        if args.subcommand == 'conversations':
            from backend.workspace import Workspace
            ws = Workspace(store)
            if args.action in ('show', 'export') and args.conversation_id:
                emit({'export' if args.action == 'export' else 'conversation': ws.export_conversation(args.conversation_id)}, args.as_json); return 0
            emit({'conversations': ws.list_conversations()}, args.as_json); return 0
        if args.subcommand == 'tools': emit({'tools': [{**probe_executable(n), 'family': m['family'], 'role': m['role']} for n,m in __import__('backend.vortex_backend', fromlist=['TOOL_CATALOG']).TOOL_CATALOG.items()]}, args.as_json); return 0
        if args.subcommand == 'adapters':
            items = []
            for adapter_id, manifest in ADAPTER_MANIFESTS.items():
                tools = [] if manifest['tool'] == 'multiple' else manifest['tool'].split('+')
                items.append({'id': adapter_id, **manifest, 'tool_state': {tool: probe_executable(tool)['state'] for tool in tools}})
            emit({'adapters': items}, args.as_json); return 0
        if args.subcommand == 'artifact':
            artifact = analyze_path(args.path, args.type)
            store.save_artifact(artifact)
            emit({'artifact': artifact}, args.as_json)
            return 0 if artifact.get('state') != 'tool_error' else EXIT_CODES['failure']
        if args.subcommand == 'backup':
            destination = store.backup(args.path, args.force)
            emit({'backup': {'path': str(destination), 'mode': oct(destination.stat().st_mode & 0o777)}}, args.as_json)
            return 0
        if args.subcommand == 'db':
            result = {'integrity': store.integrity_check()}
            emit(result, args.as_json)
            return 0 if result['integrity']['valid'] else EXIT_CODES['integrity_failure']
        if args.subcommand == 'migrate':
            result = {'migration': {'schema_version': 1, 'state': 'compatible', 'message': 'No irreversible schema migration is pending.'}}
            emit(result, args.as_json); return 0
        if args.subcommand == 'undo':
            plan = build_undo_plan(store, args.history_id)
            if args.as_json: emit({'plan': plan}, True)
            else: plan_text(plan)
            return 0
        if args.subcommand == 'retention':
            if args.action == 'status':
                emit({'retention': {'history_days': 90, 'output_days': 30, 'policy': 'redacted local evidence; raw evidence is opt-in'}}, args.as_json); return 0
            emit({'prune': store.prune(args.history_days, args.output_days)}, args.as_json); return 0
        if args.subcommand == 'model':
            model = {'state': 'disabled', 'providers': [], 'selected': None, 'network': 'disabled', 'message': 'No local model is configured; deterministic mode remains active.'}
            if args.action == 'use': model['message'] = 'No provider selected. Configuration is not implemented in this offline-first build.'
            emit({'model': model}, args.as_json)
            return 0 if args.action in ('status', 'list') else EXIT_CODES['unavailable']
        if args.subcommand == 'shell':
            return shell_command(args.shell, args.action, getattr(args, 'yes', False), args.as_json)
        if args.subcommand == 'session':
            metadata = runtime_metadata()
            if args.action == 'list':
                if metadata:
                    try: emit({'sessions': remote_request(metadata, '/api/sessions').get('sessions', [])}, args.as_json); return 0
                    except Exception: pass
                emit({'sessions': store.list_sessions()}, args.as_json); return 0
            if metadata:
                try:
                    if args.action == 'attach':
                        if not args.session_id: raise ValueError('session attach requires a session id')
                        result = attach_remote_session(metadata, args.session_id, args.as_json)
                        if args.as_json: emit({'session': result}, True)
                        return EXIT_CODES['success'] if result and result.get('status') == 'succeeded' else EXIT_CODES['command_failed']
                    if args.action == 'kill':
                        if not args.session_id: raise ValueError('session kill requires a session id')
                        remote_request(metadata, f"/api/sessions/{args.session_id}/kill", {})
                        emit({'session_id': args.session_id, 'kill_requested': True}, args.as_json); return 0
                    if args.action == 'new':
                        created = remote_request(metadata, '/api/sessions', {'name':'cli shell','cwd':args.cwd,'shell':args.shell})['session']
                        result = attach_remote_session(metadata, created['id'], args.as_json)
                        if args.as_json: emit({'session': result}, True)
                        return EXIT_CODES['success'] if result and result.get('status') == 'succeeded' else EXIT_CODES['command_failed']
                except (urllib.error.URLError, RuntimeError):
                    pass
            if args.action in ('attach', 'kill'):
                raise ValueError('no live Vortex sidecar owns this session; start the desktop sidecar or use `vortex session new`')
            if not sys.stdin.isatty() and not args.non_interactive:
                raise PermissionError('session new requires an interactive TTY')
            sessions = SessionManager(store)
            session = sessions.create(name='cli shell', cwd_raw=args.cwd, shell=args.shell)
            if args.as_json:
                print(json.dumps({'schema_version': 1, 'session': session}, sort_keys=True), file=sys.stderr)
            else:
                print(f"[SESSION {session['id']}] real PTY attached", file=sys.stderr)
            try:
                result = attach_foreground_session(sessions, session['id'])
            except KeyboardInterrupt:
                sessions.kill(session['id']); raise
            finally:
                sessions.shutdown()
            if args.as_json: emit({'session': result}, True)
            return EXIT_CODES['success'] if result and result.get('status') == 'succeeded' else EXIT_CODES['command_failed']
        if args.subcommand == 'history':
            history = store.list_history()
            if args.action == 'show': history = [x for x in history if x['id'] == args.query]
            elif args.action == 'search' and args.query: history = [x for x in history if args.query.lower() in json.dumps(x).lower()]
            elif args.action == 'replay':
                if not args.query: raise ValueError('history replay requires an operation id')
                print('Replay is plan-only: inspect the saved operation and create a fresh plan before approval.', file=sys.stderr)
                history = [x for x in history if x['id'] == args.query]
            emit({'history': history}, args.as_json); return 0
        if args.subcommand == 'audit':
            result = {'audit': store.verify_audit()}; emit(result, args.as_json); return 0 if result['audit']['valid'] else EXIT_CODES['integrity_failure']
        if args.subcommand == 'explain':
            plan = build_plan(store, 'explain ' + ' '.join(args.request), args.cwd, args.engagement_id, args.offline)
            plan['approval_required'] = False
            emit({'explanation': plan}, args.as_json)
            return 0
        if args.subcommand == 'report':
            operation = store.get_operation(args.history_id)
            if not operation: raise ValueError('history id not found')
            if args.format == 'json' or args.as_json: emit({'report': operation}, True)
            else:
                print(report_markdown(operation), end='')
            return 0
        if args.subcommand == 'completion':
            filename = {'bash':'assets/completions/vortex.bash','zsh':'assets/completions/vortex.zsh','fish':'assets/completions/vortex.fish'}[args.shell]
            print(Path(__file__).resolve().parent.parent.joinpath(filename).read_text())
            return 0
        if args.subcommand == 'theme':
            emit({'theme': {'name':'vortex-dark', 'action':args.action, 'palette':{'background':'#0a0a0c','foreground':'#f0f0f4','cyan':'#00d4aa','green':'#23a049','amber':'#e6a817','critical':'#cc0000'}, 'writes_terminal_config':False}}, args.as_json); return 0
        if args.subcommand == 'engagement':
            if args.action == 'list': emit({'engagements': store.list_engagements()}, args.as_json); return 0
            from backend.vortex_backend import normalize_target, secrets, datetime, timezone
            item={'schema_version':1,'id':secrets.token_hex(16),'created_at':now_iso(),'expires_at':datetime.fromtimestamp(time.time()+86400,tz=timezone.utc).isoformat(),'name':args.name or 'Authorized assessment','authorization':args.authorization or 'operator-declared authorization','targets':[normalize_target(x) for x in (args.target or [])],'classes':['reconnaissance'],'status':'active'}
            if not item['targets']: raise ValueError('--target is required')
            store.create_engagement(item); emit({'engagement':item},args.as_json); return 0
        if args.subcommand == 'run' and ((args.plan_id is None and (args.direct_mode or args.direct)) or args.plan_id == '--'):
            direct = args.direct_mode or args.direct
            if direct and direct[0] == '--': direct = direct[1:]
            if not direct: raise ValueError('direct command is empty')
            cwd=validate_cwd(args.cwd); spec=command_spec(direct[0],direct,cwd,risk='high',network='unknown',reject_shell_syntax=False,explanation='Explicit operator-direct command; not AI-validated.')
            plan={'schema_version':1,'id':__import__('secrets').token_hex(32),'created_at':now_iso(),'expires_at':now_iso(),'request':'operator direct command','cwd':str(cwd),'status':'planned','kind':'operator_direct','risk':'high','authorization':'operator_direct','commands':[spec],'notes':['Direct operator command. Shell interpolation is disabled and source attribution is operator_direct.'],'missing_tools':[],'scope':{'cwd':str(cwd)},'workers':[],'approval_required':True,'approval_phrase':'APPROVE '+spec['display'],'source':'operator_direct','policy_version':'safe-v1','knowledge_version':'builtin-v1','approval_token':__import__('secrets').token_urlsafe(32)}
            plan['expires_at']=__import__('datetime').datetime.fromtimestamp(time.time()+900,__import__('datetime').timezone.utc).isoformat(); plan['digest']=plan_digest(plan); store.save_plan(plan)
        elif args.subcommand in ('ask','plan'):
            plan=build_plan(store,args.request,args.cwd, args.engagement_id, offline=args.offline)
            if args.subcommand == 'ask': plan['approval_required']=False
            if args.as_json: emit({'plan':plan},True)
            else: plan_text(plan)
            return 0
        elif args.subcommand == '_request':
            request = ' '.join(args.request)
            plan = build_plan(store, request, args.cwd, args.engagement_id, offline=args.offline)
            if not args.as_json: plan_text(plan)
        else:
            request = ' '.join(args.direct) if args.direct else ' '.join(parser.parse_known_args(argv)[1]) if argv else ''
            if not request: parser.print_help(); return EXIT_CODES['invalid_usage']
            plan=build_plan(store,request,args.cwd, args.engagement_id, offline=args.offline)
            if args.as_json: emit({'plan':plan},True)
            else: plan_text(plan)
        if not plan.get('commands'):
            if is_natural_request and args.as_json: emit({'plan': plan}, True)
            return EXIT_CODES['unavailable'] if plan['status']=='unavailable' else 0
        if args.dry_run:
            if is_natural_request and args.as_json: emit({'plan': plan}, True)
            return 0
        yes = getattr(args, 'yes', False)
        non_interactive = getattr(args, 'non_interactive', False)
        if not yes:
            if non_interactive:
                if is_natural_request and args.as_json: emit({'plan': plan, 'error': {'code': 'confirmation_required'}}, True)
                return EXIT_CODES['confirmation_required']
            print('\nApprove this exact plan? Type APPROVE to continue: ', end='', file=sys.stderr)
            answer=sys.stdin.readline().strip()
            if answer != 'APPROVE':
                if is_natural_request and args.as_json: emit({'plan': plan, 'error': {'code': 'confirmation_declined'}}, True)
                return EXIT_CODES['confirmation_required']
        if non_interactive and (not getattr(args, 'digest', None) or not getattr(args, 'approval_token', None) or args.digest != plan['digest']): return EXIT_CODES['policy_denied']
        manager=ExecutionManager(store); op=manager.start(plan,True,getattr(args, 'approval_token', None) or plan['approval_token'],getattr(args, 'allow_root', False), getattr(args, 'offline', False)); op=wait_operation(store,manager,op['id'])
        if op.get('status') == 'awaiting_confirmation':
            if not yes:
                print('\nFresh preflight completed. Review the observed facts before approving the mutation:', file=sys.stderr)
                print(json.dumps(op.get('facts', {}), sort_keys=True, indent=2), file=sys.stderr)
                print('Type APPROVE to execute the mutation: ', end='', file=sys.stderr)
                if sys.stdin.readline().strip() != 'APPROVE':
                    manager.cancel(op['id'])
                    return EXIT_CODES['confirmation_required']
            preflight_digest = getattr(args, 'preflight_digest', None) or op.get('preflight_digest')
            op = manager.approve_preflight(op['id'], True, getattr(args, 'approval_token', None) or plan['approval_token'], preflight_digest)
            op = wait_operation(store, manager, op['id'])
        if args.as_json:
            emit({'plan': plan, 'operation': op} if is_natural_request else {'operation': op}, True)
        else: print(f"[{op['status'].upper()}] operation {op['id']}")
        return {'succeeded': EXIT_CODES['success'], 'cancelled': EXIT_CODES['interrupted'], 'interrupted': EXIT_CODES['interrupted'], 'timed_out': EXIT_CODES['timeout'], 'unavailable': EXIT_CODES['unavailable']}.get(op['status'], EXIT_CODES['command_failed'])
    except KeyboardInterrupt: return EXIT_CODES['interrupted']
    except PermissionError as exc: print(f"vortex: {exc}", file=sys.stderr); return EXIT_CODES['confirmation_required']
    except Exception as exc: print(f"vortex: {exc}", file=sys.stderr); return EXIT_CODES['failure']

if __name__ == '__main__': raise SystemExit(main())
