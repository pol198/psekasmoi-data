"""Builds a compact JSON of the ministry PPP database for the logbook app."""
import json, collections, datetime, re, sys, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jet4 import MDB

MDB_PATH, LIST_PATH, OUT_DIR = sys.argv[1], sys.argv[2], sys.argv[3]
SITE_DATE = sys.argv[4] if len(sys.argv) > 4 else ""   # ημερομηνία βάσης από τη σελίδα του ΥΠΑΑΤ (YYYY-MM-DD)
_m = MDB(MDB_PATH)
_cache = {}
def R(n):
    if n not in _cache: _cache[n] = list(_m.rows(_m.table(n)))
    return _cache[n]
TODAY = datetime.datetime.now()

def ki(x):
    return None if x is None else int(x)

# ---------- kinds ----------
KIND = {"IN": "Εντομοκτόνο", "AC": "Ακαρεοκτόνο", "NE": "Νηματωδοκτόνο", "RO": "Τρωκτικοκτόνο",
        "MO": "Σαλιγκαροκτόνο", "FU": "Μυκητοκτόνο", "HB": "Ζιζανιοκτόνο", "PG": "Ρυθμιστής ανάπτυξης",
        "AT": "Εντομοελκυστικό", "OT": "Άλλο φυτοπροστατευτικό", "CF": "Μικτό", "BA": "Βακτηριοκτόνο"}

# ---------- products ----------
farmako = {ki(r['KOD_FARMAK']): r for r in R('FARMAKO') if r['KOD_FARMAK'] is not None}
actives = collections.defaultdict(list)
for r in R('SKEYASMATA-DRONTA-CROPS-Total'):
    k = ki(r['KOD_FARMAK']); n = (r['ONOMADRON'] or '').split(' / (CAS')[0].strip()
    if n and n not in actives[k]: actives[k].append(n)
sys_names = {r['KODIKOS']: r['ONOMADRON'] for r in R('SYSTATIK')}
for r in R('FARM_DRO'):
    k = ki(r['KOD_FARMAK'])
    if k in actives: continue
    n = sys_names.get(r['KODIKOS'])
    if n: actives.setdefault(k, [])
    if n and n not in actives[k]: actives[k].append(n.split(' / (CAS')[0])

products = []   # [name, authNo, kind, actives, status, stockUntil, form]
seen = set()
for r in R('SKEYASMATA-professional'):
    st = r['APOSYRSH']; k = ki(r['KOD_FARMAK']); name = (r['EMPORIKHON'] or '').strip()
    if not name or k is None: continue
    if st == 'O':
        continue  # old names of renamed products
    stock = r['ΛΗΞΗ ΔΙΑΘΕΣΗΣ ΑΠΟΘΕΜΑΤΩΝ']
    if st == '-':
        if not stock or stock < TODAY: continue
        status = 'g'   # withdrawn, stock may still be sold/used until date
    elif st == 'P': status = 'p'   # parallel import
    elif st == 'E': status = 'e'   # amateur use only
    else: status = 'a'
    key = (k, name)
    if key in seen: continue
    seen.add(key)
    fm = farmako.get(k, {})
    products.append([name, k, r['EDR_COD_KAT'] or fm.get('EDR_COD_KAT') or 'OT',
                     ' + '.join(actives.get(k, [])[:4]), status,
                     stock.strftime('%Y-%m-%d') if (status == 'g' and stock) else '',
                     fm.get('MORFHSKEYA') or ''])
products.sort(key=lambda p: p[0].upper())
kods = sorted({p[1] for p in products})

