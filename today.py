"""
today.py — builds the neofetch-style profile card (dark_mode.svg + light_mode.svg)
for github.com/mahessarsajjad.

Runs daily in GitHub Actions. It pulls live stats from the GitHub API using the
ACCESS_TOKEN secret, then redraws both SVGs from scratch. The README shows
whichever SVG matches the visitor's light/dark theme.

Run locally:  ACCESS_TOKEN=xxx python today.py
Offline test: python today.py --offline   (stats drawn as 0, no API calls)
"""

import datetime as dt
import html
import os
import sys
import time

import requests

USER = "mahessarsajjad"
CAREER_START = dt.date(2021, 1, 1)  # "Uptime" counts from first analytics role
WIDTH = 58                          # characters per line on the right-hand side

# ── Card content ────────────────────────────────────────────────────────────
# Each entry is (key, value). "." draws a blank spacer line,
# ("#", "Title") draws a section header.
PROFILE = [
    ("OS", "macOS, iOS, Android, Linux"),
    ("Uptime", "__UPTIME__"),
    ("Host", "Good Merch Group"),
    ("Kernel", "Operations & Automation Manager"),
    ("Freelance", "Systems Developer"),
    ("IDE", "Xcode, VS Code, Claude Code"),
    ".",
    ("Languages.Programming", "Python, Swift, JavaScript, SQL"),
    ("Languages.Computer", "HTML, CSS, JSON, YAML"),
    ".",
    ("Stack.Backend", "Supabase, PostgreSQL, Node.js"),
    ("Stack.Payments", "Stripe"),
    ("Stack.Data", "Python, Power BI, Grafana"),
    ("Stack.AI", "LLM agents, automation"),
    ".",
    ("Education", "MSc Business Analytics, Warwick"),
    ("Hobbies.Build", "replacing rented software"),
    ("#", "Contact"),
    ("Email", "mahessarsajjad@gmail.com"),
    ("LinkedIn", "linkedin.com/in/sajjadmahessar"),
    ("Website", "sajjad.omni-genai.com"),
    ("#", "GitHub Stats"),
]

THEMES = {
    "dark_mode.svg": dict(bg="#161b22", text="#c9d1d9", key="#ffa657", value="#a5d6ff",
                          dots="#616e7f", add="#3fb950", dele="#f85149", art="#c9d1d9"),
    "light_mode.svg": dict(bg="#f6f8fa", text="#24292f", key="#953800", value="#0a3069",
                           dots="#c2cfde", add="#1a7f37", dele="#cf222e", art="#24292f"),
}


