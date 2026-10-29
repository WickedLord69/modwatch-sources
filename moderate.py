"""Moderate source references. Never fetch or execute submitted URLs or attachments."""
import base64
import hashlib
import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

MARKER = '<!-- modwatch-source-review -->'
LABELS = {
    'pending': ('fbca04', 'Awaiting owner review'),
    'published': ('0e8a16', 'Owner-approved reference published'),
    'rejected': ('b60205', 'Not accepted for the shared catalog'),
    'needs-information': ('d4c5f9', 'More information needed before approval'),
    'validation-failed': ('e99695', 'Submission did not pass structural validation'),
}
FIELDS = {'Filename', 'Mod name', 'Author', 'Source URL', 'Search aliases', 'Version comparison', 'Confirmation'}

def public_text(value, maximum=120):
    if not isinstance(value, str):
        raise ValueError('Text fields must be strings.')
    value = value.strip()
    if len(value) > maximum or re.search(r'[\x00-\x1f\x7f\\`<>]|[A-Za-z]:/|https?://', value, re.I):
        raise ValueError('Use short public labels, not paths, links, markup or control characters.')
    return value

def source_url(value):
    if not isinstance(value, str) or len(value) > 1000 or re.search(r'[\x00-\x20<>`]', value):
        raise ValueError('Use a plain HTTPS release-page URL.')
    u = urllib.parse.urlsplit(value)
    host = (u.hostname or '').lower()
    if u.scheme != 'https' or u.username or u.password or u.port not in (None, 443) or u.query or u.fragment:
        raise ValueError('Use HTTPS without credentials, query parameters or fragments.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('Use a public website name, not an IP address.')
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}', host) or host.endswith(('.local', '.localhost', '.internal')):
        raise ValueError('Use a public website name.')
    path = urllib.parse.unquote(u.path)
    if re.search(r'[\x00-\x20<>`\\]', path) or re.search(r'\.(zip|rar|7z|dll|asi|exe)$', path, re.I) or re.search(r'/(?:download|downloads)/?$', path, re.I):
        raise ValueError('Link the release listing, not a direct binary/archive download.')
    original_host = host
    host = host.removeprefix('www.')
    external = False
    if host == 'lcpdfr.com':
        if not re.fullmatch(r'/(?:downloads/gta5mods/scripts|files/file)/\d+-[^/]+/?', path, re.I):
            raise ValueError('For LCPDFR, choose the script/plugin page rather than a vehicle or clothing listing.')
        host = 'www.lcpdfr.com'
        path = path.rstrip('/') + '/'
    elif host == 'gta5-mods.com':
        if not re.fullmatch(r'/(?:scripts|tools|misc)/[^/]+/?', path, re.I):
            raise ValueError('Choose the plugin/tool page rather than a vehicle, clothing or map listing.')
        host = 'www.gta5-mods.com'
        path = path.rstrip('/')
    elif host == 'nexusmods.com':
        m = re.fullmatch(r'/(?:games/)?gta5/mods/(\d+)/?', path, re.I)
        if not m:
            raise ValueError('Choose a GTA V mod page on Nexus Mods.')
        host, path = 'www.nexusmods.com', '/games/gta5/mods/' + m[1]
    elif host == 'github.com':
        parts = path.strip('/').split('/')
        if len(parts) < 2 or not all(re.fullmatch(r'[\w.-]+', p) for p in parts[:2]) or parts[0] in {'search', 'settings', 'login'}:
            raise ValueError('Choose a public mod repository.')
        path = '/' + '/'.join(parts[:2])
    elif host == 'bejoijo.com':
        if not re.fullmatch(r'/post/[\w-]+/?', path):
            raise ValueError('Choose the individual BejoIjo release page.')
        host, path = 'www.bejoijo.com', path.rstrip('/')
    elif host == 'dev-c.com' and path.rstrip('/') == '/gtav/scripthookv':
        host, path = 'www.dev-c.com', '/gtav/scripthookv/'
    else:
        host = original_host
        external = True
    return urllib.parse.urlunsplit(('https', host, path, '', '')), external