# ---------- crops ----------
TREES = {'ΜΗΛΟΕΙΔΗ', 'ΠΥΡΗΝΟΚΑΡΠΑ', 'ΑΚΡΟΔΡΥΑ', 'ΕΣΠΕΡΙΔΟΕΙΔΗ', 'ΝΩΠΑ ΦΡΟΥΤΑ-ΑΠΟΞΗΡ.ΟΠΩΡΕΣ', 'ΑΜΠΕΛΙ', 'ΕΛΙΑ'}
ARABLE = {'ΣΙΤΗΡΑ', 'ΒΙΟΜ/ΚΑ ΚΑΙ ΑΡΩΜ/ΚΑ ΦΥΤΑ', 'ΚΤΗΝΟΤΡΟΦΙΚΑ ΦΥΤΑ', 'ΨΥΧΑΝΘΗ', 'ΟΣΠΡΙΑ, ΞΗΡΑ', 'ΛΟΙΠΕΣ ΚΑΛΛΙΕΡΓΕΙΕΣ'}
VEG = {'ΛΑΧΑΝΙΚΑ ΥΠ.', 'ΛΑΧΑΝΙΚΑ ΘΕΡΜΟΚ.', 'ΛΑΧΑΝΙΚΑ', 'ΚΑΛΛΙΕΡΓΕΙΕΣ ΣΕ ΤΟΥΝΕΛ', 'ΝΩΠΑ ΦΡΟΥΤΑ ΘΕΡΜ.'}
SKIP = {'ΚΤΙΡΙΑ', 'ΜΕΣΑ ΜΕΤΑΦΟΡΑΣ', 'ΑΠΟΘΗΚΕΥΜΕΝΑ ΠΡΟΪΟΝΤΑ', 'ΕΔΑΦΟΣ'}
def group(k):
    if k in TREES: return 't'
    if k in ARABLE: return 'a'
    if k in VEG: return 'v'
    return 'o'

appr_rows = [r for r in R('FARMAKA-CROP-SKEYASMATA') if ki(r['KOD_FARMAK']) in set(kods)]
used = {ki(r['CODE_FYTA']) for r in appr_rows}
crops = []
for r in R('CROPS'):
    c = ki(r['CODE_FYTA']); n = (r['EIDOS'] or '').strip()
    if c is None or not n or c == 1000000: continue
    if (r['KATHG'] or '') in SKIP: continue
    if c not in used and not r['GENERAL']: continue
    crops.append([c, n, group(r['KATHG'] or ''), (r['KATHG'] or '').strip()])
crops.sort(key=lambda x: x[1])
crop_codes = {c[0] for c in crops}

# ---------- approvals product x crop ----------
appr = collections.defaultdict(set)
for r in appr_rows:
    appr[ki(r['KOD_FARMAK'])].add(ki(r['CODE_FYTA']))

# ---------- PHI ----------
phi = collections.defaultdict(dict)
notes = []
note_idx = {}
for r in R('EPEMBASH'):
    k = ki(r['KOD_FARMAK']); c = ki(r['CODE_FYTA'])
    if k not in appr: continue
    d = r['DIAST_PROS']; cm = (r['COMMENTS'] or '').strip()
    if cm in ('-', '--', '---', '----') or not cm.strip('-. '): cm = ''
    prev = phi[k].get(c)
    val = int(d) if d is not None else None
    if prev is not None and prev[0] is not None and val is not None and prev[0] >= val: continue
    if cm and cm not in note_idx: note_idx[cm] = len(notes); notes.append(cm)
    phi[k][c] = (val, note_idx[cm] if cm else -1)

# ---------- targets ----------
zoik = {r['CODE_ZOOY']: (r['GREECE'] or r['ONOMA1'] or r['CODE_ZOOY']) for r in R('ZOIKOI')}
asth = {r['CODE_ASTEN']: r['ASTENIA'] for r in R('ASTHENIA')}
bfun = {r['FBCODE']: (r['GREECE'] or r['KLARTEXT'] or r['FBCODE']) for r in R('BFUNC')}
herb = {}
for r in R('ΣΚΕΥΑΣΜΑΤΑ_ΕΛΛΗΝΙΚΑ_ZIZANIA-CROPS-ft'):
    if r['KOD_HERB'] is not None and r['ZIZANIO']:
        herb[ki(r['KOD_HERB'])] = r['ZIZANIO']
dosh = {ki(r['KOD_DOSHS']): r['DOSH'] for r in R('DOSH')}

def clean_t(s):
    s = re.sub(r'\s+', ' ', str(s)).strip()
    if ' | ' in s:  # "Latin | ελληνικό"
        lat, gr = s.split(' | ', 1)
        return (gr.strip()[:1].upper() + gr.strip()[1:]) + ' (' + lat.strip() + ')'
    return s

targets = []; t_idx = {}
def tid(name):
    name = clean_t(name)
    if name not in t_idx: t_idx[name] = len(targets); targets.append(name)
    return t_idx[name]
doses = []; d_idx = {}
def did(val, unit):
    if not val: return -1
    s = (str(val).strip() + ' ' + (dosh.get(unit) or '')).strip()
    if s not in d_idx: d_idx[s] = len(doses); doses.append(s)
    return d_idx[s]