# ── GitHub API ──────────────────────────────────────────────────────────────
def gql(token, query, variables=None):
    r = requests.post("https://api.github.com/graphql",
                      json={"query": query, "variables": variables or {}},
                      headers={"Authorization": f"bearer {token}"}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def fetch_stats(token):
    base = gql(token, """
    query($login:String!){ user(login:$login){
      createdAt
      followers{ totalCount }
      repositoriesContributedTo(includeUserRepositories:true,
        contributionTypes:[COMMIT,PULL_REQUEST,REPOSITORY]){ totalCount }
    }}""", {"login": USER})["user"]

    # Owned repos (public + private, as far as the token can see) and stars
    repos, cursor = [], None
    while True:
        page = gql(token, """
        query($login:String!,$cursor:String){ user(login:$login){
          repositories(first:100, after:$cursor, ownerAffiliations:OWNER){
            pageInfo{ hasNextPage endCursor }
            nodes{ name isFork stargazerCount }
        }}}""", {"login": USER, "cursor": cursor})["user"]["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    # Commits: one contributionsCollection per year since the account opened
    commits = 0
    year = int(base["createdAt"][:4])
    now = dt.datetime.utcnow()
    while year <= now.year:
        frm = f"{year}-01-01T00:00:00Z"
        to = f"{year}-12-31T23:59:59Z" if year < now.year else now.strftime("%Y-%m-%dT%H:%M:%SZ")
        c = gql(token, """
        query($login:String!,$from:DateTime!,$to:DateTime!){ user(login:$login){
          contributionsCollection(from:$from,to:$to){
            totalCommitContributions restrictedContributionsCount }}}""",
                {"login": USER, "from": frm, "to": to})["user"]["contributionsCollection"]
        commits += c["totalCommitContributions"] + c["restrictedContributionsCount"]
        year += 1

    # Lines of code: additions / deletions authored by USER across owned repos
    added = deleted = 0
    headers = {"Authorization": f"bearer {token}", "Accept": "application/vnd.github+json"}
    for repo in repos:
        if repo["isFork"]:
            continue
        url = f"https://api.github.com/repos/{USER}/{repo['name']}/stats/contributors"
        for _ in range(6):  # GitHub returns 202 while it computes the stats
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code != 202:
                break
            time.sleep(4)
        if r.status_code != 200 or not isinstance(r.json(), list):
            continue
        for person in r.json():
            if (person.get("author") or {}).get("login", "").lower() == USER.lower():
                added += sum(w["a"] for w in person["weeks"])
                deleted += sum(w["d"] for w in person["weeks"])

    return dict(
        repos=len(repos),
        contributed=base["repositoriesContributedTo"]["totalCount"],
        stars=sum(r["stargazerCount"] for r in repos),
        commits=commits,
        followers=base["followers"]["totalCount"],
        loc=added - deleted, added=added, deleted=deleted,
    )


# ── Helpers ─────────────────────────────────────────────────────────────────
def uptime(start, today):
    years = today.year - start.year
    months = today.month - start.month
    days = today.day - start.day
    if days < 0:
        months -= 1
        prev_month_end = today.replace(day=1) - dt.timedelta(days=1)
        days += prev_month_end.day
    if months < 0:
        years -= 1
        months += 12

    def p(n, word):
        return f"{n} {word}{'' if n == 1 else 's'}"
    return f"{p(years, 'year')}, {p(months, 'month')}, {p(days, 'day')}"


def esc(s):
    return html.escape(s, quote=False)


def kv_line(key, value, width=WIDTH):
    """'Key: ....... value' padded with dots to exactly `width` characters."""
    dots = width - len(key) - len(value) - 3
    dots = max(dots, 1)
    return [(f"{key}", "key"), (": ", "text"), ("." * dots + " ", "dots"), (value, "value")]


def header_line(title, width=WIDTH):
    left = f"- {title} "
    return [(left, "text"), ("-" * (width - len(left)), "dots")]


def stats_lines(s):
    f = lambda n: f"{n:,}"
    left_w = 31

    def pair(k1, v1, k2, v2):
        a = kv_line(k1, v1, left_w)
        b = kv_line(k2, v2, WIDTH - left_w - 3)
        return a + [(" | ", "text")] + b

    repos_val = f"{f(s['repos'])} {{Contributed: {f(s['contributed'])}}}"
    loc_tail = [(f"{f(s['loc'])}", "value"), (" ( ", "text"),
                (f"{f(s['added'])}++", "add"), (", ", "text"),
                (f"{f(s['deleted'])}--", "dele"), (" )", "text")]
    tail_len = sum(len(t) for t, _ in loc_tail)
    lead = "Lines of Code"
    dots = max(WIDTH - len(lead) - 3 - tail_len, 1)
    loc = [(lead, "key"), (": ", "text"), ("." * dots + " ", "dots")] + loc_tail

    return [
        pair("Repos", repos_val, "Stars", f(s["stars"])),
        pair("Commits", f(s["commits"]), "Followers", f(s["followers"])),
        loc,
    ]


# ── SVG ─────────────────────────────────────────────────────────────────────
def build_lines(stats, today):
    lines = [[(f"{USER}@github ", "text"), ("-" * (WIDTH - len(USER) - 8), "dots")]]
    for item in PROFILE:
        if item == ".":
            lines.append([(".", "dots")])
        elif item[0] == "#":
            lines.append(header_line(item[1]))
        else:
            k, v = item
            if v == "__UPTIME__":
                v = uptime(CAREER_START, today)
            lines.append(kv_line(k, v))
    lines += stats_lines(stats)
    return lines


def render(theme, lines, art_lines):
    t = THEMES[theme]
    line_h, art_h = 20, 12.6
    top = 32
    height = top + len(lines) * line_h + 18
    art_block = len(art_lines) * art_h
    art_top = (height - art_block) / 2 + 10
    width = 1030
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,Menlo,DejaVu Sans Mono,monospace" '
        f'width="{width}px" height="{height}px" font-size="15px">',
        "<style>",
        "@font-face{src:local('Consolas'),local('Consolas Bold');font-family:'ConsolasFallback';"
        "font-display:swap;-webkit-size-adjust:109%;size-adjust:109%;}",
        f".key{{fill:{t['key']};}} .value{{fill:{t['value']};}} .dots{{fill:{t['dots']};}} "
        f".add{{fill:{t['add']};}} .dele{{fill:{t['dele']};}} .text{{fill:{t['text']};}}",
        "text,tspan{white-space:pre;}",
        "</style>",
        f'<rect width="{width}px" height="{height}px" fill="{t["bg"]}" rx="15"/>',
        f'<text xml:space="preserve" x="18" y="{art_top:.0f}" fill="{t["art"]}" font-size="10.5px">',
    ]
    for i, row in enumerate(art_lines):
        dy = "0" if i == 0 else f"{art_h}"
        out.append(f'<tspan x="18" dy="{dy}">{esc(row)}</tspan>')
    out.append("</text>")
    out.append(f'<text xml:space="preserve" x="470" y="{top}" class="text">')
    for i, segs in enumerate(lines):
        dy = "0" if i == 0 else f"{line_h}"
        inner = "".join(f'<tspan class="{c}">{esc(s)}</tspan>' for s, c in segs)
        out.append(f'<tspan x="470" dy="{dy}">{inner}</tspan>')
    out.append("</text>")
    out.append("</svg>")
    return "\n".join(out)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    offline = "--offline" in sys.argv
    if offline:
        stats = dict(repos=0, contributed=0, stars=0, commits=0, followers=0,
                     loc=0, added=0, deleted=0)
    else:
        token = os.environ.get("ACCESS_TOKEN")
        if not token:
            sys.exit("ACCESS_TOKEN is not set")
        stats = fetch_stats(token)

    with open(os.path.join(here, "ascii.txt"), encoding="utf-8") as fh:
        art_lines = [ln.rstrip("\n") for ln in fh if ln.strip()]

    lines = build_lines(stats, dt.date.today())
    for name in THEMES:
        with open(os.path.join(here, name), "w", encoding="utf-8") as fh:
            fh.write(render(name, lines, art_lines))
    print("Updated:", stats)


if __name__ == "__main__":
    main()
