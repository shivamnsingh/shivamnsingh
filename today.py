import datetime
from dateutil import relativedelta
import requests
import os
from lxml import etree
import time
import hashlib
import re

# Configuration
HEADERS = {'authorization': 'token ' + os.environ['ACCESS_TOKEN']}
USER_NAME = os.environ['USER_NAME']
QUERY_COUNT = {'user_getter': 0, 'follower_getter': 0, 'graph_repos_stars': 0, 'recursive_loc': 0, 'graph_commits': 0,
               'loc_query': 0}
EXCLUDED_REPOS = {'is-a-dev/register', 'shivamnsingh/register', 'is-a-good-dev/register', 'shivamnsingh/register-is-a-good-dev'}


def daily_readme(birthday):
    diff = relativedelta.relativedelta(datetime.datetime.today(), birthday)
    return '{} {}, {} {}, {} {}{}'.format(
        diff.years, 'year' + format_plural(diff.years),
        diff.months, 'month' + format_plural(diff.months),
        diff.days, 'day' + format_plural(diff.days),
        ' 🎂' if (diff.months == 0 and diff.days == 0) else '')


def format_plural(unit):
    return 's' if unit != 1 else ''


def simple_request(func_name, query, variables):
    request = requests.post('https://api.github.com/graphql', json={'query': query, 'variables': variables},
                            headers=HEADERS)
    if request.status_code == 200:
        return request
    raise Exception(func_name, ' has failed with a', request.status_code, request.text, QUERY_COUNT)


SPARK = ' ▁▂▃▄▅▆▇█'


def uptime_text(created_at):
    """Account age, e.g. '2 years, 26 days' (zero parts are dropped)."""
    created = datetime.datetime.strptime(created_at, '%Y-%m-%dT%H:%M:%SZ')
    diff = relativedelta.relativedelta(datetime.datetime.utcnow(), created)
    parts = []
    for value, unit in ((diff.years, 'year'), (diff.months, 'month'), (diff.days, 'day')):
        if value:
            parts.append('{} {}{}'.format(value, unit, format_plural(value)))
    return ', '.join(parts) if parts else '0 days'


def contribution_calendar():
    """Last-12-months contribution total and the calendar as a list of weeks (each a list of days)."""
    query_count('graph_commits')
    query = '''
    query($login: String!) {
        user(login: $login) {
            contributionsCollection {
                contributionCalendar {
                    totalContributions
                    weeks { contributionDays { date contributionCount } }
                }
            }
        }
    }'''
    request = simple_request('contribution_calendar', query, {'login': USER_NAME})
    cal = request.json()['data']['user']['contributionsCollection']['contributionCalendar']
    return int(cal['totalContributions']), [w['contributionDays'] for w in cal['weeks']]


def streak_stats(weeks):
    """(current streak, best streak within the calendar window), computed from real contribution days."""
    days = sorted((d for w in weeks for d in w), key=lambda d: d['date'])
    counts = [d['contributionCount'] for d in days]
    best = run = 0
    for c in counts:
        run = run + 1 if c > 0 else 0
        best = max(best, run)
    current, i = 0, len(counts) - 1
    if i >= 0 and counts[i] == 0:  # today may simply not have a contribution yet
        i -= 1
    while i >= 0 and counts[i] > 0:
        current += 1
        i -= 1
    return current, best