counter_map = collections.defaultdict(list)  # (k, crop) -> [(t, d)]
def add_links(link_table, detail_rows, name_fn):
    by_counter = collections.defaultdict(list)
    for r in detail_rows: by_counter[ki(r['COUNTER'])].append(r)
    for r in R(link_table):
        k = ki(r['KOD_FARMAK']); c = ki(r['CODE_FYTA'])
        if k not in appr or c is None: continue
        for d in by_counter.get(ki(r['COUNTER']), []):
            n = name_fn(d)
            if not n: continue
            counter_map[(k, c)].append((tid(n), did(d.get('DOSH_FARM'), ki(d.get('KOD_DOSHS')))))

add_links('FARMKZOA', R('ZOAFARM'), lambda d: zoik.get(d['CODE_ZOOY']))
add_links('FARMKAST', R('ASTFARM'), lambda d: (bfun.get(d['FBCODE']) if d['FBCODE'] else None) or asth.get(d['CODE_ASTEN']))
add_links('FARMKZIZ', R('ZIZ_FARM'), lambda d: herb.get(ki(d['KOD_HERB'])))

# ---------- assemble compact structure ----------
crop_i = {c[0]: i for i, c in enumerate(crops)}
all_codes = {}
def code_ref(c):
    return crop_i.get(c, None)

out_products = []
for p in products:
    k = p[1]
    a = sorted({crop_i[c] for c in appr.get(k, ()) if c in crop_i})
    ph = []
    for c, (val, ni) in phi.get(k, {}).items():
        if c in crop_i: ph.append([crop_i[c], val if val is not None else -1, ni])
    tg = []
    for c in appr.get(k, ()):
        if c not in crop_i: continue
        lst = counter_map.get((k, c))
        if not lst: continue
        dd = {}
        for t, d in lst:
            if t not in dd or (dd[t] == -1 and d != -1): dd[t] = d
        tg.append([crop_i[c], [x for pair in sorted(dd.items()) for x in pair]])
    out_products.append(p + [a, sorted(ph), sorted(tg)])

# ---------- news: ministry decisions (from LIST-TKINISI-DATE xls) ----------
import pandas as pd
news = []
xl = [LIST_PATH] if LIST_PATH and os.path.exists(LIST_PATH) else []
data_date = None
if xl:
    df = pd.read_excel(xl[0], header=0)
    df.columns = ['date','aada','cat','x','subject','prot','link']
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date'])
    data_date = df['date'].max()
    recent = df[df['date'] >= data_date - pd.Timedelta(days=120)].sort_values('date', ascending=False)
    for _, r in recent.iterrows():
        kod = str(r['aada']).split('/')[0].strip().split('.')[0]
        subj = re.sub(r'\s+', ' ', str(r['subject'])).strip()
        link = str(r['link']) if isinstance(r['link'], str) and r['link'].startswith('http') else ''
        news.append([r['date'].strftime('%Y-%m-%d'), kod, subj, link])
UPDATED = max([d for d in [data_date.strftime('%Y-%m-%d') if data_date is not None else '', SITE_DATE] if d] or [TODAY.strftime('%Y-%m-%d')])

db = {
    "v": 1,
    "source": "ΥΠΑΑΤ – Βάση Φυτοπροστατευτικών Προϊόντων (Syspest)",
    "updated": UPDATED,
    "news": news,
    "kinds": KIND,
    "groups": {"t": "Δενδρώδη & αμπέλι", "a": "Αροτραίες", "v": "Κηπευτικά", "o": "Άλλες"},
    "crops": crops,
    "notes": notes,
    "targets": targets,
    "doses": doses,
    "products": out_products,
}
s = json.dumps(db, ensure_ascii=False, separators=(',', ':'))
open(os.path.join(OUT_DIR, 'ppp-db.json'), 'w', encoding='utf-8').write(s)
meta = {"updated": UPDATED, "products": len(out_products), "news": len(news), "bytes": len(s.encode())}
open(os.path.join(OUT_DIR, 'ppp-meta.json'), 'w', encoding='utf-8').write(json.dumps(meta, ensure_ascii=False))
print('meta', meta)
st = collections.Counter(p[4] for p in products)
print('products', len(products), st, 'crops', len(crops), 'targets', len(targets), 'doses', len(doses), 'notes', len(notes))
print('size MB', round(len(s.encode()) / 1e6, 2))
