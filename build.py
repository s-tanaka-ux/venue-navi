#!/usr/bin/env python3
"""会場サイトの自動ビルド(標準ライブラリのみ・追加インストール不要)
 1) OpenStreetMap(Overpass API)から会場データを取得(週1回)
 2) 新しい会場の紹介文をClaudeで下書き(APIキーがある場合のみ・1回の上限あり)
 3) dist/ に静的HTMLを生成
使い方: python build.py [--fetch] [--no-fetch]
"""
import html, json, os, pathlib, sys, time, urllib.parse, urllib.request, datetime

ROOT = pathlib.Path(__file__).parent
DATA, DIST = ROOT / "data", ROOT / "dist"
CFG = json.loads((ROOT / "config.json").read_text("utf-8"))
VENUES_F, DESC_F = DATA / "venues.json", DATA / "descriptions.json"

PREFS = ["北海道","青森県","岩手県","宮城県","秋田県","山形県","福島県","茨城県","栃木県","群馬県","埼玉県","千葉県","東京都","神奈川県","新潟県","富山県","石川県","福井県","山梨県","長野県","岐阜県","静岡県","愛知県","三重県","滋賀県","京都府","大阪府","兵庫県","奈良県","和歌山県","鳥取県","島根県","岡山県","広島県","山口県","徳島県","香川県","愛媛県","高知県","福岡県","佐賀県","長崎県","熊本県","大分県","宮崎県","鹿児島県","沖縄県"]
REG = [("北海道",[1]),("東北",range(2,8)),("関東",range(8,15)),("中部",range(15,24)),("近畿",range(24,31)),("中国",range(31,36)),("四国",range(36,40)),("九州・沖縄",range(40,48))]
KINDS = {"music_venue": "ライブハウス・音楽会場", "theatre": "劇場・ホール", "stadium": "スタジアム・アリーナ"}


def esc(s):
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------- 1) 取得
URLS = CFG.get("overpass_urls") or [
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.osm.jp/api/interpreter",
]


def overpass(q):
    last = None
    for attempt in range(2):
        for u in URLS:
            try:
                req = urllib.request.Request(u, data=urllib.parse.urlencode({"data": q}).encode(),
                                             headers={"User-Agent": CFG["user_agent"]})
                with urllib.request.urlopen(req, timeout=CFG.get("request_timeout", 150)) as r:
                    return json.load(r)
            except Exception as e:
                last = e
                print(f"  失敗({u.split('/')[2]}): {e}", flush=True)
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(last)


def parse(el, pref):
    t = el.get("tags", {})
    kind = "music_venue" if t.get("amenity") == "music_venue" else "theatre" if t.get("amenity") == "theatre" else "stadium"
    c = el.get("center") or el
    if "lat" not in c:
        return None
    addr = t.get("addr:full") or "".join(t.get(k, "") for k in
        ("addr:city", "addr:suburb", "addr:quarter", "addr:neighbourhood", "addr:block_number", "addr:housenumber"))
    return {"id": el["type"][0] + str(el["id"]), "name": t["name"], "kind": kind, "pref": pref,
            "lat": round(c["lat"], 5), "lon": round(c["lon"], 5), "addr": addr,
            "website": t.get("website", t.get("contact:website", "")), "capacity": t.get("capacity", "")}


def priority_codes():
    """config.json の "priority"(地方名または都道府県名のリスト)を県コードに変換。未設定なら関東を優先。"""
    out = set()
    for name in CFG.get("priority", ["関東"]):
        for rn, codes in REG:
            if name == rn:
                out |= set(codes)
        if name in PREFS:
            out.add(PREFS.index(name) + 1)
    return out


def load_data():
    if VENUES_F.exists():
        d = json.loads(VENUES_F.read_text("utf-8"))
        d.setdefault("done", {})
        d.setdefault("tried", {})
        return d
    return {"venues": [], "done": {}, "tried": {}}


def stale_prefs(d):
    """更新が必要な県(古い順)。未取得は最優先。"""
    now, days = time.time(), CFG["refetch_days"]
    if "--fetch" in sys.argv:
        d["done"] = {}
    pri = priority_codes()
    return sorted((c for c in range(1, 48) if now - d["done"].get(str(c), 0) > days * 86400),
                  key=lambda c: (c not in pri, d.get("tried", {}).get(str(c), 0), d["done"].get(str(c), 0)))