def parse_submission(body):
    if not isinstance(body, str) or len(body) > 15000:
        raise ValueError('Missing or oversized source submission.')
    sections = {}
    for match in re.finditer(r'^### ([^\r\n]+)\r?\n([\s\S]*?)(?=^### |\Z)', body, re.M):
        key, value = match[1].strip(), match[2].strip()
        if key not in FIELDS or key in sections:
            raise ValueError('Unexpected or duplicate form field.')
        sections[key] = '' if value == '_No response_' else value
    for key in ('Filename', 'Mod name', 'Source URL', 'Version comparison'):
        if not sections.get(key):
            raise ValueError('Missing form field: ' + key)
    filename = public_text(sections['Filename'], 150)
    if re.search(r'[<>:"/\\|?*]', filename) or not re.fullmatch(r'.+\.(?:dll|asi|cs|vb|lua|js|exe)', filename, re.I):
        raise ValueError('Filename must be a plain DLL/ASI/script filename without folders.')
    url, external = source_url(sections['Source URL'])
    aliases = [public_text(a) for a in sections.get('Search aliases', '').split(';') if a.strip()]
    if len(aliases) > 16:
        raise ValueError('Use no more than 16 aliases.')
    comparison = sections['Version comparison']
    if comparison not in ('Normal version checks', 'Require manual build review'):
        raise ValueError('Unrecognized version comparison option.')
    entry = dict(FileName=filename, Name=public_text(sections['Mod name']), Author=public_text(sections.get('Author', '')),
                 Url=url, Aliases=list(dict.fromkeys(aliases)), ReviewOnly=comparison == 'Require manual build review')
    digest = hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return entry, digest, external

def approved_catalog(catalog, entry, replace=False):
    if not isinstance(catalog, dict) or catalog.get('SchemaVersion') != 1 or not isinstance(catalog.get('Entries'), list):
        raise ValueError('Published catalog schema is invalid; no change made.')
    rows = catalog['Entries']
    existing = [e for e in rows if e['FileName'].casefold() == entry['FileName'].casefold()]
    different = any(e['Url'].rstrip('/').casefold() != entry['Url'].rstrip('/').casefold() for e in existing)
    if different and not replace:
        raise ValueError('This filename already has another source. Review the existing mapping and use the explicit /replace command to change it.')
    retained = [e for e in rows if not (e['FileName'].casefold() == entry['FileName'].casefold() and
                 (replace or e['Url'].rstrip('/').casefold() == entry['Url'].rstrip('/').casefold()))]
    retained.append(entry)
    retained.sort(key=lambda e: (e['FileName'].casefold(), e['Url'].casefold()))
    result = {'SchemaVersion': 1, 'Entries': retained}
    if len(retained) > 5000 or len(json.dumps(result).encode()) > 4_000_000:
        raise ValueError('Catalog size limit exceeded.')
    return result

def approval_command(comment, author, owner, digest, external=False):
    if author.casefold() != owner.casefold():
        return None
    match = re.fullmatch(r'/(approve|replace|approve-external|replace-external|reject|needs-info)\s+([a-f0-9]{64})', comment.strip(), re.I)
    if not match:
        return None
    if match[2].lower() != digest:
        raise ValueError('The submission changed after the reviewed receipt. Copy the command from the newest review receipt.')
    action = match[1].lower()
    if external and action in ('approve', 'replace'):
        raise ValueError('This website is outside the supported source list. Review its identity and use the explicit external-source approval command.')
    return action