def sparkline(weeks):
    totals = [sum(d['contributionCount'] for d in w) for w in weeks]
    peak = max(totals) if totals and max(totals) > 0 else 1
    return ''.join(SPARK[0] if t == 0 else SPARK[max(1, -(-t * 8 // peak))] for t in totals)


def pull_requests():
    query_count('graph_repos_stars')
    query = 'query($login: String!){ user(login: $login) { pullRequests { totalCount } } }'
    request = simple_request('pull_requests', query, {'login': USER_NAME})
    return int(request.json()['data']['user']['pullRequests']['totalCount'])


def repo_stats():
    """Stars received and language bytes across owned, non-fork repos."""
    query = '''
    query($login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER], isFork: false) {
                nodes {
                    nameWithOwner
                    stargazerCount
                    languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
                        edges { size node { name } }
                    }
                }
                pageInfo { endCursor hasNextPage }
            }
        }
    }'''
    stars, langs, cursor = 0, {}, None
    while True:
        query_count('graph_repos_stars')
        request = simple_request('repo_stats', query, {'login': USER_NAME, 'cursor': cursor})
        repos = request.json()['data']['user']['repositories']
        for node in repos['nodes']:
            if not node or node['nameWithOwner'] in EXCLUDED_REPOS:
                continue
            stars += node['stargazerCount']
            for edge in node['languages']['edges']:
                langs[edge['node']['name']] = langs.get(edge['node']['name'], 0) + edge['size']
        if not repos['pageInfo']['hasNextPage']:
            return stars, langs
        cursor = repos['pageInfo']['endCursor']


def languages_text(langs, max_len=41):
    total = sum(langs.values()) or 1
    out = ''
    for name, size in sorted(langs.items(), key=lambda kv: kv[1], reverse=True):
        pct = round(size * 100 / total)
        if pct < 1:
            break
        item = '{} {}%'.format(name, pct)
        candidate = out + (', ' if out else '') + item
        if len(candidate) > max_len:
            break
        out = candidate
    return out or 'n/a'


def graph_commits():
    query_count('graph_commits')
    query = '''
    query($login: String!) {
        user(login: $login) {
            contributionsCollection {
                contributionCalendar {
                    totalContributions
                }
            }
        }
    }'''
    variables = {'login': USER_NAME}
    request = simple_request(graph_commits.__name__, query, variables)
    data = request.json()['data']['user']['contributionsCollection']
    return int(data['contributionCalendar']['totalContributions'])


def graph_repos_stars(count_type, owner_affiliation, cursor=None):
    query_count('graph_repos_stars')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                totalCount
                edges {
                    node {
                        ... on Repository {
                            nameWithOwner
                            stargazers {
                                totalCount
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    request = simple_request(graph_repos_stars.__name__, query, variables)
    if request.status_code == 200:
        if count_type == 'repos':
            return request.json()['data']['user']['repositories']['totalCount']
        elif count_type == 'stars':
            return stars_counter(request.json()['data']['user']['repositories']['edges'])


def recursive_loc(owner, repo_name, data, cache_comment, addition_total=0, deletion_total=0, my_commits=0, cursor=None):
    global OWNER_ID
    query = '''
    query ($repo_name: String!, $owner: String!, $cursor: String) {
        repository(name: $repo_name, owner: $owner) {
            defaultBranchRef {
                target {
                    ... on Commit {
                        history(first: 100, after: $cursor) {
                            totalCount
                            edges {
                                node {
                                    ... on Commit {
                                        committedDate
                                    }
                                    author {
                                        user {
                                            id
                                        }
                                    }
                                    deletions
                                    additions
                                }
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
        }
    }'''
    while True:
        query_count('recursive_loc')
        variables = {'repo_name': repo_name, 'owner': owner, 'cursor': cursor}
        request = requests.post('https://api.github.com/graphql', json={'query': query, 'variables': variables},
                                headers=HEADERS)
        if request.status_code != 200:
            force_close_file(data, cache_comment)
            if request.status_code == 403:
                raise Exception(
                    'Too many requests in a short amount of time!\nYou\'ve hit the non-documented anti-abuse limit!')
            raise Exception('recursive_loc() has failed with a', request.status_code, request.text, QUERY_COUNT)

        if request.json()['data']['repository']['defaultBranchRef'] is None:
            return 0

        history = request.json()['data']['repository']['defaultBranchRef']['target']['history']
        for node in history['edges']:
            if node['node']['author']['user'] and node['node']['author']['user']['id'] == OWNER_ID:
                my_commits += 1
                addition_total += node['node']['additions']
                deletion_total += node['node']['deletions']

        if not history['edges'] or not history['pageInfo']['hasNextPage']:
            return addition_total, deletion_total, my_commits
        cursor = history['pageInfo']['endCursor']


def loc_query(owner_affiliation, comment_size=0, force_cache=False, cursor=None, edges=None):
    if edges is None:
        edges = []
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 60, after: $cursor, ownerAffiliations: $owner_affiliation) {
            edges {
                node {
                    ... on Repository {
                        nameWithOwner
                        defaultBranchRef {
                            target {
                                ... on Commit {
                                    history {
                                        totalCount
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    while True:
        query_count('loc_query')
        variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
        request = simple_request(loc_query.__name__, query, variables)
        repo_data = request.json()['data']['user']['repositories']
        edges += [e for e in repo_data['edges']
                  if e and e.get('node') and e['node']['nameWithOwner'] not in EXCLUDED_REPOS]
        if not repo_data['pageInfo']['hasNextPage']:
            return cache_builder(edges, comment_size, force_cache)
        cursor = repo_data['pageInfo']['endCursor']


def cache_builder(edges, comment_size, force_cache, loc_add=0, loc_del=0):
    edges = [e for e in edges if e is not None and e.get('node') is not None
             and e['node']['nameWithOwner'] not in EXCLUDED_REPOS]
    print(edges)
    filename = 'cache/' + hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest() + '.txt'

    if not os.path.exists('cache'):
        os.makedirs('cache')

    try:
        with open(filename, 'r') as f:
            data = f.readlines()
    except FileNotFoundError:
        data = []
        if comment_size > 0:
            for _ in range(comment_size): data.append('This line is a comment block.\n')
        with open(filename, 'w') as f:
            f.writelines(data)

    if len(data) - comment_size != len(edges) or force_cache:
        flush_cache(edges, filename, comment_size)
        with open(filename, 'r') as f:
            data = f.readlines()

    cache_comment = data[:comment_size]
    data = data[comment_size:]

    for index in range(len(edges)):
        line_parts = data[index].split()
        repo_hash = line_parts[0]
        commit_count = line_parts[1]

        if repo_hash == hashlib.sha256(edges[index]['node']['nameWithOwner'].encode('utf-8')).hexdigest():
            try:
                hist = edges[index]['node']['defaultBranchRef']['target']['history']
                if int(commit_count) != hist['totalCount']:
                    owner, repo_name = edges[index]['node']['nameWithOwner'].split('/')
                    loc = recursive_loc(owner, repo_name, data, cache_comment)
                    data[index] = f"{repo_hash} {hist['totalCount']} {loc[2]} {loc[0]} {loc[1]}\n"
            except (TypeError, AttributeError):
                data[index] = repo_hash + ' 0 0 0 0\n'

    with open(filename, 'w') as f:
        f.writelines(cache_comment)
        f.writelines(data)

    my_commits = 0
    for line in data:
        loc = line.split()
        my_commits += int(loc[2])
        loc_add += int(loc[3])
        loc_del += int(loc[4])
    return [loc_add, loc_del, loc_add - loc_del, True, my_commits]


def flush_cache(edges, filename, comment_size):
    with open(filename, 'r') as f:
        data = []
        lines = f.readlines()
        if len(lines) >= comment_size:
            data = lines[:comment_size]
    with open(filename, 'w') as f:
        f.writelines(data)
        for node in edges:
            if node.get('node') and node['node'].get('nameWithOwner'):
                f.write(hashlib.sha256(node['node']['nameWithOwner'].encode('utf-8')).hexdigest() + ' 0 0 0 0\n')


def force_close_file(data, cache_comment):
    filename = 'cache/' + hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest() + '.txt'
    with open(filename, 'w') as f:
        f.writelines(cache_comment)
        f.writelines(data)


def stars_counter(data):
    total_stars = 0
    for node in data: total_stars += node['node']['stargazers']['totalCount']
    return total_stars


# id -> (length of the ". Label: " prefix, row width in characters). Must match the card template.
ROW_SPECS = {
    'uptime_data': (len('. Uptime: '), 58),
    'repos_data': (len('. Repos: '), 27),
    'stars_data': (len('. Stars: '), 27),
    'commits_data': (len('. Commits: '), 27),
    'prs_data': (len('. PRs: '), 27),
    'contribs_data': (len('. Contributions: '), 27),
    'followers_data': (len('. Followers: '), 27),
    'streak_data': (len('. Streak: '), 58),
    'langs_data': (len('. Languages: '), 58),
}


def svg_overwrite(filename, values):
    tree = etree.parse(filename)
    root = tree.getroot()
    for element_id, (lead, width) in ROW_SPECS.items():
        value = values[element_id]
        text = '{:,}'.format(value) if isinstance(value, int) else str(value)
        text = text[:max(1, width - lead - 3)]
        find_and_replace(root, element_id, ' ' + text)
        find_and_replace(root, element_id + '_dots', '.' * max(2, width - lead - len(text) - 1))
    find_and_replace(root, 'spark_data', values['spark_data'])
    tree.write(filename, encoding='utf-8', xml_declaration=True)


def _mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return '#%02x%02x%02x' % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def render_gif(svg_file, gif_file, base, glow, frames=30):
    """Animated copy of the card: a thin scan line sweeps over the ASCII portrait, then it pauses and loops."""
    import io
    import shutil
    import subprocess
    from PIL import Image
    if shutil.which('rsvg-convert') is None:
        print('rsvg-convert not found, skipping', gif_file)
        return False
    ns = '{http://www.w3.org/2000/svg}'

    def frame(scan):
        root = etree.parse(svg_file).getroot()
        if scan is not None:
            for t in root.iter(ns + 'text'):
                if t.get('class') == 'art':
                    d = abs(float(t.get('y')) - scan)
                    t.set('fill', _mix(base, glow, (1 - d / 30) ** 1.5) if d < 30 else base)
            etree.SubElement(root, ns + 'rect', x='24', y='%.1f' % (scan - 4), width='330', height='1.2',
                             fill=glow, opacity='0.55')
        png = subprocess.run(['rsvg-convert', '-w', '966', '-h', '603', '-f', 'png'],
                             input=etree.tostring(root), stdout=subprocess.PIPE, check=True).stdout
        return Image.open(io.BytesIO(png)).convert('RGB')

    scans = [24 + i * (590 - 24) / (frames - 1) for i in range(frames)]
    imgs = [frame(y) for y in scans]
    still = frame(None)
    sample = Image.new('RGB', (966, 603 * 4))
    for k, idx in enumerate([0, frames // 3, 2 * frames // 3, frames - 1]):
        sample.paste(imgs[idx], (0, 603 * k))
    palette = sample.quantize(colors=64, method=0, dither=0)  # 0 = median cut, no dithering
    seq = [im.quantize(palette=palette, dither=0) for im in imgs + [still]]
    seq[0].save(gif_file, save_all=True, append_images=seq[1:], duration=[55] * frames + [2200], loop=0,
                optimize=True, disposal=1)
    return True


def find_and_replace(root, element_id, new_text):
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = new_text


def user_getter(username):
    query_count('user_getter')
    query = 'query($login: String!){ user(login: $login) { id createdAt } }'
    variables = {'login': username}
    request = simple_request(user_getter.__name__, query, variables)
    return request.json()['data']['user']['id'], request.json()['data']['user']['createdAt']


def follower_getter(username):
    query_count('follower_getter')
    query = 'query($login: String!){ user(login: $login) { followers { totalCount } } }'
    request = simple_request(follower_getter.__name__, query, {'login': username})
    return int(request.json()['data']['user']['followers']['totalCount'])


def query_count(funct_id):
    global QUERY_COUNT
    QUERY_COUNT[funct_id] += 1


def perf_counter(funct, *args):
    start = time.perf_counter()
    funct_return = funct(*args)
    return funct_return, time.perf_counter() - start


def formatter(query_type, difference):
    print('{:<23}'.format('   ' + query_type + ':'), sep='', end='')
    if difference > 1:
        print('{:>12}'.format('%.4f' % difference + ' s '))
    else:
        print('{:>12}'.format('%.4f' % (difference * 1000) + ' ms'))


if __name__ == '__main__':
    print('Starting stats update...')
    OWNER_ID, acc_date = user_getter(USER_NAME)
    formatter('account data', 0)

    age_data, age_time = perf_counter(uptime_text, acc_date)
    formatter('account age', age_time)

    total_loc, loc_time = perf_counter(loc_query, ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'], 7)
    formatter('commits (cached)', loc_time)

    (contrib_total, weeks), _ = perf_counter(contribution_calendar)
    streak_now, streak_best = streak_stats(weeks)
    repo_data, _ = perf_counter(graph_repos_stars, 'repos', ['OWNER'])
    (star_data, lang_data), _ = perf_counter(repo_stats)
    pr_data, _ = perf_counter(pull_requests)
    follower_data, _ = perf_counter(follower_getter, USER_NAME)

    values = {
        'uptime_data': age_data,
        'repos_data': repo_data,
        'stars_data': star_data,
        # +2: commits in excluded repos that are too large to parse
        'commits_data': total_loc[4] + 2,
        'prs_data': pr_data,
        'contribs_data': contrib_total,
        'followers_data': follower_data,
        'streak_data': '{} day{} (best {})'.format(streak_now, format_plural(streak_now), streak_best),
        'langs_data': languages_text(lang_data),
        'spark_data': sparkline(weeks),
    }
    for theme in ('dark', 'light'):
        svg_overwrite(theme + '_mode.svg', values)
    # Scan-line colors: base portrait color, highlight color
    render_gif('dark_mode.svg', 'dark_mode.gif', '#c9d1d9', '#7ee787')
    render_gif('light_mode.svg', 'light_mode.gif', '#57606a', '#1a7f37')

    print('Total GitHub GraphQL API calls:', sum(QUERY_COUNT.values()))