def fetch_some(d):
    """時間の上限内で、取れた県から順に保存する。残りは次回の実行に持ち越し。"""
    by = {}
    for v in d["venues"]:
        by.setdefault(v["pref"], []).append(v)
    deadline = time.time() + CFG.get("fetch_budget_minutes", 40) * 60
    fails = 0
    for c in stale_prefs(d):
        if time.time() > deadline:
            print("取得の時間上限に達したため中断します。残りは次回の実行で続けます", flush=True)
            break
        if fails >= 3:
            print("3回連続で失敗したため中断します。残りは次回の実行で続けます", flush=True)
            break
        q = (f'[out:json][timeout:120];area["ISO3166-2"="JP-{c:02d}"]->.a;'
             '(nwr(area.a)["amenity"="music_venue"]["name"];nwr(area.a)["amenity"="theatre"]["name"];'
             'nwr(area.a)["leisure"="stadium"]["name"];);out center tags;')
        print(f"取得中 {PREFS[c-1]}", flush=True)
        d.setdefault("tried", {})[str(c)] = time.time()
        try:
            by[c] = [p for p in (parse(e, c) for e in overpass(q).get("elements", [])) if p]
            d["done"][str(c)] = time.time()
            fails = 0
            print(f"  {len(by[c])} 件", flush=True)
        except Exception as e:
            fails += 1
            print("  この県はスキップ(前回データを残します):", e, flush=True)
        d["venues"] = [v for k in sorted(by) for v in by[k]]
        VENUES_F.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
        time.sleep(20)
    print(f"取得済みの県: {len(d['done'])}/47", flush=True)