class GitHub:
    def __init__(self, repository, token):
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository):
            raise ValueError('Invalid repository context.')
        self.repository, self.owner, self.token = repository, repository.split('/')[0], token

    def request(self, method, path, value=None):
        data = json.dumps(value).encode() if value is not None else None
        request = urllib.request.Request('https://api.github.com/repos/' + self.repository + path, data=data, method=method,
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'User-Agent': 'ModWatch-source-moderation'})
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read(6_000_000)
            return json.loads(raw) if raw else None

    def comment(self, number, message):
        return self.request('POST', f'/issues/{int(number)}/comments', {'body': message})

    def status(self, number, name, close=False):
        color, description = LABELS[name]
        try:
            self.request('POST', '/labels', dict(name=name, color=color, description=description))
        except urllib.error.HTTPError as error:
            if error.code != 422:
                raise
        issue = self.request('GET', f'/issues/{int(number)}')
        labels = [e['name'] for e in issue.get('labels', []) if e['name'] not in LABELS] + [name]
        value = {'labels': labels}
        if close:
            value.update(state='closed', state_reason='completed' if name == 'published' else 'not_planned')
        self.request('PATCH', f'/issues/{int(number)}', value)

    def receipt(self, number, entry, digest, external):
        approve = 'approve-external' if external else 'approve'
        replace = 'replace-external' if external else 'replace'
        message = MARKER + '\n## Pending source review\n\n' + \
            'Structural checks passed. The owner must still verify the page supplies this file and belongs to the expected author. ' + \
            ('**This is an external website: inspect it carefully before approving.**\n\n' if external else '\n\n') + \
            '```json\n' + json.dumps(entry, indent=2, ensure_ascii=False) + '\n```\n\n' + \
            f'Only @{self.owner} can publish. Copy the appropriate command into a new comment:\n\n' + \
            f'**Approve new/same source:**\n```text\n/{approve} {digest}\n```\n' + \
            f'**Replace an existing different source:**\n```text\n/{replace} {digest}\n```\n' + \
            f'**Ask for information:**\n```text\n/needs-info {digest}\n```\n' + \
            f'**Reject:**\n```text\n/reject {digest}\n```\n\n' + \
            'Commands apply only to these exact details. Editing the submission requires a fresh receipt.'
        comments = self.request('GET', f'/issues/{number}/comments?per_page=100')
        previous = next((c for c in comments if c['user']['login'] == 'github-actions[bot]' and c['body'].startswith(MARKER)), None)
        if previous:
            self.request('PATCH', f'/issues/comments/{previous["id"]}', {'body': message})
        else:
            self.comment(number, message)
        self.status(number, 'pending')

    def publish(self, number, entry, replace):
        for attempt in range(4):
            current = self.request('GET', '/contents/catalog.json?ref=main')
            catalog = json.loads(base64.b64decode(current['content']))
            updated = approved_catalog(catalog, entry, replace)
            if updated == catalog:
                return 'This approved reference is already in the catalog.'
            value = {'message': f'Approve source reference from issue #{number}', 'branch': 'main', 'sha': current['sha'],
                     'content': base64.b64encode((json.dumps(updated, indent=2, ensure_ascii=False) + '\n').encode()).decode()}
            try:
                result = self.request('PUT', '/contents/catalog.json', value)
                return 'Published in commit ' + result['commit']['sha'] + '.'
            except urllib.error.HTTPError as error:
                if error.code not in (409, 422) or attempt == 3:
                    raise
        raise RuntimeError('Catalog changed repeatedly; retry the approval.')

def handle(event, api):
    issue = event.get('issue', {})
    if 'pull_request' in issue or not isinstance(issue.get('number'), int):
        return
    number = issue['number']
    comment = event.get('comment')
    if comment:
        # Ignore every non-owner comment, including our own bot receipts.
        if comment.get('user', {}).get('login', '').casefold() != api.owner.casefold():
            return
        if not comment.get('body', '').strip().startswith(('/approve ', '/replace ', '/approve-external ', '/replace-external ', '/reject ', '/needs-info ')):
            return
    current = api.request('GET', f'/issues/{number}')
    if current.get('state') != 'open':
        return
    try:
        entry, digest, external = parse_submission(current.get('body', ''))
        if not comment:
            if not current.get('title', '').startswith('[Source]'):
                return
            api.receipt(number, entry, digest, external)
            return
        action = approval_command(comment['body'], comment['user']['login'], api.owner, digest, external)
        if not action:
            return
        if action == 'reject':
            api.status(number, 'rejected', True)
            api.comment(number, 'Rejected by the catalog owner. This reference was not added to the catalog.')
        elif action == 'needs-info':
            api.status(number, 'needs-information')
            api.comment(number, 'More information was requested by the owner. Please explain which file this page supplies and who publishes it, then edit the submission.')
        else:
            result = api.publish(number, entry, action.startswith('replace'))
            # A later edit is a new proposal; do not close it as though those new details were approved.
            latest = api.request('GET', f'/issues/{number}')
            try:
                unchanged = parse_submission(latest.get('body', ''))[1] == digest
            except ValueError:
                unchanged = False
            api.status(number, 'published' if unchanged else 'pending', unchanged)
            api.comment(number, result + '\n\nModWatch users receive it during their next shared-catalog refresh. ' +
                        ('' if unchanged else 'A newer edit was not included; it needs a fresh owner review.'))
    except ValueError as error:
        api.status(number, 'validation-failed' if not comment else 'pending')
        api.comment(number, 'No catalog change made: ' + str(error))
        if comment:
            try:
                entry, digest, external = parse_submission(current.get('body', ''))
                api.receipt(number, entry, digest, external)
            except ValueError:
                pass

if __name__ == '__main__':
    with open(os.environ['GITHUB_EVENT_PATH'], encoding='utf-8') as stream:
        event = json.load(stream)
    handle(event, GitHub(os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_TOKEN']))