# ---------------------------------------------------------------- 2) 紹介文
def ask(prompt):
    body = json.dumps({"model": CFG["model"], "max_tokens": 500, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return "".join(b.get("text", "") for b in json.load(r)["content"]).strip()


def describe(venues):
    desc = json.loads(DESC_F.read_text("utf-8")) if DESC_F.exists() else {}
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY 未設定のため、紹介文の下書きはスキップします")
        return desc
    todo = [v for v in venues if v["id"] not in desc]
    pri = priority_codes()
    todo.sort(key=lambda v: (v["pref"] not in pri, -(bool(v["capacity"]) + bool(v["website"]) + bool(v["addr"]))))
    for v in todo[: CFG["max_new_descriptions"]]:
        facts = f"会場名:{v['name']}\n種類:{KINDS[v['kind']]}\n所在地:{PREFS[v['pref']-1]}{v['addr']}"
        if v["capacity"]:
            facts += f"\n収容人数:{v['capacity']}"
        p = ("次の事実だけを使って、ライブ・コンサート会場の紹介文を日本語で100〜180字で書いてください。\n"
             "ルール: 与えられていない情報(設備、歴史、座席数、最寄り駅、過去の公演、評判など)は絶対に書かない。"
             "宣伝調や断定的な褒め言葉は使わない。会場名と種類と所在地を自然に盛り込み、出力は本文のみ。\n\n" + facts)
        try:
            desc[v["id"]] = {"text": ask(p), "reviewed": False}
            print("下書き:", v["name"])
        except Exception as e:
            print("下書き失敗:", v["name"], e)
        time.sleep(1)
    DESC_F.write_text(json.dumps(desc, ensure_ascii=False, indent=1), "utf-8")
    return desc


# ---------------------------------------------------------------- 3) 生成
CSS = """:root{--h:62,48,140;--bg:#f4f3fa;--s:#fff;--ink:#222036;--sub:#645f85;--line:#dedbee;--ab:#ebe9f6;--ac:#e0457b;--r1:#2a7fc1;--r2:#d6532f;--r3:#2f9a63;--r4:#a0449c;--r5:#c58a12;--r6:#17908f;--r7:#c4374f}
@media(prefers-color-scheme:dark){:root{--h:150,138,235;--bg:#15132b;--s:#1f1c3d;--ink:#ecebf8;--sub:#a9a5cc;--line:#332f5f;--ab:#272447;--ac:#ff6fa0;--r1:#6bb4ee;--r2:#f2896a;--r3:#6cc896;--r4:#d589d1;--r5:#e6b85a;--r6:#5cc7c5;--r7:#f27a8e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:"Hiragino Sans","Yu Gothic",Meiryo,sans-serif;line-height:1.75}
a{color:inherit}a:focus-visible,input:focus-visible{outline:3px solid var(--ac);outline-offset:2px}
header{background:rgb(62,48,140);color:#fff;padding:8px 14px}@media(prefers-color-scheme:dark){header,footer{background:#241e57}}
.hb{max-width:1000px;margin:auto;display:flex;gap:14px;align-items:center;flex-wrap:wrap}.logo{font-weight:900;font-size:1.3rem;text-decoration:none}
.sw{position:relative;margin-left:auto}.sw input{padding:8px 12px;border:0;border-radius:8px;width:220px;font:inherit;font-size:.9rem}
#sr{position:absolute;right:0;top:100%;margin:4px 0 0;padding:0;list-style:none;background:var(--s);color:var(--ink);border-radius:8px;box-shadow:0 6px 20px rgba(0,0,0,.25);width:min(340px,90vw);z-index:9}
#sr a{display:flex;justify-content:space-between;gap:8px;padding:8px 12px;text-decoration:none;font-size:.9rem}#sr a:hover{background:var(--bg)}#sr span,.none{color:var(--sub);font-size:.8rem;padding:8px 12px}
main{max-width:1000px;margin:auto;padding:0 14px}.top{text-align:center;padding:34px 0 6px}.top h1{margin:0 0 14px;font-size:clamp(2rem,7vw,3rem);color:rgb(var(--h));letter-spacing:.06em}
.top p{margin:0;color:var(--sub)}.num{font-size:2rem;font-weight:900;color:rgb(var(--h))}
h2{font-size:1.15rem;margin:26px 0 12px;padding-left:10px;border-left:5px solid rgb(var(--h))}
.pg{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}.pg a{min-width:84px;text-align:center;padding:7px 10px;border:2px solid var(--c);color:var(--c);background:var(--s);border-radius:8px;text-decoration:none;font-size:.9rem}
.pg a:hover,.pg a.rg{background:var(--c);color:var(--s)}.pg i{display:block;font-style:normal;font-size:.75rem}
.list{list-style:none;padding:0;margin:0}.list li{background:var(--s);border:1px solid var(--line);border-radius:8px;margin-bottom:6px}.list a{display:block;padding:10px 14px;text-decoration:none}.list a:hover{border-color:var(--ac)}.list small{color:var(--sub);display:block}
.card{background:var(--s);border:1px solid var(--line);border-radius:10px;padding:16px 18px}.tag{display:inline-block;padding:1px 10px;border-radius:4px;background:rgb(var(--h));color:var(--s);font-size:.78rem}
table{border-collapse:collapse;width:100%;margin-top:12px}th,td{text-align:left;padding:8px 6px;border-top:1px solid var(--line);font-size:.92rem;vertical-align:top}th{width:7em;color:var(--sub);font-weight:500}
.bc{font-size:.82rem;color:var(--sub);margin:18px 0 0}.adw{margin:26px 0;min-height:90px}.ph{background:var(--ab);border:1px dashed var(--line);border-radius:6px;color:var(--sub);font-size:.76rem;text-align:center;padding:12px}.ph small{display:block}
.note{font-size:.8rem;color:var(--sub)}footer{background:rgb(62,48,140);color:#e6e3f8;margin-top:36px;padding:22px 14px;font-size:.82rem}footer div{max-width:1000px;margin:auto}footer a{margin-right:14px}"""

JS = """(function(){var i=document.getElementById('sk'),l=document.getElementById('sr'),d=null,r=document.documentElement.dataset.root||'';
function e(s){return s.replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function L(f){if(d)return f();fetch(r+'search.json').then(function(x){return x.json()}).then(function(j){d=j;f()}).catch(function(){})}
i.addEventListener('input',function(){var k=i.value.trim().toLowerCase();if(!k){l.innerHTML='';return}L(function(){var o=[];for(var x=0;x<d.length&&o.length<10;x++)if(d[x][0].toLowerCase().indexOf(k)>-1)o.push(d[x]);
l.innerHTML=o.map(function(v){return'<li><a href="'+r+'v/'+v[2]+'.html">'+e(v[0])+'<span>'+e(v[1])+'</span></a></li>'}).join('')||'<li class="none">見つかりません</li>'})})})();"""


def ad(kind):
    c, s = CFG["adsense_client"], CFG["ad_slots"].get(kind, "")
    if c and s:
        return (f'<aside class="adw"><ins class="adsbygoogle" style="display:block" data-ad-client="{esc(c)}" data-ad-slot="{esc(s)}" '
                'data-ad-format="auto" data-full-width-responsive="true"></ins><script>(adsbygoogle=window.adsbygoogle||[]).push({});</script></aside>')
    return f'<aside class="adw ph"><small>広告</small>広告枠({kind}):config.json にAdSenseの設定を入れると表示されます</aside>' if CFG["show_ad_placeholders"] else ""


def page(root, path, title, desc, body, noindex=False):
    name = CFG["site_name"]
    ads = (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={esc(CFG["adsense_client"])}" crossorigin="anonymous"></script>'
           if CFG["adsense_client"] else "")
    canon = f'<link rel="canonical" href="{esc(CFG["base_url"].rstrip("/") + "/" + path)}">' if CFG["base_url"] else ""
    robots = '<meta name="robots" content="noindex">' if noindex else ""
    out = DIST / path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"""<!DOCTYPE html><html lang="ja" data-root="{root}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><meta name="description" content="{esc(desc)}">{robots}{canon}
<style>{CSS}</style>{ads}</head><body>
<header><div class="hb"><a class="logo" href="{root}index.html">{esc(name)}</a>
<div class="sw"><input id="sk" type="search" placeholder="会場名で検索" aria-label="会場名で検索" autocomplete="off"><ul id="sr"></ul></div></div></header>
<main>{body}</main>
<footer><div><a href="{root}about.html">運営について</a><a href="{root}privacy.html">プライバシーポリシー</a><a href="{root}contact.html">お問い合わせ</a>
<p>会場データ © <a href="https://www.openstreetmap.org/copyright" rel="noopener">OpenStreetMap contributors</a>(ODbL)。紹介文にはAIが作成した下書きを含みます。<br>© {esc(name)}</p></div></footer>
<script>{JS}</script></body></html>""", "utf-8")


def render(venues, desc):
    import shutil
    shutil.rmtree(DIST, ignore_errors=True)
    DIST.mkdir()
    name, by_pref = CFG["site_name"], {}
    for v in venues:
        by_pref.setdefault(v["pref"], []).append(v)
    for l in by_pref.values():
        l.sort(key=lambda v: v["name"])
    urls = ["index.html"]

    # トップ
    grid = ""
    for i, (rn, codes) in enumerate(REG):
        grid += f'<div class="pg" style="--c:var(--r{i % 7 + 1})">'
        for c in codes:
            grid += f'<a href="pref/{c}.html">{PREFS[c-1]}<i>{len(by_pref.get(c, []))}</i></a>'
        grid += "</div>"
    body = (f'<section class="top"><p>{esc(CFG["tagline"])}</p><h1>{esc(name)}</h1><p class="num">{len(venues):,}</p><p>掲載会場数</p></section>'
            f'{ad("top")}<h2>エリアから会場を探す</h2>{grid}{ad("mid")}{ad("bottom")}')
    page("", "index.html", f"{name} | {CFG['tagline']}", f"全国のライブ・コンサート会場を都道府県別に探せます。掲載数{len(venues):,}件。", body)

    # 都道府県ページ
    for c in range(1, 48):
        vs = by_pref.get(c, [])
        li = "".join(f'<li><a href="../v/{v["id"]}.html">{esc(v["name"])}<small>{KINDS[v["kind"]]}</small></a></li>' for v in vs)
        body = (f'<p class="bc"><a href="../index.html">トップ</a> › {PREFS[c-1]}</p><h1>{PREFS[c-1]}のライブ・コンサート会場({len(vs)}件)</h1>'
                f'{ad("top")}<ul class="list">{li or "<li><a>該当する会場はまだありません</a></li>"}</ul>{ad("bottom")}')
        page("../", f"pref/{c}.html", f"{PREFS[c-1]}のライブ会場一覧 | {name}", f"{PREFS[c-1]}のライブハウス、ホール、スタジアムなど{len(vs)}件の会場一覧。", body, noindex=not vs)
        if vs:
            urls.append(f"pref/{c}.html")

    # 会場ページ
    for c, vs in by_pref.items():
        for v in vs:
            d = desc.get(v["id"], {}).get("text", "")
            near = sorted((o for o in vs if o is not v and o["kind"] == v["kind"]),
                          key=lambda o: (o["lat"] - v["lat"]) ** 2 + (o["lon"] - v["lon"]) ** 2)[:6]
            rel = "".join(f'<li><a href="{o["id"]}.html">{esc(o["name"])}</a></li>' for o in near)
            rows = f'<tr><th>種類</th><td>{KINDS[v["kind"]]}</td></tr><tr><th>所在地</th><td>{PREFS[c-1]}{esc(v["addr"])}</td></tr>'
            if v["capacity"]:
                rows += f'<tr><th>収容人数</th><td>{esc(v["capacity"])}</td></tr>'
            if v["website"].startswith("http"):
                rows += f'<tr><th>公式サイト</th><td><a href="{esc(v["website"])}" rel="nofollow noopener" target="_blank">{esc(v["website"])}</a></td></tr>'
            rows += f'<tr><th>地図</th><td><a href="https://www.openstreetmap.org/?mlat={v["lat"]}&amp;mlon={v["lon"]}#map=17/{v["lat"]}/{v["lon"]}" rel="noopener" target="_blank">地図で見る</a></td></tr>'
            body = (f'<p class="bc"><a href="../index.html">トップ</a> › <a href="../pref/{c}.html">{PREFS[c-1]}</a> › {esc(v["name"])}</p>'
                    f'<h1>{esc(v["name"])}</h1><span class="tag">{KINDS[v["kind"]]}</span>{ad("top")}'
                    f'<div class="card">{"<p>" + esc(d) + "</p>" if d else ""}<table>{rows}</table>'
                    '<p class="note">情報は変更されている場合があります。お出かけ前に公式情報をご確認ください。</p></div>'
                    f'{ad("mid")}{"<h2>近くの同じ種類の会場</h2><ul class=list>" + rel + "</ul>" if rel else ""}{ad("bottom")}')
            page("../", f"v/{v['id']}.html", f"{v['name']}({PREFS[c-1]}) | {name}",
                 (d[:110] if d else f"{PREFS[c-1]}の{KINDS[v['kind']]}「{v['name']}」の会場情報。"), body, noindex=not d)
            if d:
                urls.append(f"v/{v['id']}.html")

    # 固定ページ(AdSense審査に必要。内容は必ず確認・修正してください)
    mail = esc(CFG["contact_email"] or "(config.json の contact_email を設定してください)")
    static = {
        "about": ("運営について", f"<p>{esc(name)}は、全国のライブ・コンサート会場の情報をまとめたサイトです。会場の基本情報はOpenStreetMapの公開データをもとにしており、紹介文はAIで下書きしたものを含みます。情報の誤りや変更にお気づきの場合はお問い合わせください。</p>"),
        "privacy": ("プライバシーポリシー", "<p>当サイトは、Google AdSenseなどの第三者配信の広告サービスを利用することがあります。広告配信事業者は、Cookieを使用して、ユーザーが当サイトや他のサイトに過去にアクセスした際の情報に基づいて広告を配信します。Cookieを無効にする設定やGoogleによる広告のパーソナライズの無効化は、Googleの広告設定ページから行えます。</p><p>当サイトでは、アクセス状況の把握のためにアクセス解析ツールを利用する場合があります。収集される情報に個人を特定するものは含まれません。</p><p>当サイトの掲載情報の正確性には注意していますが、利用者が当サイトの情報を用いて行う行動の結果について、責任を負いかねます。</p>"),
        "contact": ("お問い合わせ", f"<p>会場情報の修正依頼やご意見は、次のメールアドレスまでご連絡ください。</p><p>{mail}</p>"),
    }
    for k, (t, b) in static.items():
        page("", f"{k}.html", f"{t} | {name}", t, f"<h1>{t}</h1><div class=card>{b}</div>")
        urls.append(f"{k}.html")

    (DIST / "search.json").write_text(json.dumps([[v["name"], PREFS[v["pref"]-1], v["id"]] for v in venues], ensure_ascii=False, separators=(",", ":")), "utf-8")
    if CFG["base_url"]:
        b, today = CFG["base_url"].rstrip("/"), datetime.date.today().isoformat()
        (DIST / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(f"<url><loc>{esc(b + '/' + u)}</loc><lastmod>{today}</lastmod></url>" for u in urls) + "</urlset>", "utf-8")
        (DIST / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {b}/sitemap.xml\n", "utf-8")
    if CFG["adsense_client"]:
        (DIST / "ads.txt").write_text(f"google.com, {CFG['adsense_client'].replace('ca-', '')}, DIRECT, f08c47fec0942fa0\n", "utf-8")
    print(f"生成完了: 会場 {len(venues)} 件 / 公開ページ(index可) {len(urls)} 件")


def main():
    DATA.mkdir(exist_ok=True)
    d = load_data()
    if "--no-fetch" not in sys.argv and stale_prefs(d):
        fetch_some(d)
    venues = load_data()["venues"]
    desc = describe(venues)
    unrev = sum(1 for v in venues if v["id"] in desc and not desc[v["id"]].get("reviewed"))
    print(f"未確認の紹介文: {unrev} 件 / 紹介文なし: {sum(1 for v in venues if v['id'] not in desc)} 件")
    render(venues, desc)


if __name__ == "__main__":
    main()
